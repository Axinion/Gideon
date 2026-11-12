"""Local Sign in with ChatGPT connection for an optional plan-backed chat mode.

Only the local FastAPI process sees OAuth credentials. Browser code receives
account display data and model names, never access or refresh tokens.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import secrets
import tempfile
import time
import uuid
from pathlib import Path
from urllib.parse import urlencode, urlparse

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse

from openjarvis.core.paths import get_config_dir

router = APIRouter()

_ISSUER = "https://auth.openai.com"
_AUTHORIZE = f"{_ISSUER}/api/accounts/authorize"
_TOKEN = f"{_ISSUER}/api/accounts/oauth/token"
_JWKS = f"{_ISSUER}/.well-known/jwks.json"
_RESOURCE = "https://api.openai.com/v1"
_SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
_COOKIE = "openjarvis_chatgpt_session"
_PENDING: dict[str, dict] = {}
_REFRESH_LOCK = asyncio.Lock()


def _path() -> Path:
    return get_config_dir() / "chatgpt-plan.json"


def _read() -> dict:
    try:
        return json.loads(_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"host_id": f"urn:uuid:{uuid.uuid4()}", "profiles": {}}


def _write(data: dict) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".chatgpt-plan-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(data, output)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _session(request: Request, data: dict) -> bool:
    presented = request.cookies.get(_COOKIE, "")
    expected = data.get("session_token", "")
    return bool(presented and expected and secrets.compare_digest(presented, expected))


def _active_profile(data: dict) -> dict | None:
    return data.get("profiles", {}).get(data.get("active_client_id", ""))


def _return_url(request: Request) -> str:
    origin = request.headers.get("origin", "")
    parsed = urlparse(origin)
    if parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}:
        return f"{origin.rstrip('/')}/settings"
    return "http://127.0.0.1:5173/settings"


def _callback_uri(request: Request) -> str:
    # Vite proxies this request to the API process and changes Host to the API
    # target. The OAuth redirect itself must always use the loopback IP.
    port = request.url.port or 8000
    return f"http://127.0.0.1:{port}/auth/chatgpt/callback"


def _require_profile(request: Request) -> tuple[dict, dict]:
    data = _read()
    if not _session(request, data):
        raise HTTPException(401, "Connect ChatGPT from Jarvis Settings first.")
    profile = _active_profile(data)
    if not profile or not profile.get("access_token"):
        raise HTTPException(401, "ChatGPT needs a new sign-in.")
    if "chatgpt.tokens.use.direct" not in profile.get("scopes", []):
        raise HTTPException(403, "ChatGPT plan usage was not authorized.")
    return data, profile


async def _token_request(fields: dict) -> dict:
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(_TOKEN, data=fields)
    if response.status_code != 200:
        # Do not place OAuth credentials or response bodies into browser errors.
        raise HTTPException(502, f"ChatGPT sign-in failed ({response.status_code}). Try again.")
    return response.json()


async def _access_token(data: dict, profile: dict) -> str:
    if profile.get("saved_at", 0) + profile.get("expires_in", 0) > time.time() + 90:
        return profile["access_token"]
    async with _REFRESH_LOCK:
        fresh = _read()
        current = fresh.get("profiles", {}).get(profile["client_id"])
        if not current or not current.get("refresh_token"):
            raise HTTPException(401, "ChatGPT needs a new sign-in.")
        if current.get("saved_at", 0) + current.get("expires_in", 0) > time.time() + 90:
            return current["access_token"]
        tokens = await _token_request({
            "grant_type": "refresh_token",
            "client_id": current["client_id"],
            "refresh_token": current["refresh_token"],
            "resource": _RESOURCE,
        })
        if not tokens.get("access_token") or not tokens.get("refresh_token"):
            raise HTTPException(502, "ChatGPT did not renew the session. Sign in again.")
        current.update({
            "access_token": tokens["access_token"],
            "refresh_token": tokens["refresh_token"],
            "expires_in": tokens.get("expires_in", 3600),
            "saved_at": time.time(),
            "scopes": tokens.get("scope", "").split() or current.get("scopes", []),
        })
        _write(fresh)
        return current["access_token"]


@router.post("/v1/chatgpt/start")
async def start(request: Request):
    data = _read()
    if not _path().exists():
        _write(data)
    body = await request.json()
    new_account = bool(body.get("new_account"))
    profile = None if new_account else _active_profile(data)
    client_id = (
        "dynamic_agent_client" if new_account
        else profile["client_id"] if profile
        else data.get("pending_client_id", "dynamic_agent_client")
    )
    session_token = secrets.token_urlsafe(32)
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    redirect_uri = _callback_uri(request)
    _PENDING[state] = {
        "nonce": nonce,
        "verifier": verifier,
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "return_url": _return_url(request),
        "session_token": session_token,
        "created_at": time.time(),
        "original_subject": profile.get("subject") if profile else None,
    }
    params = {
        "client_id": client_id,
        "ext_agent_host_id": data["host_id"],
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": _SCOPES,
        "resource": _RESOURCE,
        "state": state,
        "nonce": nonce,
        "code_challenge_method": "S256",
        "code_challenge": challenge,
    }
    if client_id == "dynamic_agent_client":
        params["agent_name_hint"] = "OpenJarvis"
    if profile and profile.get("email"):
        params["login_hint"] = profile["email"]
    if profile and "chatgpt.tokens.use.direct" not in profile.get("scopes", []):
        params["prompt"] = "consent"
    response = JSONResponse({"authorization_url": f"{_AUTHORIZE}?{urlencode(params)}"})
    response.set_cookie(_COOKIE, session_token, httponly=True, samesite="lax", path="/")
    return response


@router.get("/auth/chatgpt/callback")
async def callback(request: Request):
    state = request.query_params.get("state", "")
    pending = _PENDING.pop(state, None)
    if not pending or time.time() - pending["created_at"] > 600:
        raise HTTPException(400, "ChatGPT sign-in expired. Start again in Jarvis Settings.")
    if not secrets.compare_digest(request.cookies.get(_COOKIE, ""), pending["session_token"]):
        raise HTTPException(400, "ChatGPT sign-in could not be verified.")
    if request.query_params.get("error"):
        return RedirectResponse(f"{pending['return_url']}?chatgpt=cancelled", status_code=303)
    code = request.query_params.get("code", "")
    issued_id = request.query_params.get("client_id", "")
    expected_id = pending["client_id"]
    if expected_id == "dynamic_agent_client":
        if not issued_id.startswith("oaiapp_"):
            raise HTTPException(400, "ChatGPT did not return a client registration.")
        client_id = issued_id
        data = _read()
        data["pending_client_id"] = client_id
        _write(data)
    else:
        if issued_id and issued_id != expected_id:
            raise HTTPException(400, "ChatGPT returned a different client registration.")
        client_id = expected_id
    if not code:
        raise HTTPException(400, "ChatGPT did not return an authorization code.")
    tokens = await _token_request({
        "grant_type": "authorization_code",
        "client_id": client_id,
        "code": code,
        "code_verifier": pending["verifier"],
        "redirect_uri": pending["redirect_uri"],
        "resource": _RESOURCE,
    })
    if not all(tokens.get(k) for k in ("id_token", "access_token", "refresh_token")):
        raise HTTPException(502, "ChatGPT did not return a complete session.")
    try:
        import jwt

        signing_key = await asyncio.to_thread(
            jwt.PyJWKClient(_JWKS).get_signing_key_from_jwt, tokens["id_token"]
        )
        identity = jwt.decode(
            tokens["id_token"], signing_key.key,
            algorithms=["RS256", "ES256"], audience=client_id, issuer=_ISSUER,
            leeway=5, options={"require": ["sub", "exp", "iat"]},
        )
    except Exception as exc:
        raise HTTPException(502, "ChatGPT identity could not be verified.") from exc
    if identity.get("nonce") != pending["nonce"]:
        raise HTTPException(400, "ChatGPT identity nonce did not match.")
    if pending["original_subject"] and identity["sub"] != pending["original_subject"]:
        raise HTTPException(400, "This is a different ChatGPT account. Choose Add account.")
    data = _read()
    scopes = tokens.get("scope", "").split()
    data.setdefault("profiles", {})[client_id] = {
        "client_id": client_id,
        "subject": identity["sub"],
        "email": identity.get("email", ""),
        "name": identity.get("name", ""),
        "id_token": tokens["id_token"],
        "access_token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
        "expires_in": tokens.get("expires_in", 3600),
        "saved_at": time.time(),
        "scopes": scopes,
    }
    data["active_client_id"] = client_id
    data["session_token"] = pending["session_token"]
    data.pop("pending_client_id", None)
    _write(data)
    outcome = "connected" if "chatgpt.tokens.use.direct" in scopes else "no-plan-access"
    return RedirectResponse(f"{pending['return_url']}?chatgpt={outcome}", status_code=303)


@router.get("/v1/chatgpt/status")
async def status(request: Request):
    data = _read()
    if not _session(request, data):
        return {"connected": False, "plan_enabled": False, "profiles": []}
    profile = _active_profile(data)
    return {
        "connected": bool(profile and profile.get("access_token")),
        "plan_enabled": bool(profile and "chatgpt.tokens.use.direct" in profile.get("scopes", [])),
        "email": profile.get("email", "") if profile else "",
        "profiles": [
            {"client_id": key, "email": value.get("email", ""), "active": key == data.get("active_client_id")}
            for key, value in data.get("profiles", {}).items()
        ],
    }


@router.post("/v1/chatgpt/select")
async def select_profile(request: Request):
    data = _read()
    if not _session(request, data):
        raise HTTPException(401, "Connect ChatGPT from Jarvis Settings first.")
    body = await request.json()
    client_id = body.get("client_id", "")
    if client_id not in data.get("profiles", {}):
        raise HTTPException(404, "Saved ChatGPT account not found.")
    data["active_client_id"] = client_id
    _write(data)
    return {"selected": True}


@router.post("/v1/chatgpt/disconnect")
async def disconnect(request: Request):
    data = _read()
    if not _session(request, data):
        raise HTTPException(401, "No ChatGPT connection is active in this browser.")
    profile = _active_profile(data)
    remote_revoked = False
    if profile and profile.get("refresh_token"):
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                discovery = await client.get(f"{_ISSUER}/.well-known/openid-configuration")
                discovery.raise_for_status()
                endpoint = discovery.json().get("revocation_endpoint", "")
                if urlparse(endpoint).scheme == "https" and urlparse(endpoint).hostname == "auth.openai.com":
                    response = await client.post(endpoint, data={
                        "token": profile["refresh_token"],
                        "token_type_hint": "refresh_token",
                        "client_id": profile["client_id"],
                    })
                    remote_revoked = response.status_code == 200
        except (httpx.HTTPError, ValueError):
            pass
        for key in ("access_token", "refresh_token", "id_token"):
            profile.pop(key, None)
        profile["scopes"] = []
    data.pop("session_token", None)
    _write(data)
    response = JSONResponse({"disconnected": True, "remote_revoked": remote_revoked})
    response.delete_cookie(_COOKIE, path="/")
    return response


@router.get("/v1/chatgpt/models")
async def models(request: Request):
    data, profile = _require_profile(request)
    token = await _access_token(data, profile)
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(f"{_RESOURCE}/models", headers={"Authorization": f"Bearer {token}"})
    if response.status_code != 200:
        raise HTTPException(response.status_code, "ChatGPT models are unavailable. Check your plan access.")
    payload = response.json()
    listed = payload.get("models", payload.get("data", []))
    return {"data": [
        {"id": f"chatgpt/{model['slug']}", "owned_by": "chatgpt", "display_name": model.get("display_name", model["slug"])}
        for model in listed if model.get("visibility") == "list" and model.get("slug")
    ]}


@router.post("/v1/chatgpt/completions")
async def completions(request: Request):
    data, profile = _require_profile(request)
    body = await request.json()
    model = body.get("model", "")
    if not isinstance(model, str) or not model.startswith("chatgpt/"):
        raise HTTPException(400, "Choose a ChatGPT plan model.")
    slug = model.removeprefix("chatgpt/")
    if not slug or len(slug) > 100:
        raise HTTPException(400, "Invalid ChatGPT model.")
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        raise HTTPException(400, "A chat message is required.")
    token = await _access_token(data, profile)
    input_items = [
        {"role": "developer" if item["role"] == "system" else item["role"], "content": item["content"]}
        for item in messages
        if isinstance(item, dict)
        and item.get("role") in {"user", "assistant", "system", "developer"}
        and isinstance(item.get("content"), str)
    ]
    if not input_items:
        raise HTTPException(400, "A text message is required.")

    async def generate():
        completed = False
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(None, connect=20)) as client:
                async with client.stream(
                    "POST", f"{_RESOURCE}/responses",
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                    json={"model": slug, "input": input_items, "store": False, "stream": True},
                ) as response:
                    if response.status_code != 200:
                        raw = await response.aread()
                        try:
                            problem = json.loads(raw)
                            code = (problem.get("error") or {}).get("code", "")
                        except (ValueError, AttributeError):
                            code = ""
                        message = (
                            "ChatGPT plan limit reached. Manage usage in ChatGPT settings."
                            if code == "subscription_sharing_usage_limit_exceeded"
                            else f"ChatGPT request failed ({response.status_code}{': ' + code if code else ''}). Review plan access in ChatGPT settings."
                        )
                        yield f"event: error\ndata: {json.dumps({'error': message})}\n\n"
                        return
                    async for line in response.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        try:
                            event = json.loads(line[6:])
                        except json.JSONDecodeError:
                            continue
                        kind = event.get("type")
                        if kind == "response.output_text.delta":
                            chunk = {"choices": [{"delta": {"content": event.get("delta", "")}, "finish_reason": None}], "telemetry": {"engine": "chatgpt"}}
                            yield f"data: {json.dumps(chunk)}\n\n"
                        elif kind == "response.completed":
                            completed = True
                            chunk = {"choices": [{"delta": {}, "finish_reason": "stop"}], "telemetry": {"engine": "chatgpt"}}
                            yield f"data: {json.dumps(chunk)}\n\n"
                            yield "data: [DONE]\n\n"
                            return
                        elif kind in {"response.failed", "response.incomplete", "error"}:
                            code = (event.get("response") or {}).get("error") or event.get("error") or {}
                            detail = code.get("code", kind) if isinstance(code, dict) else kind
                            yield f"event: error\ndata: {json.dumps({'error': f'ChatGPT stopped: {detail}. Check ChatGPT usage settings.'})}\n\n"
                            return
        except httpx.HTTPError:
            yield f"event: error\ndata: {json.dumps({'error': 'Could not reach ChatGPT. Try again.'})}\n\n"
            return
        if not completed:
            yield f"event: error\ndata: {json.dumps({'error': 'ChatGPT stream ended before completion.'})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
