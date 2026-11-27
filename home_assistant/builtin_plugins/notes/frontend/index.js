import { PluginElement, esc } from '/static/sdk.js';

const when = (iso) => new Date(iso).toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });

class Notes extends PluginElement {
  async init() {
    this.innerHTML = `
      <form class="inline-form">
        <input type="text" placeholder="Write a note…" aria-label="New note">
        <button class="btn" type="submit">Save</button>
      </form>
      <ul class="list" style="margin-top: 8px"></ul>`;
    this.querySelector('form').addEventListener('submit', (e) => this.add(e));
    this.addEventListener('click', (e) => {
      const del = e.target.closest('[data-delete]');
      if (del) this.run(() => this.api.del(`/notes/${encodeURIComponent(del.dataset.delete)}`));
    });
    this.listen('changed', (e) => this.render(e.data.notes));
    this.render(await this.api.get('/notes'));
  }

  render(notes) {
    this.querySelector('.list').innerHTML = notes.length
      ? [...notes].reverse().map((n) => `<li>
          <div class="grow"><div>${esc(n.text)}</div><div class="muted small">${esc(when(n.created))}</div></div>
          <button class="btn-icon" data-delete="${esc(n.id)}" aria-label="Delete note">×</button></li>`).join('')
      : '<li class="empty">No notes yet.</li>';
  }

  add(e) {
    e.preventDefault();
    const input = this.querySelector('input');
    const text = input.value.trim();
    if (!text) return;
    input.value = '';
    this.run(() => this.api.post('/notes', { text }));
  }
}

customElements.define('plugin-notes', Notes);
