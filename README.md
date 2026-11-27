# Local Home Assistant (LangChain + Ollama)

A private, fully local home assistant built from plugins. A LangChain agent
(`create_agent`) drives an open-source model served by Ollama. Each plugin adds
tools the AI can call, a backend API, and a dashboard widget. You can talk to it
from a web dashboard, Telegram or the terminal.

## Setup

```bash
# 1. Ollama
curl -fsSL https://ollama.com/install.sh | sh
ollama serve &                 # skip if systemd already started it
ollama pull qwen3:8b

# 2. Python deps
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 3. Run the dashboard (and optionally Telegram) on one shared assistant
python -m home_assistant web telegram
# → http://localhost:8765
```

## Plugins

Everything the assistant can do comes from plugins. A plugin can provide any of:

| Part | What it does |
|---|---|
| **AI tools** | LangChain tools so the model can operate the plugin |
| **Backend** | A FastAPI router mounted at `/api/plugins/<id>/` |
| **Frontend** | A web component shown as a card on the dashboard |
| **Commands** | Slash commands for every chat channel (e.g. `/devices`) |
| **Prompt** | Notes appended to the AI's system prompt |

The plugin state is the same everywhere. If you say "turn off the kitchen light"
in Telegram, the dashboard switch flips live.

Built-ins: `smart_home`, `shopping_list`, `notes`, `clock`. Choose which load with
`plugins.enabled` in `config.yaml`, or with `HA_PLUGINS=clock,notes`.

**Writing your own:** see [PLUGINS.md](PLUGINS.md). Plugins can live in `./plugins/`,
be pip-installed packages, or ship with the app.

## Channels

Run `python -m home_assistant <channel> [<channel> ...]`. Channels started together
share one assistant: the same devices, plugins and live updates. Each user or chat
still gets its own conversation history.

| Channel | |
|---|---|
| `web` | Dashboard with every plugin's UI and a chat panel. Serves on `127.0.0.1:8765`, API docs at `/api/docs` |
| `telegram` | Telegram bot (see below) |
| `cli` | Terminal chat (default) |

Shared commands: `/model`, `/models`, `/plugins`, `/reset`, `/help`, plus every plugin's commands.

### Voice (wake word)

The dashboard's **Voice** card listens hands-free: say "Hey Jarvis", then your
request. The browser only captures the microphone and streams it to this app; the
wake word ([openWakeWord](https://github.com/dscripka/openWakeWord)) and speech-to-text
([faster-whisper](https://github.com/SYSTRAN/faster-whisper)) both run locally.
Replies show in the chat and are read aloud with the browser's voice (switchable off).

```bash
pip install -r requirements-voice.txt
python -m home_assistant web      # then click "Start listening" on the Voice card
```

- **Talk now** skips the wake word.
- The first start downloads the Whisper model (~145 MB for `base.en`).
- Settings live under `plugins.voice` in `config.yaml`: wake word, sensitivity, Whisper
  model size, and the pause that ends a command.
- **Custom wake words:** train one with openWakeWord and set `wake_word` to the `.onnx` path.
- Whisper uses the GPU when CUDA libraries are available, otherwise the CPU.
- Browsers only allow the microphone on `localhost` or HTTPS, so open the dashboard via
  `http://localhost:8765`.

### Telegram

1. In Telegram, message **@BotFather**, send `/newbot`, and copy the token.
2. `export TELEGRAM_BOT_TOKEN=123456:ABC...`
3. `python -m home_assistant telegram`, then message your bot. It replies with your
   user id because nobody is allowed yet.
4. `export TELEGRAM_ALLOWED_USERS=<your id>` (comma-separate several) and restart.

It uses long polling, so no public URL or port forwarding is needed. Messages from
anyone not on the allowlist are rejected, so strangers can't control your home.

### Web dashboard security

The dashboard has no login. It listens on localhost only by default. Set
`channels.web.host: 0.0.0.0` only on a network you trust.

### Adding a channel

Create `home_assistant/channels/<name>.py` with a `Channel` subclass that implements
`run()`, receives messages, and calls `self.assistant.reply(text, conversation="<name>:<user>")`
(plus `self.handle_command(...)` for slash commands). Then register it in
`channels/__init__.py`.

## Testing without Ollama

Add `--fake` (or set `HA_FAKE_LLM=1`) to swap the LLM for a keyword-matching stand-in
(`home_assistant/fake_llm.py`). Channels, plugins, devices and memory all run for real:

```bash
python -m home_assistant web telegram --fake
```

It understands simple commands such as "turn on the kitchen light", "set bedroom
brightness to 30", "add milk and eggs to the shopping list" and "what time is it".
Once Ollama is ready, send `/model qwen3:8b` to switch to the real model without restarting.

## Customizing the model

- **Pick any model**: edit `model.name` in `config.yaml`, pass `--model llama3.1:8b`,
  set `HA_MODEL=...`, or type `/model <name>` while chatting. The model must support
  tool calling (qwen3, llama3.1/3.2, mistral-nemo, granite3.3, ...).
- **Build your own**: edit `Modelfile` (base model, parameters, persona), then
  `ollama create home-assistant -f Modelfile` and set `model.name: home-assistant`.
- **Persona**: `assistant.name` / `assistant.system_prompt` in `config.yaml`.

## Real devices

The smart-home plugin talks to one backend: `simulated` (demo devices, the default),
`dirigera`, or `homeassistant`. All three work with the same AI tools, dashboard card and
commands (`/devices`, `/scene`).

### IKEA DIRIGERA

Supports lights (on/off, brightness), outlets, blinds, air purifiers, scenes, and
read-only sensors (VINDSTYRKA, door/window, leak, motion). Everything stays on your network.
Changes made in the IKEA Home app or with remotes show up on the dashboard live.

1. Find the hub's IP address in your router's list of connected devices. Giving the hub
   a fixed IP (DHCP reservation) means it won't change later.
2. Pair once. Run this, then press the action button on the bottom of the hub (there may
   be no visible reaction; the script waits up to 2 minutes):
   ```bash
   python -m home_assistant.builtin_plugins.smart_home.pair_dirigera 192.168.1.50
   ```
   It saves `DIRIGERA_HOST`, `DIRIGERA_TOKEN` and `HA_BACKEND=dirigera` to `.env` in the
   project folder (git-ignored, owner-only), which the app loads automatically. Use
   `--print` to show them instead. Keep the token out of `config.yaml`, since anyone with
   it controls your home.

Devices with the same name in different rooms are addressed as "kitchen ceiling light".
The integration uses the community [`dirigera`](https://github.com/Leggin/dirigera)
library. The hub uses a self-signed certificate, so its HTTPS certificate isn't verified.

### Home Assistant

Set `plugins.smart_home.backend: homeassistant`, your instance URL, and a long-lived
access token (Profile → Security in Home Assistant), or use `HA_BACKEND`, `HASS_URL`,
`HASS_TOKEN`.

## Layout

| Path | Purpose |
|---|---|
| `home_assistant/agent.py` | Assistant core: loads plugins, builds the LangChain agent |
| `home_assistant/plugins/` | Plugin API (`Plugin`, `PluginError`, `Command`) and loader |
| `home_assistant/builtin_plugins/` | Built-in plugins, each with tools, backend and `frontend/` |
| `home_assistant/channels/` | `web.py`, `telegram.py`, `cli.py`; shared commands in `base.py` |
| `home_assistant/web/` | Dashboard shell and `sdk.js` for plugin frontends |
| `home_assistant/events.py`, `storage.py` | Event bus and per-plugin JSON storage |
| `plugins/` | Your own plugins (auto-discovered) |
| `config.yaml`, `Modelfile` | Configuration and custom model definition |
