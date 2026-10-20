/* Live driver commerce uses sponsor-scoped APIs; local-file demos keep their own views. */
function installLiveDriverViews() {
  const heading = title => `<div class="head"><div><h1>${title}</h1><p class="sub">${esc(App.me.sponsor_name || "Select a sponsor to continue")}</p></div></div>`;
  const act = async (button, operation) => {
    button.disabled = true;
    try { await operation(); await App.render(); }
    catch (error) { toast(error.message); button.disabled = false; }
  };
  VIEWS.driver.catalog = async () => {
    const { products } = await App.api('/api/driver/catalog');
    return heading('Catalog') + `<div class="cards">${products.map(p => `<article class="item">${p.image_url
        ? `<img src="${esc(p.image_url)}" alt="" loading="lazy" referrerpolicy="no-referrer" style="aspect-ratio:4/3;width:100%;object-fit:contain;background:#fff">`
        : `<div class="ph">${esc(p.product_name)}</div>`}<div class="bd">
      <span class="nm">${esc(p.product_name)}</span><p>${esc(p.description)}</p><span class="pts">${n(p.point_price)} pts</span>
      <button class="btn go" data-live-add="${p.product_id}" ${p.availability !== 'AVAILABLE' || App.me.viewed_by ? 'disabled' : ''}>Add to cart</button>
      </div></article>`).join('') || '<p>No rewards available for this sponsor.</p>'}</div>`;
  };
  bind.driver.catalog = () => document.querySelectorAll('[data-live-add]').forEach(button => {
    button.onclick = () => act(button, async () => {
      const { items } = await App.api('/api/driver/cart');
      const id = +button.dataset.liveAdd, item = items.find(i => i.product_id === id);
      await App.api(`/api/driver/cart/items/${id}`, { method:'PUT', body:{quantity:(item?.quantity || 0) + 1} });
      toast('Added to cart');
    });
  });
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
    const { orders } = await App.api('/api/driver/orders');
    return heading('Orders') + orders.map(o => `<div class="panel"><h2>Order #${o.order_id}</h2>${badge(o.status)}
      <p>${fmtD(o.placed_at)} · ${n(o.total_points)} points</p>
      ${o.items.map(i => `<p>${esc(i.product_name)} · ${i.quantity} × ${n(i.unit_point_price)} points</p>`).join('')}
      ${o.status === 'PLACED' && !App.me.viewed_by ? `<button class="btn danger" data-live-cancel="${o.order_id}">Cancel order</button>` : ''}</div>`).join('') +
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
