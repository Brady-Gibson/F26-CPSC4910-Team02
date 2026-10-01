/* TigerTruck front end: shared code for every page.
   Each page file sets VIEWS.<role>.<page> (and optionally bind.<role>.<page>), then calls App.start(role, page).
   A view can be async: `VIEWS.driver.x = async () => { const data = await App.api("/api/driver/x"); ... }`

   Two modes, picked automatically on load:
   - LIVE (served by Flask and /api/health answers): real login via /api/login, pages call App.api(...).
     Pages not converted yet read DB, which /api/bootstrap fills from MySQL (dev only).
   - Sample (opened as a local file only): DB comes from window.MOCK, login is simulated, edits stay in this tab.
   - Offline (served, but Flask/DB unreachable): pages show an error. Never falls back to sample data. */

const ROOT = document.body.dataset.root || "";
let DB = {};
let DATA_SOURCE = "sample data";
let LIVE = false;
let OFFLINE = false;
const FILE_MODE = location.protocol === "file:";
let role = null;
const ME = {};
const VIEWS = { driver:{}, sponsor:{}, admin:{} };
const bind = { driver:{}, sponsor:{}, admin:{} };
const HOME = { driver:"driver/dashboard", sponsor:"sponsor/drivers", admin:"admin/users" };
const ROUTES = {"driver": [["dashboard", "Dashboard"], ["catalog", "Catalog"], ["cart", "Cart"], ["orders", "Orders"], ["points", "Point history"], ["sponsor", "My sponsor"], ["notifications", "Notifications"], ["profile", "Profile"]], "sponsor": [["drivers", "Drivers"], ["applications", "Applications"], ["schedules", "Recurring points"], ["catalog", "Catalog"], ["orders", "Orders"], ["reports", "Reports"], ["organization", "Organization"]], "admin": [["users", "Users"], ["sponsors", "Sponsors"], ["audit", "Audit log"], ["reports", "Sales reports"], ["about", "About"]]};

const store = {
  get(k){ try { return JSON.parse(sessionStorage.getItem(k)); } catch { return null; } },
  set(k,v){ try { sessionStorage.setItem(k, JSON.stringify(v)); } catch {} },
  del(k){ try { sessionStorage.removeItem(k); } catch {} },
};
const pref = {
  get(k){ try { return localStorage.getItem(k); } catch { return null; } },
  set(k,v){ try { localStorage.setItem(k,v); } catch {} },
};
function fromCols(raw){ const db={}; for (const [t,{cols,rows}] of Object.entries(raw)) db[t]=rows.map(r=>Object.fromEntries(cols.map((c,i)=>[c,r[i]]))); return db; }
function saveDB(){ if (!LIVE) store.set("tt_db", { source: DATA_SOURCE, db: DB }); }

const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const n = x => Number(x).toLocaleString("en-US");
const usd = x => "$" + Number(x).toLocaleString("en-US",{minimumFractionDigits:2,maximumFractionDigits:2});
const now = () => { const d=new Date(); return d.toISOString().slice(0,16).replace("T"," "); };
const fmtD = s => s ? new Date(s.replace(" ","T")).toLocaleDateString("en-US",{month:"short",day:"numeric"}) : "—";
const fmtDT = s => s ? new Date(s.replace(" ","T")).toLocaleString("en-US",{month:"short",day:"numeric",hour:"numeric",minute:"2-digit"}) : "—";
const nextId = (t,k) => Math.max(0,...DB[t].map(r=>r[k]))+1;
const user = id => DB.user_account.find(u=>u.user_id===id);
const uname = id => { const u=user(id); return u ? `${u.first_name} ${u.last_name}` : "System"; };
const sponsor = id => DB.sponsor_organization.find(s=>s.sponsor_id===id);
const product = id => DB.product.find(p=>p.product_id===id);
const driver = id => DB.driver.find(d=>d.driver_id===id);
const badge = s => `<span class="badge b-${esc(s)}">${esc(String(s).replace(/_/g," ").toLowerCase())}</span>`;
const src = (...t) => `<div class="src">Reads/writes: ${t.map(x=>`<code>${x.toUpperCase()}</code>`).join(" ")}</div>`;
const roleOf = id => DB.admin.some(a=>a.admin_id===id) ? "Admin" : DB.sponsor_user.some(s=>s.sponsor_user_id===id) ? "Sponsor user" : "Driver";
function toast(m){ const t=$("#toast"); t.textContent=m; t.classList.add("on"); clearTimeout(t._h); t._h=setTimeout(()=>t.classList.remove("on"),2400); }

function addPoints(did, sid, delta, reason, by){
  const d = driver(did); const bal = d.current_points + delta;
  if (bal < 0) { toast("That would drop the balance below zero."); return false; }
  d.current_points = bal;
  const id = nextId("point_transaction","point_transaction_id"), t = now();
  DB.point_transaction.push({point_transaction_id:id,driver_id:did,sponsor_id:sid,performed_by_user_id:by,points_delta:delta,balance_after:bal,reason,created_at:t});
  const pref = DB.alert_preference.find(p=>p.user_id===did);
  if (!pref || pref.point_change_enabled)
    DB.notification.push({notification_id:nextId("notification","notification_id"),user_id:did,notification_type:"POINT_CHANGE",message:`${n(Math.abs(delta))} points were ${delta>0?"added":"deducted"}: ${reason}. New balance: ${n(bal)}.`,is_read:false,created_at:t});
  DB.audit_event.push({audit_event_id:nextId("audit_event","audit_event_id"),actor_user_id:by,sponsor_id:sid,driver_id:did,category:"POINT_CHANGE",subject_username:user(did).username,entity_type:"POINT_TRANSACTION",entity_id:id,success:true,reason_or_details:reason,created_at:t});
  return true;
}


const mySponsor = () => DB.sponsor_user.find(s=>s.sponsor_user_id===ME.sponsor).sponsor_id;
const roleKey = id => DB.admin.some(a=>a.admin_id===id) ? "admin" : DB.sponsor_user.some(s=>s.sponsor_user_id===id) ? "sponsor" : DB.driver.some(d=>d.driver_id===id) ? "driver" : null;
const counts = {
  driver:{ notifications:()=>DB.notification.filter(x=>x.user_id===ME.driver&&!x.is_read).length, cart:()=>cartItems().reduce((a,c)=>a+c.quantity,0) },
  sponsor:{ applications:()=>DB.driver_application.filter(a=>a.sponsor_id===mySponsor()&&a.status==="PENDING").length },
  admin:{},
};

function myDriver(){ return driver(ME.driver); }
function activeCart(create){
  const d = myDriver();
  let c = DB.shopping_cart.find(c=>c.driver_id===d.driver_id&&c.sponsor_id===d.sponsor_id&&c.status==="ACTIVE");
  if (!c && create){ c={cart_id:nextId("shopping_cart","cart_id"),driver_id:d.driver_id,sponsor_id:d.sponsor_id,status:"ACTIVE",created_at:now(),updated_at:now()}; DB.shopping_cart.push(c); }
  return c;
}
function cartItems(){ const c=activeCart(false); return c ? DB.cart_item.filter(i=>i.cart_id===c.cart_id) : []; }
function signHTML(d){
  const s = d.sponsor_id && sponsor(d.sponsor_id);
  const dollars = s ? d.current_points * s.point_dollar_rate : 0;
  const next = DB.recurring_point_schedule.filter(x=>x.driver_id===d.driver_id&&x.is_active).sort((a,b)=>a.next_run_at.localeCompare(b.next_run_at))[0];
  return `<div class="sign" role="img" aria-label="${n(d.current_points)} points available">
    <div class="sign-in"><div class="sign-label">Points available</div>
      <div><span class="sign-num">${n(d.current_points)}</span><span class="sign-unit">pts</span></div>
      ${next?`<div class="sign-exit">+${n(next.points_amount)} next<small>${fmtD(next.next_run_at)}</small></div>`:""}
      <div class="sign-foot">Worth about ${usd(dollars)} at ${esc(s?s.sponsor_name:"—")}</div></div></div>`;
}
function txTable(rows, showDriver, compact){
  if (!rows.length) return `<div class="empty">No point activity yet.</div>`;
  return `<div class="tw"><table><thead><tr><th>Date</th>${showDriver?"<th>Driver</th>":""}<th>Reason</th>${compact?"":"<th>By</th>"}<th class="num">Change</th><th class="num">Balance</th></tr></thead><tbody>
  ${rows.map(t=>`<tr><td class="when">${fmtDT(t.created_at)}</td>${showDriver?`<td>${esc(uname(t.driver_id))}</td>`:""}<td>${esc(t.reason)}</td>${compact?"":`<td class="dim">${esc(uname(t.performed_by_user_id))}</td>`}
  <td class="num ${t.points_delta>0?"plus":"minus"}">${t.points_delta>0?"+":"−"}${n(Math.abs(t.points_delta))}</td><td class="num">${n(t.balance_after)}</td></tr>`).join("")}</tbody></table></div>`;
}
const byNewest = (a,b)=>b.created_at.localeCompare(a.created_at);



function orderCards(orders, canCancel){
  if(!orders.length) return `<div class="panel empty">No orders yet.</div>`;
  return orders.sort((a,b)=>b.placed_at.localeCompare(a.placed_at)).map(o=>`<div class="panel" style="margin-bottom:14px">
    <div class="row spread"><div><h2 style="margin:0">Order #${o.order_id}</h2><span class="dim">${fmtDT(o.placed_at)} · ${esc(uname(o.driver_id))}${o.placed_by_user_id!==o.driver_id?` · placed by ${esc(uname(o.placed_by_user_id))}`:""}</span></div>
    <div class="row">${badge(o.status)}${canCancel&&o.status==="PLACED"?`<button class="btn danger sm" data-cancel="${o.order_id}">Cancel order</button>`:""}</div></div>
    <div class="tw"><table style="margin-top:10px"><tbody>${DB.order_item.filter(i=>i.order_id===o.order_id).map(i=>`<tr><td>${esc(product(i.product_id).product_name)}</td><td class="num">× ${i.quantity}</td><td class="num">${n(i.unit_point_price*i.quantity)} pts</td></tr>`).join("")}
    <tr><td><b>Total</b></td><td></td><td class="num"><b>${n(o.total_points)} pts</b> <span class="dim">(${usd(o.total_dollar_amount)})</span></td></tr></tbody></table></div></div>`).join("");
}

function bindCancel(){
  document.querySelectorAll("[data-cancel]").forEach(b=>b.onclick=()=>{
    const o=DB.customer_order.find(x=>x.order_id===+b.dataset.cancel);
    o.status="CANCELLED"; o.cancelled_at=now(); addPoints(o.driver_id,o.sponsor_id,o.total_points,`Refund: order #${o.order_id} cancelled`,ME[role]);
    toast(`Order #${o.order_id} cancelled and refunded`); App.render();});
}

function adjustDialog(did){
  const u=user(did);
  $("#dlgBody").innerHTML=`<h2 style="margin:0">Adjust points for ${esc(u.first_name)} ${esc(u.last_name)}</h2>
    <div class="row"><label class="row"><input type="radio" name="dir" value="1" checked> Add</label><label class="row"><input type="radio" name="dir" value="-1"> Deduct</label></div>
    <label class="field">Points<input type="number" id="amt" min="1" value="500" required></label>
    <label class="field">Reason (the driver sees this)<input type="text" id="why" placeholder="e.g. Clean roadside inspection" required></label>
    <div class="row" style="justify-content:flex-end"><button class="btn ghost" value="cancel" formnovalidate>Cancel</button><button class="btn go" value="ok" id="ok">Save adjustment</button></div>`;
  const dlg=$("#dlg"); dlg.showModal();
  dlg.onclose=()=>{ if(dlg.returnValue!=="ok") return; const amt=+$("#amt").value*+document.querySelector("[name=dir]:checked").value, why=$("#why").value.trim();
    if(!amt||!why) return toast("Enter points and a reason.");
    if(LIVE){ App.api(`/api/sponsor/drivers/${did}/points`,{method:"POST",body:{delta:amt,reason:why}})
      .then(()=>{ toast(`${amt>0?"Added":"Deducted"} ${n(Math.abs(amt))} points`); App.refresh(); })
      .catch(e=>toast(e.message)); return; }
    if(addPoints(did,mySponsor(),amt,why,ME.sponsor)){ toast(`${amt>0?"Added":"Deducted"} ${n(Math.abs(amt))} points`); App.render(); } };
}

function audit(e){ DB.audit_event.push({audit_event_id:nextId("audit_event","audit_event_id"),actor_user_id:null,sponsor_id:null,driver_id:null,subject_username:null,entity_type:null,entity_id:null,reason_or_details:null,created_at:now(),...e}); }

const App = {
  page: null,
  me: null,
  ready: (async () => {
    try { const h = await fetch("/api/health"); LIVE = h.ok && (await h.json()).ok === true; } catch { LIVE = false; }
    if (LIVE) { DATA_SOURCE = "live MySQL"; await loadBootstrap(); return; }
    if (!FILE_MODE) { OFFLINE = true; DATA_SOURCE = "offline"; return; }  // served site: no sample-data fallback
    const saved = store.get("tt_db");
    if (saved) { DB = saved.db; DATA_SOURCE = saved.source; return; }
    DB = fromCols(window.MOCK); DATA_SOURCE = "sample data"; saveDB();
  })(),

  // Call the Flask API. Throws Error(message) on failure; sends you to login if the session expired.
  async api(path, { method = "GET", body, redirectOn401 = true } = {}){
    const r = await fetch(path, { method, credentials: "same-origin",
      headers: body ? { "Content-Type": "application/json" } : {}, body: body ? JSON.stringify(body) : undefined });
    let data = null; try { data = await r.json(); } catch {}
    if (r.status === 401 && redirectOn401) {
      store.del("tt_session");
      location.replace(ROOT + "login.html" + (role ? "?next=" + encodeURIComponent(role + "/" + App.page) : ""));
      throw new Error("Please sign in.");
    }
    if (!r.ok) throw new Error(data?.error || `Request failed (${r.status})`);
    return data;
  },

  // Re-read data after a save, then redraw the page.
  async refresh(){ if (LIVE) await loadBootstrap(); App.render(); },

  go(path){ saveDB(); location.href = ROOT + path + ".html"; },
  session(){ return store.get("tt_session"); },

  async start(r, page){
    applyPrefs();
    await App.ready;
    if (OFFLINE) { showOffline(); return; }
    let s = App.session();
    if (LIVE) {
      const r = await fetch("/api/me", { credentials: "same-origin" });
      if (r.ok) { App.me = (await r.json()).user; s = { user_id: App.me.user_id, role: App.me.role }; store.set("tt_session", s); }
      else { s = null; store.del("tt_session"); }
    }
    if (!s || (!LIVE && !user(s.user_id))) { location.replace(ROOT + "login.html?next=" + encodeURIComponent(r + "/" + page)); return; }
    if (s.role !== r) { location.replace(ROOT + HOME[s.role] + ".html"); return; }
    role = r; ME[r] = s.user_id; App.page = page;
    document.title = `${ROUTES[r].find(x=>x[0]===page)[1]} · TigerTruck`;
    App.render();
  },

  async render(){
    renderRail();
    try {
      $("#main").innerHTML = await VIEWS[role][App.page]();
      bind[role]?.[App.page]?.();
    } catch (e) {
      console.error(e);
      $("#main").innerHTML = `<div class="panel empty">Couldn't load this page: ${esc(e.message)}</div>`;
    }
    saveDB();
  },

  async login(identifier, password){
    await App.ready;
    if (OFFLINE) return { ok: false, error: "Can't reach the server right now. Try again in a minute." };
    if (LIVE) {
      try {
        const d = await App.api("/api/login", { method: "POST", body: { username: identifier, password }, redirectOn401: false });
        store.set("tt_session", { user_id: d.user.user_id, role: d.user.role });
        return { ok: true, home: HOME[d.user.role] };
      } catch (e) { return { ok: false, error: e.message }; }
    }
    // Sample mode: simulated login against window.MOCK
    const id = identifier.trim().toLowerCase();
    const u = DB.user_account.find(x => x.username.toLowerCase()===id || x.email.toLowerCase()===id);
    const fail = (msg, details) => { audit({category:"LOGIN", subject_username:identifier.trim()||null, success:false, reason_or_details:details, actor_user_id:null}); saveDB(); return { ok:false, error: msg }; };
    if (!identifier.trim() || !password) return { ok:false, error:"Enter your username and password." };
    if (!u) return fail("Incorrect username or password.", "Failed login: unknown user");
    if (u.account_status === "LOCKED") return fail("This account is locked. Contact your sponsor or an admin to unlock it.", "Failed login: account locked");
    if (u.account_status === "INACTIVE") return fail("This account is inactive.", "Failed login: account inactive");
    // Seed hashes are placeholders, so any password works in sample mode.
    const r = roleKey(u.user_id);
    if (!r) return fail("This account has no role assigned yet.", "Failed login: no role");
    const d = r==="driver" ? driver(u.user_id) : null;
    audit({category:"LOGIN", actor_user_id:u.user_id, sponsor_id:d?.sponsor_id ?? (r==="sponsor" ? DB.sponsor_user.find(s=>s.sponsor_user_id===u.user_id).sponsor_id : null), driver_id:d?.driver_id ?? null, subject_username:u.username, success:true, reason_or_details:"Successful login"});
    store.set("tt_session", { user_id:u.user_id, role:r, at:now() });
    saveDB();
    return { ok:true, home: HOME[r] };
  },

  async logout(){
    if (LIVE) { try { await fetch("/api/logout", { method: "POST", credentials: "same-origin" }); } catch {}
      store.del("tt_session"); location.href = ROOT + "login.html"; return; }
    const s = App.session();
    if (s) { const u=user(s.user_id); audit({category:"LOGOUT", actor_user_id:s.user_id, subject_username:u?.username, success:true, reason_or_details:"Signed out"}); saveDB(); }
    store.del("tt_session");
    location.href = ROOT + "login.html";
  },

  resetDemo(){ store.del("tt_db"); store.del("tt_session"); location.href = ROOT + "login.html"; },
};

function applyPrefs(){
  const t = pref.get("tt_theme"); if (t) document.documentElement.dataset.theme = t;
  if (pref.get("tt_src")==="1") document.body.classList.add("show-src");
}

function showOffline(){
  document.querySelector(".shell")?.classList.add("offline");
  $("#main").innerHTML = `<div class="panel" style="max-width:520px"><h2>Can't reach the server</h2>
    <p class="dim">The site is up, but it can't connect to the backend right now. Try again in a minute.</p>
    <button class="btn go" onclick="location.reload()">Try again</button></div>`;
}

async function loadBootstrap(){
  try { const r = await fetch("/api/bootstrap", { credentials: "same-origin" }); if (r.ok) DB = fromCols(await r.json()); } catch {}
}

function renderRail(){
  let u, sub;
  if (App.me) {
    u = App.me;
    sub = role==="admin" ? "Admin" : (u.sponsor_name || (role==="driver" ? "No sponsor yet" : ""));
  } else {
    u = user(ME[role]);
    sub = roleOf(u.user_id);
    if (role==="sponsor") sub = sponsor(mySponsor()).sponsor_name;
    if (role==="driver") { const d=driver(u.user_id); sub = d.sponsor_id ? sponsor(d.sponsor_id).sponsor_name : "No sponsor yet"; }
  }
  const dark = (document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")) === "dark";
  $("#rail").innerHTML = `
    <a class="brand" href="${ROOT}${HOME[role]}.html" style="color:inherit;text-decoration:none">
      <svg class="shield" viewBox="0 0 40 40" aria-hidden="true"><path d="M20 2c5 3 11 3 16 1 2 13-1 27-16 35C5 30 2 16 4 3c5 2 11 2 16-1z" fill="#00694B" stroke="#fff" stroke-width="2.5"/><text x="20" y="26" text-anchor="middle" font-family="Overpass,sans-serif" font-weight="900" font-size="13" fill="#FFB81C">02</text></svg>
      TigerTruck</a>
    <div class="who"><b>${esc(u.first_name)} ${esc(u.last_name)}</b>${esc(sub)}</div>
    <nav class="nav" aria-label="Main">${ROUTES[role].map(([k,l])=>{ let c; try { c=counts[role][k]?.(); } catch {}
      return `<a href="${ROOT}${role}/${k}.html" ${k===App.page?'aria-current="page"':""}>${l}${c?`<span class="count">${c}</span>`:""}</a>`; }).join("")}</nav>
    <div class="rail-foot">
      <button class="signout" id="signOut">Sign out</button>
      <label><input type="checkbox" id="srcToggle" ${document.body.classList.contains("show-src")?"checked":""}> Show data sources</label>
      <label><input type="checkbox" id="darkToggle" ${dark?"checked":""}> Dark theme</label>
      <span>UI draft · data: <b>${esc(DATA_SOURCE)}</b></span>
      ${LIVE ? "" : `<button class="linkbtn" id="resetDemo">Reset demo data</button>`}
    </div>`;
  $("#signOut").onclick = App.logout;
  if ($("#resetDemo")) $("#resetDemo").onclick = App.resetDemo;
  $("#srcToggle").onchange = e => { document.body.classList.toggle("show-src", e.target.checked); pref.set("tt_src", e.target.checked ? "1" : "0"); };
  $("#darkToggle").onchange = e => { const t = e.target.checked ? "dark" : "light"; document.documentElement.dataset.theme = t; pref.set("tt_theme", t); };
}

window.addEventListener("pagehide", () => { if (Object.keys(DB).length) saveDB(); });
