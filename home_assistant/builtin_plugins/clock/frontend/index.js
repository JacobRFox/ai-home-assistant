import { PluginElement } from '/static/sdk.js';

// Frontend-only widget: no backend calls needed.
class Clock extends PluginElement {
  init() {
    this.innerHTML = `<div style="font-size: 32px; font-weight: 650; font-variant-numeric: tabular-nums" data-time></div>
      <div class="muted" data-date></div>`;
    this.tick();
    this.timer = setInterval(() => this.tick(), 1000);
  }

  tick() {
    const now = new Date();
    this.querySelector('[data-time]').textContent = now.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
    this.querySelector('[data-date]').textContent = now.toLocaleDateString([], { weekday: 'long', month: 'long', day: 'numeric' });
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    clearInterval(this.timer);
  }
}

customElements.define('plugin-clock', Clock);
