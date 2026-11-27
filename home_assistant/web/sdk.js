// Plugin frontend SDK. Import from plugin modules:
//   import { PluginElement, esc } from '/static/sdk.js';
//
// A plugin frontend is an ES module that defines the custom element named in
// /api/plugins (plugin-<id>), usually by extending PluginElement.

/** Escape text for safe insertion into innerHTML. */
export function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
}

async function request(method, url, body) {
  const res = await fetch(url, {
    method,
    headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = res.headers.get('content-type')?.includes('json') ? await res.json() : await res.text();
  if (!res.ok) throw new Error(typeof data === 'object' && data?.detail ? (typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)) : `${res.status} ${res.statusText}`);
  return data;
}

/** HTTP client for a plugin's backend router (mounted at /api/plugins/<id>). */
export function api(pluginId) {
  const base = `/api/plugins/${encodeURIComponent(pluginId)}`;
  return {
    get: (path) => request('GET', base + path),
    post: (path, body = {}) => request('POST', base + path, body),
    put: (path, body = {}) => request('PUT', base + path, body),
    del: (path) => request('DELETE', base + path),
  };
}

// ---- live events --------------------------------------------------------
const listeners = new Map(); // type or "prefix.*" -> Set<callback>
let socket = null;
let connected = false;

function dispatch(event) {
  for (const [pattern, callbacks] of listeners) {
    const match = pattern === '*' || pattern === event.type ||
      (pattern.endsWith('.*') && event.type.startsWith(pattern.slice(0, -1)));
    if (match) callbacks.forEach((cb) => { try { cb(event); } catch (e) { console.error(e); } });
  }
}

function connect(delay = 500) {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  socket = new WebSocket(`${proto}://${location.host}/api/events`);
  socket.onopen = () => { connected = true; delay = 500; dispatch({ type: 'connection.status', data: { connected } }); };
  socket.onmessage = (msg) => dispatch(JSON.parse(msg.data));
  socket.onclose = () => {
    if (connected) dispatch({ type: 'connection.status', data: { connected: (connected = false) } });
    setTimeout(() => connect(Math.min(delay * 2, 10000)), delay);
  };
}

/**
 * Subscribe to server events, e.g. on('smart_home.changed', cb) or on('notes.*', cb).
 * Returns an unsubscribe function.
 */
export function on(type, callback) {
  if (!socket) connect();
  if (!listeners.has(type)) listeners.set(type, new Set());
  listeners.get(type).add(callback);
  return () => listeners.get(type)?.delete(callback);
}

export const isConnected = () => connected;

/**
 * Base class for plugin UIs. Override `init()` (may be async). Inside you get:
 *   this.pluginId                 the plugin's id
 *   this.api.get/post/put/del     calls to the plugin's backend
 *   this.listen(name, cb)         subscribe to "<pluginId>.<name>" (auto-cleaned up)
 *   this.notify(message, isError) show a status message in the card
 */
export class PluginElement extends HTMLElement {
  get pluginId() { return this.getAttribute('plugin-id'); }

  connectedCallback() {
    this.api = api(this.pluginId);
    this._unsubscribe = [];
    Promise.resolve(this.init?.()).catch((e) => this.notify(e.message, true));
  }

  disconnectedCallback() {
    this._unsubscribe.forEach((u) => u());
  }

  listen(name, callback) {
    this._unsubscribe.push(on(`${this.pluginId}.${name}`, callback));
  }

  notify(message, isError = false) {
    this.dispatchEvent(new CustomEvent('plugin-notify', { bubbles: true, detail: { message, isError } }));
  }

  /** Run an async action, reporting failures in the card instead of throwing. */
  async run(action) {
    try { return await action(); } catch (e) { this.notify(e.message, true); }
  }
}
