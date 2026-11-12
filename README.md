# Gideon

A local-first personal AI assistant for your own computer. Gideon combines a clean browser interface with local chat, voice, web search, and an optional ChatGPT Plus connection. The default setup needs no paid API key.

![Gideon is built on OpenJarvis](https://img.shields.io/badge/built%20on-OpenJarvis-5b55c8)

## Features

- Local Qwen2.5 chat through Ollama, with a model picker and conversation history.
- Optional ChatGPT Plus sign-in for eligible plan models; the billed OpenAI API is separate.
- Local Faster-Whisper dictation and Kokoro spoken replies.
- Keyless web search, with optional Tavily support.
- Research, agents, data-source, dashboard, and settings views from the underlying OpenJarvis framework.
- A Muse shortcut that opens Muse separately.

## Quick start

Install [Ollama](https://ollama.com/download), [uv](https://docs.astral.sh/uv/getting-started/installation/), and Node.js 22 or newer. On macOS:

```sh
git clone https://github.com/Axinion/Gideon.git
cd Gideon
uv sync --extra desktop --extra voice
ollama pull qwen2.5:1.5b-instruct
./gideon gui
```

Open <http://127.0.0.1:5173/> if it does not open automatically. See [START-HERE.md](START-HERE.md) for setup and optional services.

The first launch creates `.openjarvis/config.toml` from [the local configuration template](configs/gideon.local.toml). That directory holds local data and credentials and is ignored by Git. The app binds its API to `127.0.0.1` by default, and external analytics are disabled in the template.

## Open source and attribution

Gideon is a customized build of [OpenJarvis](https://github.com/open-jarvis/OpenJarvis), developed by the Stanford SAIL research community. The underlying Python package and command remain named `openjarvis` and `jarvis` for compatibility. The original project README is preserved as [UPSTREAM-README.md](UPSTREAM-README.md), and its [Apache 2.0 license](LICENSE) remains in this repository.
