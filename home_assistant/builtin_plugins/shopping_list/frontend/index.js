import { PluginElement, esc } from '/static/sdk.js';

class ShoppingList extends PluginElement {
  async init() {
    this.innerHTML = `
      <form class="inline-form">
        <input type="text" placeholder="Add items (comma-separated)" aria-label="New items">
        <button class="btn" type="submit">Add</button>
      </form>
      <ul class="list" style="margin-top: 8px"></ul>
      <div class="row" style="justify-content: flex-end; margin-top: 8px">
        <button class="btn btn-ghost" data-action="clear" hidden>Clear list</button>
      </div>`;
    this.querySelector('form').addEventListener('submit', (e) => this.add(e));
    this.addEventListener('click', (e) => this.onClick(e));
    this.listen('changed', (e) => this.render(e.data.items));
    this.render(await this.api.get('/items'));
  }

  render(items) {
    this.querySelector('.list').innerHTML = items.length
      ? items.map((i) => `<li><span class="grow">${esc(i)}</span>
          <button class="btn-icon" data-remove="${esc(i)}" aria-label="Remove ${esc(i)}">×</button></li>`).join('')
      : '<li class="empty">The list is empty.</li>';
    this.querySelector('[data-action="clear"]').hidden = !items.length;
  }

  add(e) {
    e.preventDefault();
    const input = this.querySelector('input');
    const items = input.value.split(',').map((s) => s.trim()).filter(Boolean);
    if (!items.length) return;
    input.value = '';
    this.run(() => this.api.post('/items', { items }));
  }

  onClick(e) {
    const remove = e.target.closest('[data-remove]');
    if (remove) this.run(() => this.api.del(`/items/${encodeURIComponent(remove.dataset.remove)}`));
    if (e.target.closest('[data-action="clear"]')) this.run(() => this.api.del('/items'));
  }
}

customElements.define('plugin-shopping-list', ShoppingList);
