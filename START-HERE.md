# Start Gideon

Gideon is a local-first personal AI app built on the Apache 2.0-licensed [OpenJarvis](https://github.com/open-jarvis/OpenJarvis) framework. The default Qwen2.5 1.5B model runs on your computer through Ollama. Voice input uses Faster-Whisper, spoken replies use Kokoro, and web search works without a key. No paid API key is required.

## Set up on macOS

Install [Ollama](https://ollama.com/download), [uv](https://docs.astral.sh/uv/getting-started/installation/), and Node.js 22 or newer. Then run from this repository:

```sh
uv sync --extra desktop --extra voice
ollama pull qwen2.5:1.5b-instruct
./gideon gui
```

The browser app opens at `http://127.0.0.1:5173/`. Keep the terminal open while using it. The first voice request may download free Kokoro voice files and a speech language model.

For a command-line question, run `./gideon ask "Hello, Gideon"`.

## Optional services

- **ChatGPT Plus:** In Settings, choose **Continue with ChatGPT** and authorize the app. Plan usage is separate from the billed OpenAI API. To avoid extra credit spending after plan limits, disable credit use in ChatGPT's Manage usage page.
- **Muse:** The shortcut opens Muse in another tab. It does not run Gideon chats.
- **Web search:** Works without a key. A Tavily key is optional.

The launcher creates `.openjarvis/config.toml` from `configs/gideon.local.toml` on first use. Local conversations, credentials, and logs stay under `.openjarvis/`, which Git ignores. Do not commit that folder.
