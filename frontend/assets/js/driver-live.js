/* Live driver commerce uses sponsor-scoped APIs; local-file demos keep their own views. */
function installLiveDriverViews() {
  const heading = title => `<div class="head"><div><h1>${title}</h1><p class="sub">${esc(App.me.sponsor_name || "Select a sponsor to continue")}</p></div></div>`;
  const act = async (button, operation) => {
    button.disabled = true;
    try { await operation(); await App.render(); }
    catch (error) { toast(error.message); button.disabled = false; }
  };
  // Catalog: cards show name, points and Add to cart; clicking a card opens its details.
  // Search and filters run in the browser and survive the re-render after adding to cart.
  let catalog, filter = { q:'', cat:'', afford:false, sort:'name' };
  const image = p => p.image_url
    ? `<img src="${esc(p.image_url)}" alt="" loading="lazy" referrerpolicy="no-referrer" class="item-img">`
    : `<div class="ph">${esc(p.product_name)}</div>`;
  const addButton = p => {
    const out = p.availability !== 'AVAILABLE';
    return `<button type="button" class="btn ${out || p.point_price > catalog.current_points ? 'ghost' : 'go'}" data-live-add="${p.product_id}"
      ${out || App.me.viewed_by ? 'disabled' : ''}>${out ? 'Unavailable' : 'Add to cart'}</button>`;
  };
  const shown = () => {
    const q = filter.q.trim().toLowerCase();
    const list = catalog.products.filter(p =>
      (!q || [p.product_name, p.description, p.category].some(s => (s || '').toLowerCase().includes(q))) &&
      (!filter.cat || p.category === filter.cat) &&
      (!filter.afford || p.point_price <= catalog.current_points));
    const by = { name:(a, b) => a.product_name.localeCompare(b.product_name),
      low:(a, b) => a.point_price - b.point_price, high:(a, b) => b.point_price - a.point_price };
    return list.sort(by[filter.sort]);
  };
  const cards = () => shown().map(p => `<article class="item">
      <button type="button" class="item-open" data-live-open="${p.product_id}" aria-label="View details for ${esc(p.product_name)}">${image(p)}</button>
      <div class="bd"><button type="button" class="item-open nm" data-live-open="${p.product_id}">${esc(p.product_name)}</button>
      <span class="pts">${n(p.point_price)} pts</span>${addButton(p)}</div></article>`).join('')
    || `<p class="empty">${catalog.products.length ? 'No rewards match your search.' : 'No rewards available for this sponsor.'}</p>`;
  const addToCart = async id => {
    const { items } = await App.api('/api/driver/cart');
    const item = items.find(i => i.product_id === id);
    await App.api(`/api/driver/cart/items/${id}`, { method:'PUT', body:{quantity:(item?.quantity || 0) + 1} });
    toast('Added to cart');
  };
  const details = id => {
    const p = catalog.products.find(x => x.product_id === id), form = $('#dlgBody'), dlg = $('#dlg');
    form.innerHTML = `${image(p)}${p.category ? `<span class="dim">${esc(p.category)}</span>` : ''}
      <h2 style="margin:0">${esc(p.product_name)}</h2>
      <p class="item-desc">${esc(p.description || 'No description provided.')}</p>
      <span class="pts" style="font-size:22px;font-weight:900">${n(p.point_price)} pts</span>
      ${p.point_price > catalog.current_points ? `<p class="dim" style="margin:0">You need ${n(p.point_price - catalog.current_points)} more points for this reward.</p>` : ''}
      <div class="row" style="justify-content:flex-end"><button class="btn ghost" value="cancel">Close</button>${addButton(p)}</div>`;
    form.querySelector('[data-live-add]').onclick = e => act(e.currentTarget, async () => { await addToCart(id); dlg.close(); });
    dlg.onclose = null;
    dlg.showModal();
  };
  const bindCards = () => {
    document.querySelectorAll('#cards [data-live-add]').forEach(button => {
      button.onclick = () => act(button, () => addToCart(+button.dataset.liveAdd));
    });
    document.querySelectorAll('#cards [data-live-open]').forEach(el => { el.onclick = () => details(+el.dataset.liveOpen); });
  };
  VIEWS.driver.catalog = async () => {
    catalog = await App.api('/api/driver/catalog');
    const cats = [...new Set(catalog.products.map(p => p.category).filter(Boolean))].sort();
    if (!cats.includes(filter.cat)) filter.cat = '';
    return `<div class="head"><div><h1>Catalog</h1><p class="sub">${esc(App.me.sponsor_name || 'Select a sponsor to continue')}
        · You have ${n(catalog.current_points)} points to spend.</p></div></div>
      <div class="row" style="margin-bottom:16px">
        <input type="search" id="catQ" placeholder="Search rewards" aria-label="Search rewards" value="${esc(filter.q)}" style="flex:1 1 220px">
        ${cats.length ? `<select id="catCat" aria-label="Category"><option value="">All categories</option>
          ${cats.map(c => `<option ${c === filter.cat ? 'selected' : ''}>${esc(c)}</option>`).join('')}</select>` : ''}
        <select id="catSort" aria-label="Sort">${[['name', 'Name A–Z'], ['low', 'Points: low to high'], ['high', 'Points: high to low']]
          .map(([v, t]) => `<option value="${v}" ${v === filter.sort ? 'selected' : ''}>${t}</option>`).join('')}</select>
        <label class="row" style="gap:6px"><input type="checkbox" id="catAfford" ${filter.afford ? 'checked' : ''}> Only what I can afford</label>
      </div>
      <div class="cards" id="cards">${cards()}</div>`;
  };
  bind.driver.catalog = () => {
    const redraw = () => { $('#cards').innerHTML = cards(); bindCards(); };
    $('#catQ').oninput = e => { filter.q = e.target.value; redraw(); };
    if ($('#catCat')) $('#catCat').onchange = e => { filter.cat = e.target.value; redraw(); };
    $('#catSort').onchange = e => { filter.sort = e.target.value; redraw(); };
    $('#catAfford').onchange = e => { filter.afford = e.target.checked; redraw(); };
    bindCards();
  };
  let cart;
  VIEWS.driver.cart = async () => {
    cart = await App.api('/api/driver/cart');
    const total = cart.items.reduce((sum, i) => sum + i.quantity * i.point_price_snapshot, 0);
    return heading('Cart') + `<div class="panel"><p>Catalog availability and prices are checked again at checkout.</p>
      ${cart.items.map(i => `<div class="row spread"><span>${esc(i.product_name)} · ${i.quantity} × ${n(i.point_price_snapshot)} pts</span>
        <button class="btn ghost" data-live-remove="${i.product_id}" ${App.me.viewed_by ? 'disabled' : ''}>Remove</button></div>`).join('') || '<p>Your cart is empty.</p>'}
      <p>Total: <b>${n(total)} points</b></p><button class="btn go" id="live-checkout" ${!cart.items.length || App.me.viewed_by ? 'disabled' : ''}>Place order</button></div>`;
  };
  bind.driver.cart = () => {
    document.querySelectorAll('[data-live-remove]').forEach(button => {
      button.onclick = () => act(button, () => App.api(`/api/driver/cart/items/${button.dataset.liveRemove}`, {method:'PUT', body:{quantity:0}}));
    });
    $('#live-checkout').onclick = e => act(e.currentTarget, async () => {
      const result = await App.api('/api/driver/checkout', {method:'POST', body:{cart_id:cart.cart_id}});
      toast(`Order #${result.order_id} placed`);
    });
  };
  VIEWS.driver.orders = async () => {
    const { orders, cancel_window_days: days } = await App.api('/api/driver/orders');
    return heading('Orders') + `<p class="dim">You can cancel an order within ${days} days of placing it, until it ships. Points go back to your balance.</p>` +
      orders.map(o => `<div class="panel"><h2>Order #${o.order_id}</h2>${badge(o.status)}
      <p>${fmtD(o.placed_at)} · ${n(o.total_points)} points</p>
      ${o.items.map(i => `<p>${esc(i.product_name)} · ${i.quantity} × ${n(i.unit_point_price)} points</p>`).join('')}
      ${o.can_cancel && !App.me.viewed_by ? `<button class="btn danger" data-live-cancel="${o.order_id}">Cancel order</button>
        <span class="dim">Cancel by ${fmtDT(o.cancel_until)}</span>` : ''}</div>`).join('') +
      (orders.length ? '' : '<div class="panel">No orders with this sponsor.</div>');
  };
  bind.driver.orders = () => document.querySelectorAll('[data-live-cancel]').forEach(button => {
    button.onclick = () => act(button, async () => {
      await App.api(`/api/driver/orders/${button.dataset.liveCancel}/cancel`, {method:'POST'});
      toast('Order cancelled; points refunded to the original sponsor.');
    });
  });
  VIEWS.driver.points = async () => {
    const { transactions } = await App.api('/api/driver/points');
    return heading('Point history') + `<div class="panel">${transactions.map(t => `<div class="li"><div>${esc(t.reason)}
      <br><span class="dim">${fmtD(t.created_at)} · Balance: ${n(t.balance_after)}</span></div><b>${n(t.points_delta)} pts</b></div>`).join('') || 'No point transactions with this sponsor.'}</div>`;
  };
  bind.driver.points = () => {};
}
