# Writing a plugin

A plugin is a Python package that exposes `plugin = <Plugin subclass>`. Every
part is optional, so start with one tool and add a backend and frontend when you
need them.

```
plugins/
  timers/
    __init__.py        # the Plugin subclass
    frontend/
      index.js         # optional dashboard card (defines <plugin-timers>)
```

## Where plugins come from

1. **Your folder:** any package in `./plugins/` (or the folders in `plugins.paths`).
2. **pip packages:** declare an entry point in your package's `pyproject.toml`:
   ```toml
   [project.entry-points."home_assistant.plugins"]
   timers = "my_package.timers:TimersPlugin"
   ```
3. **Built-ins:** `home_assistant/builtin_plugins/`.

A plugin with the same `id` from a later source replaces an earlier one, so you
can override a built-in. Enable and order plugins with `plugins.enabled` in
`config.yaml`. If a plugin fails to start, it's logged and skipped; the rest
keep working.

## The backend (`__init__.py`)

```python
from fastapi import APIRouter, HTTPException
from langchain_core.tools import tool
from pydantic import BaseModel

from home_assistant.plugins import Command, Plugin, PluginError


class NewTimer(BaseModel):
    label: str
    minutes: float


class TimersPlugin(Plugin):
    id = "timers"                 # unique snake_case id
    name = "Timers"
    description = "Kitchen timers."

    def setup(self):
        # self.ctx.config  -> this plugin's section of config.yaml (plugins.timers)
        # self.ctx.store   -> persistent JSON storage, private to the plugin
        # self.ctx.emit()  -> publish "timers.<name>" events to the dashboard
        # self.ctx.log     -> a logger
        # self.ctx.assistant.chat(text, conversation) -> talk to the AI (for input plugins like voice)
        self.default_minutes = self.ctx.config.get("default_minutes", 5)

    # 1. Shared logic. Tools, routes and commands all call these methods,
    #    so every interface behaves the same way.
    def timers(self) -> list[dict]:
        return self.ctx.store.get("timers", [])

    def add(self, label: str, minutes: float) -> dict:
        if minutes <= 0:
            raise PluginError("Timers need a positive duration.")  # shown to the AI / API / chat
        timer = {"label": label, "minutes": minutes}
        timers = self.timers() + [timer]
        self.ctx.store.set("timers", timers)
        self.ctx.emit("changed", {"timers": timers})               # the dashboard updates live
        return timer

    # 2. AI tools. Docstrings and type hints tell the model how to call them.
    def tools(self):
        @tool
        def start_timer(label: str, minutes: float) -> str:
            """Start a timer, e.g. label='pasta', minutes=9."""
            self.add(label, minutes)
            return f"Timer '{label}' set for {minutes:g} minutes."

        return [start_timer]

    # 3. Extra guidance appended to the system prompt.
    def prompt(self):
        return "Use start_timer whenever the user asks for a timer or reminder in N minutes."

    # 4. Backend API, mounted at /api/plugins/timers/
    def router(self):
        r = APIRouter()

        @r.get("/timers")
        def list_timers():
            return self.timers()

        @r.post("/timers")
        def create(body: NewTimer):
            try:
                return self.add(body.label, body.minutes)
            except PluginError as e:
                raise HTTPException(400, str(e))

        return r

    # 5. Slash commands for Telegram / CLI / web chat.
    def commands(self):
        return {"timers": Command("list timers", lambda arg: "\n".join(t["label"] for t in self.timers()) or "No timers.")}

    def shutdown(self):
        pass  # stop threads, close connections, ...


plugin = TimersPlugin
```

Rules of thumb:

- **Raise `PluginError` for expected problems** (bad input, device not found).
  The AI sees the message and can recover or ask a question. Any other exception
  is logged, and the AI only sees a generic failure.
- **Tool names must be unique across plugins.** Prefix them if they're generic.
- **Tools run in a worker thread.** Keep them synchronous and quick-ish, and use
  locks if you share mutable state with background threads.
- **Configure through `self.ctx.config`**, and add a `plugins.<id>:` section to
  `config.yaml`.

## The frontend (`frontend/index.js`)

The dashboard imports `/plugins/<id>/index.js` and renders the custom element
`<plugin-<id with dashes>>` inside a card. It's a plain ES module, with no build
step. Extend `PluginElement` from the SDK:

```js
import { PluginElement, esc } from '/static/sdk.js';

class Timers extends PluginElement {
  async init() {
    this.listen('changed', (e) => this.render(e.data.timers));   // live updates
    this.render(await this.api.get('/timers'));                  // GET /api/plugins/timers/timers
  }

  render(timers) {
    this.innerHTML = timers.length
      ? `<ul class="list">${timers.map((t) => `<li><span class="grow">${esc(t.label)}</span>${esc(t.minutes)} min</li>`).join('')}</ul>`
      : '<p class="empty">No timers.</p>';
  }
}

customElements.define('plugin-timers', Timers);
```

What `PluginElement` gives you:

| | |
|---|---|
| `this.api.get/post/put/del(path, body)` | Calls your router; throws `Error(detail)` on failure |
| `this.listen(name, cb)` | Subscribes to `<id>.<name>` events; cleaned up automatically |
| `this.run(asyncFn)` | Runs an action and shows any error in the card |
| `this.notify(message, isError)` | Shows a status line in the card |
| `postToChat(role, text, {steps, pending})` | Shows a message in the dashboard chat (import from the SDK) |
| `esc(text)` | Escapes text before you put it in `innerHTML`; always use it for data |

Shared CSS classes from the dashboard: `list`, `row`, `grow`, `stack`, `muted`,
`small`, `empty`, `btn`, `btn-ghost`, `btn-icon`, `inline-form`, and `switch`
(`<label class="switch"><input type="checkbox"><span></span></label>`). The
components follow the dashboard's light and dark themes.
