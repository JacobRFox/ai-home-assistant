// Dashboard shell: loads each plugin's frontend module into a card, and runs the chat.
import { esc, on } from '/static/sdk.js';

const $ = (sel) => document.querySelector(sel);

async function getJSON(url, options) {
  const res = await fetch(url, options);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

// ---- header -----------------------------------------------------------------
async function loadStatus() {
  const status = await getJSON('/api/status');
  $('#assistant-name').textContent = status.name;
  $('#model').textContent = status.model;
  document.title = status.name;
}

on('connection.status', ({ data }) => {
  const el = $('#connection');
  el.classList.toggle('online', data.connected);
  el.querySelector('span').textContent = data.connected ? 'Live' : 'Reconnecting';
});
on('assistant.model_changed', ({ data }) => { $('#model').textContent = data.model; });

// ---- plugins ------------------------------------------------------------------
function pluginCard(plugin) {
  const card = document.createElement('article');
  card.className = 'card plugin-card';
  card.dataset.plugin = plugin.id;
  card.innerHTML = `
    <div class="card-head">
      <div>
        <h2>${esc(plugin.name)}</h2>
        ${plugin.description ? `<p class="muted small">${esc(plugin.description)}</p>` : ''}
      </div>
    </div>
    <div class="card-body"></div>
    <p class="card-status" role="status" hidden></p>`;

  let timer;
  card.addEventListener('plugin-notify', (e) => {
    const status = card.querySelector('.card-status');
    status.textContent = e.detail.message;
    status.classList.toggle('error', e.detail.isError);
    status.hidden = false;
    clearTimeout(timer);
    timer = setTimeout(() => { status.hidden = true; }, 5000);
  });
  return card;
}

async function loadPlugins() {
  const container = $('#plugins');
  const plugins = await getJSON('/api/plugins');
  const withUI = plugins.filter((p) => p.module);
  if (!withUI.length) {
    container.innerHTML = '<div class="card"><p class="empty">No plugins with a dashboard are loaded.</p></div>';
    return;
  }
  for (const plugin of withUI) {
    const card = pluginCard(plugin);
    container.append(card);
    const body = card.querySelector('.card-body');
    try {
      await import(plugin.module);
      if (!customElements.get(plugin.element)) throw new Error(`module did not define <${plugin.element}>`);
      const el = document.createElement(plugin.element);
      el.setAttribute('plugin-id', plugin.id);
      body.append(el);
    } catch (e) {
      console.error(`Plugin ${plugin.id} frontend failed`, e);
      body.innerHTML = `<p class="empty error">Couldn’t load this plugin’s interface: ${esc(e.message)}</p>`;
    }
  }
}

// ---- chat -------------------------------------------------------------------------
const log = $('#chat-log');

function addMessage(role, text, steps = []) {
  log.querySelector('.empty')?.remove();
  const msg = document.createElement('div');
  msg.className = `msg msg-${role}`;
  const toolSteps = steps.filter((s) => s.kind === 'tool');
  msg.innerHTML = `
    ${toolSteps.length ? `<div class="steps">${toolSteps.map((s) => `<code class="step">${esc(s.content)}</code>`).join('')}</div>` : ''}
    <div class="bubble"></div>`;
  msg.querySelector('.bubble').textContent = text;
  log.append(msg);
  log.scrollTop = log.scrollHeight;
  return msg;
}

// Plugins post into the chat via postToChat() in the SDK (e.g. voice transcripts and replies).
window.addEventListener('assistant-chat', (e) => {
  const { role, text, steps, pending } = e.detail;
  log.querySelector('.msg.pending.from-plugin')?.remove();
  const msg = addMessage(role, text, steps ?? []);
  if (pending) msg.classList.add('pending', 'from-plugin');
});

$('#chat-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const input = $('#chat-input');
  const text = input.value.trim();
  if (!text) return;
  input.value = '';
  addMessage('user', text);
  const pending = addMessage('assistant', 'Thinking…');
  pending.classList.add('pending');
  const button = e.target.querySelector('button');
  button.disabled = true;
  try {
    const res = await getJSON('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text }),
    });
    pending.remove();
    addMessage('assistant', res.reply, res.steps);
  } catch (err) {
    pending.remove();
    addMessage('error', `Request failed: ${err.message}`);
  } finally {
    button.disabled = false;
    input.focus();
  }
});

$('#chat-reset').addEventListener('click', async () => {
  await fetch('/api/chat/reset', { method: 'POST' });
  log.innerHTML = '<p class="empty">New conversation started.</p>';
});

loadStatus().catch(console.error);
loadPlugins().catch((e) => { $('#plugins').innerHTML = `<div class="card"><p class="empty error">${esc(e.message)}</p></div>`; });
