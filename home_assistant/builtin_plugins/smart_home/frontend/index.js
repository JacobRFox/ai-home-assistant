import { PluginElement, esc } from '/static/sdk.js';

const ICONS = { light: '💡', switch: '🔌', lock: '🔒', climate: '🌡️', fan: '🌀', cover: '🪟', sensor: '📟' };
const READING_FORMAT = {
  temperature: (v) => `${v}°`, humidity: (v) => `${v}% RH`, pm2_5: (v) => `PM2.5 ${v}`, voc_index: (v) => `VOC ${v}`,
  battery: (v) => `🔋 ${v}%`, open: (v) => (v ? 'Open' : 'Closed'), leak: (v) => (v ? '⚠️ Leak!' : 'Dry'),
  motion: (v) => (v ? 'Motion' : 'No motion'), illuminance: (v) => `${v} lx`,
};

class SmartHome extends PluginElement {
  async init() {
    this.innerHTML = '<div class="row" data-scenes style="flex-wrap: wrap; gap: 6px; margin-bottom: 8px"></div><ul class="list" data-devices></ul>';
    // Re-render whenever devices change: from here, the AI, or the hub itself.
    this.listen('changed', (e) => this.render(e.data.devices));
    this.addEventListener('change', (e) => this.onChange(e));
    this.addEventListener('click', (e) => this.onClick(e));
    const [devices, scenes] = await Promise.all([this.api.get('/devices'), this.api.get('/scenes')]);
    this.renderScenes(scenes);
    this.render(devices);
  }

  renderScenes(scenes) {
    this.querySelector('[data-scenes]').innerHTML = scenes
      .map((s) => `<button class="btn btn-ghost" data-scene="${esc(s.id)}">▶ ${esc(s.name)}</button>`).join('');
  }

  render(devices) {
    const list = this.querySelector('[data-devices]');
    list.innerHTML = devices.length ? devices.map((d) => this.row(d)).join('') : '<li class="empty">No devices found.</li>';
  }

  row(d) {
    const id = esc(d.id);
    const offline = d.reachable === false;
    const where = d.room ? `${esc(d.room)} · ` : '';
    let control = '', detail = '', extra = '';

    if (offline) {
      detail = 'Offline';
    } else if (d.type === 'sensor') {
      detail = Object.entries(d.readings ?? {}).map(([k, v]) => esc((READING_FORMAT[k] ?? ((x) => `${k} ${x}`))(v))).join(' · ') || 'No readings';
    } else if (d.type === 'lock') {
      detail = d.on ? 'Locked' : 'Unlocked';
      control = `<button class="btn btn-ghost" data-action="power" data-on="${!d.on}" data-id="${id}">${d.on ? 'Unlock' : 'Lock'}</button>`;
    } else if (d.type === 'climate') {
      const t = d.target_temp ?? 20;
      detail = `Target ${t}°`;
      control = `<div class="row">
        <button class="btn btn-ghost" data-action="temp" data-value="${t - 0.5}" data-id="${id}" aria-label="Lower">−</button>
        <strong>${esc(t)}°</strong>
        <button class="btn btn-ghost" data-action="temp" data-value="${t + 0.5}" data-id="${id}" aria-label="Raise">+</button>
      </div>`;
    } else if (d.type === 'cover') {
      const pos = d.position ?? (d.on ? 100 : 0);
      detail = pos >= 100 ? 'Open' : pos <= 0 ? 'Closed' : `${pos}% open`;
      control = `<div class="row" style="gap: 4px">
        <button class="btn btn-ghost" data-action="position" data-value="100" data-id="${id}">Open</button>
        <button class="btn btn-ghost" data-action="position" data-value="0" data-id="${id}">Close</button></div>`;
      extra = `<input type="range" min="0" max="100" step="5" value="${pos}" data-action="position" data-id="${id}" aria-label="${esc(d.name)} position">`;
    } else {
      detail = d.on ? 'On' : 'Off';
      if (d.type === 'light' && d.on && d.brightness != null) detail += ` · ${d.brightness}%`;
      if (d.type === 'fan' && d.fan_mode) detail = d.fan_mode[0].toUpperCase() + d.fan_mode.slice(1);
      if (d.power_w != null) detail += ` · ${d.power_w} W`;
      control = `<label class="switch" title="${d.on ? 'Turn off' : 'Turn on'}">
        <input type="checkbox" data-action="power" data-id="${id}" ${d.on ? 'checked' : ''} aria-label="${esc(d.name)}"><span></span></label>`;
      if (d.type === 'light' && d.brightness != null) {
        extra = `<input type="range" min="0" max="100" step="5" value="${d.on ? d.brightness : 0}" data-action="brightness" data-id="${id}" aria-label="${esc(d.name)} brightness">`;
      }
    }

    return `<li class="stack" style="align-items: stretch; gap: 6px; ${offline ? 'opacity: 0.55' : ''}">
      <div class="row">
        <span aria-hidden="true">${ICONS[d.type] ?? '•'}</span>
        <div class="grow"><div>${esc(d.name)}</div><div class="muted small">${where}${detail}</div></div>
        ${offline ? '' : control}
      </div>${offline ? '' : extra}
    </li>`;
  }

  onChange(e) {
    const el = e.target, id = encodeURIComponent(el.dataset.id ?? '');
    const action = el.dataset.action;
    if (action === 'power') this.run(() => this.api.post(`/devices/${id}/power`, { on: el.checked }));
    if (action === 'brightness') this.run(() => this.api.post(`/devices/${id}/brightness`, { percent: Number(el.value) }));
    if (action === 'position' && el.type === 'range') this.run(() => this.api.post(`/devices/${id}/position`, { percent: Number(el.value) }));
  }

  onClick(e) {
    const scene = e.target.closest('[data-scene]');
    if (scene) {
      this.run(async () => this.notify((await this.api.post(`/scenes/${encodeURIComponent(scene.dataset.scene)}/trigger`)).message));
      return;
    }
    const el = e.target.closest('button[data-action]');
    if (!el) return;
    const id = encodeURIComponent(el.dataset.id);
    const action = el.dataset.action;
    if (action === 'power') this.run(() => this.api.post(`/devices/${id}/power`, { on: el.dataset.on === 'true' }));
    if (action === 'temp') this.run(() => this.api.post(`/devices/${id}/temperature`, { temperature: Number(el.dataset.value) }));
    if (action === 'position') this.run(() => this.api.post(`/devices/${id}/position`, { percent: Number(el.dataset.value) }));
  }
}

customElements.define('plugin-smart-home', SmartHome);
