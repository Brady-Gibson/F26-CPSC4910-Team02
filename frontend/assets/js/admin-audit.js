/* Audit log only: shared filters for the table and the administrator CSV export. */
let auditFilters = {}, auditLoadVersion = 0, auditLoading = false, auditExporting = false;
function auditQuery(filters) {
  return new URLSearchParams(Object.entries(filters).filter(([, value]) => value !== '')).toString();
}
function auditCountText(count) { return `${n(count)} matching ${count === 1 ? 'entry' : 'entries'}`; }
function auditRows(entries) {
  return entries.map(a => `<tr><td class="when">${esc(a.created_at)}</td><td>${esc(a.category.replaceAll('_', ' ').toLowerCase())}</td>
    <td>${esc(a.subject_username || '—')}<br><span class="dim">by ${esc(a.actor_name || 'System')}</span></td>
    <td>${esc(a.sponsor_name || '—')}</td><td style="white-space:pre-wrap">${esc(a.reason_or_details)}</td>
    <td>${a.success ? badge('ACTIVE').replace('active', 'ok') : badge('FAIL').replace('fail', 'failed')}</td></tr>`).join('') ||
    '<tr><td colspan="6" class="empty">No audit entries match these filters.</td></tr>';
}
function sampleAudit(filters) {
  const entries = DB.audit_event.map(a => ({...a, actor_name: uname(a.actor_user_id),
    sponsor_name: DB.sponsor_organization.find(s => s.sponsor_id === a.sponsor_id)?.sponsor_name})).filter(a =>
      (!filters.category || a.category === filters.category) &&
      (filters.success === undefined || filters.success === '' || String(Number(Boolean(a.success))) === filters.success) &&
      (!filters.sponsor_id || String(a.sponsor_id) === filters.sponsor_id) &&
      (!filters.start_date || a.created_at.slice(0,10) >= filters.start_date) &&
      (!filters.end_date || a.created_at.slice(0,10) <= filters.end_date))
    .sort((a,b) => byNewest(a,b) || b.audit_event_id - a.audit_event_id);
  return {entries, categories:[...new Set(DB.audit_event.map(a => a.category))].sort(), sponsors:DB.sponsor_organization};
}
async function loadAudit(filters) {
  return LIVE ? App.api('/api/admin/audit?' + auditQuery(filters)) : sampleAudit(filters);
}
function auditDownloadState() {
  $('#auditDownload').disabled = !LIVE || auditLoading || auditExporting;
}
VIEWS.admin.audit = async () => {
  const data = await loadAudit(auditFilters);
  const options = (items, selected) => items.map(([value,label]) => `<option value="${esc(value)}" ${String(value) === selected ? 'selected' : ''}>${esc(label)}</option>`).join('');
  return `<div class="head"><div><h1>Audit log</h1><p class="sub">Review activity and download all entries matching your filters.</p></div>
    <button type="button" class="btn go" id="auditDownload" ${LIVE ? '' : 'disabled'}>Download CSV</button></div>
    <form id="auditFilters" class="panel"><div class="row" style="align-items:flex-end">
      <label class="field">Category<select name="category"><option value="">All categories</option>${options(data.categories.map(c => [c,c]), auditFilters.category)}</select></label>
      <label class="field">Result<select name="success"><option value="">Any result</option>${options([['1','Succeeded'],['0','Failed']], auditFilters.success)}</select></label>
      <label class="field">Sponsor<select name="sponsor_id"><option value="">All sponsors</option>${options(data.sponsors.map(s => [s.sponsor_id,s.sponsor_name]), auditFilters.sponsor_id)}</select></label>
      <label class="field">Start date<input type="date" name="start_date" value="${esc(auditFilters.start_date || '')}"></label>
      <label class="field">End date<input type="date" name="end_date" value="${esc(auditFilters.end_date || '')}"></label>
      <button type="submit" class="btn ghost">Apply filters</button><button type="button" class="btn ghost" id="auditClear">Clear filters</button>
    </div><p class="dim">Dates are inclusive and use the database timestamps shown below.${LIVE ? '' : ' CSV downloads require signing in to the live server.'}</p>
    <p id="auditError" role="alert"></p></form>
    <p id="auditCount" role="status" aria-live="polite">${auditCountText(data.entries.length)}</p>
    <div class="panel flush"><div class="tw"><table><thead><tr><th>When (database time)</th><th>Category</th><th>User</th><th>Sponsor</th><th>Details</th><th>Result</th></tr></thead>
    <tbody id="auditRows">${auditRows(data.entries)}</tbody></table></div></div>`;
};
async function applyAuditFilters() {
  const version = ++auditLoadVersion, form = $('#auditFilters');
  auditLoading = true; auditDownloadState();
  const filters = Object.fromEntries(new FormData(form));
  $('#auditError').textContent = '';
  if (!form.reportValidity()) return;
  if (filters.start_date && filters.end_date && filters.start_date > filters.end_date) {
    $('#auditError').textContent = 'Start date must be on or before end date.';
    return;
  }
  $('#auditCount').textContent = 'Loading matching entries…';
  try {
    const {entries} = await loadAudit(filters);
    if (version !== auditLoadVersion) return;
    auditFilters = filters;
    $('#auditRows').innerHTML = auditRows(entries);
    $('#auditCount').textContent = auditCountText(entries.length);
    auditLoading = false; auditDownloadState();
  } catch (error) {
    if (version !== auditLoadVersion) return;
    $('#auditError').textContent = error.message;
    $('#auditCount').textContent = 'Filters could not be applied. Try Apply filters again.';
    // Keep export disabled until these filters have successfully loaded.
  }
}
async function downloadAuditCsv() {
  if (!LIVE || auditLoading || auditExporting) return;
  auditExporting = true; auditDownloadState();
  $('#auditDownload').textContent = 'Downloading…';
  $('#auditError').textContent = '';
  try {
    const response = await fetch('/api/admin/audit/export.csv?' + auditQuery(auditFilters), {credentials:'same-origin'});
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.error || 'Could not download the audit log. Please sign in again or retry.');
    }
    const blob = await response.blob(), url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    const filename = /filename="([^"]+)"/.exec(response.headers.get('Content-Disposition') || '')?.[1];
    link.href = url; link.download = filename || 'audit-log.csv';
    document.body.appendChild(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    toast('CSV download started.');
  } catch (error) {
    $('#auditError').textContent = error.message;
  } finally {
    auditExporting = false; auditDownloadState();
    $('#auditDownload').textContent = 'Download CSV';
  }
}
bind.admin.audit = () => {
  const form = $('#auditFilters');
  form.onsubmit = event => {event.preventDefault(); applyAuditFilters();};
  form.onchange = applyAuditFilters;
  // A typed date must be applied before exporting; do not silently use older filters.
  form.oninput = () => {++auditLoadVersion; auditLoading = true; auditDownloadState();};
  $('#auditClear').onclick = () => {
    form.querySelectorAll('input,select').forEach(input => input.value = '');
    applyAuditFilters();
  };
  $('#auditDownload').onclick = downloadAuditCsv;
};
App.start('admin', 'audit');
