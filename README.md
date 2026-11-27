# Local Home Assistant (LangChain + Ollama)

A private, fully local home assistant. A LangChain agent (`create_agent`) drives an
open-source model served by Ollama and calls tools to control smart-home devices,
manage a shopping list and notes, and tell the time.

## Setup

```bash
# 1. Ollama
curl -fsSL https://ollama.com/install.sh | sh
ollama serve &                 # skip if systemd already started it
ollama pull qwen3:8b

# 2. Python deps
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 3. Run
python -m home_assistant -v
```

## Customizing the model

- **Pick any model**: edit `model.name` in `config.yaml`, pass `--model llama3.1:8b`,
  set `HA_MODEL=...`, or type `/model <name>` while chatting. The model must support
  tool calling (qwen3, llama3.1/3.2, mistral-nemo, granite3.3, ...).
- **Build your own**: edit `Modelfile` (base model, parameters, persona), then
  `ollama create home-assistant -f Modelfile` and set `model.name: home-assistant`.
- **Persona**: `assistant.name` / `assistant.system_prompt` in `config.yaml`.

## Channels

Run `python -m home_assistant <channel>`. Every channel shares the same agent and
slash commands (`/model`, `/models`, `/devices`, `/reset`, `/help`), and each
user/chat gets its own conversation history.

### Terminal — `cli` (default)

### Telegram — `telegram`

1. In Telegram, message **@BotFather**, send `/newbot`, and copy the token.
2. `export TELEGRAM_BOT_TOKEN=123456:ABC...`
3. `python -m home_assistant telegram`, then message your bot. It replies with your
   user id because nobody is allowed yet.
4. `export TELEGRAM_ALLOWED_USERS=<your id>` (comma-separate several) and restart.

It uses long polling, so no public URL or port forwarding is needed. Messages from
anyone not on the allowlist are rejected, so strangers can't control your home.

### Adding a channel

Create `home_assistant/channels/<name>.py` with a `Channel` subclass that implements
`run()`, receives messages, and calls `self.assistant.reply(text, conversation="<name>:<user>")`
(plus `self.handle_command(...)` for slash commands). Then register it in
`channels/__init__.py`.

## Real devices (Home Assistant)

Set `smart_home.backend: homeassistant`, your instance URL, and a long-lived access
token (Profile → Security in Home Assistant), or use `HA_BACKEND`, `HASS_URL`,
`HASS_TOKEN`. The default `simulated` backend uses demo devices.

## Layout

| File | Purpose |
|---|---|
| `home_assistant/agent.py` | ChatOllama + LangChain agent with conversation memory |
| `home_assistant/tools.py` | Tools the model can call (add new `@tool` functions here) |
| `home_assistant/devices.py` | Simulated and Home Assistant REST backends |
| `home_assistant/channels/` | Ways to talk to it: `cli.py`, `telegram.py`, shared commands in `base.py` |
| `home_assistant/__main__.py` | Entry point: picks the channel |
| `config.yaml`, `Modelfile` | Configuration and custom model definition |
