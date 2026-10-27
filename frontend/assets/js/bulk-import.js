/* RC#1: stream a UTF-8 file; preserve physical line numbers and empty columns. */
async function* importFileLines(file) {
  const reader = file.stream().getReader(), decoder = new TextDecoder('utf-8', {fatal:true});
  let pending = '', number = 0;
  try {
    while (true) {
      const {value, done} = await reader.read();
      pending += decoder.decode(value, {stream:!done});
      let end;
      while ((end = pending.indexOf('\n')) !== -1) {
        yield {number:++number, text:pending.slice(0,end).replace(/\r$/, '')};
        pending = pending.slice(end+1);
      }
      if (done) break;
    }
    if (pending.length) yield {number:++number, text:pending.replace(/\r$/, '')};
  } finally { await reader.cancel(); reader.releaseLock(); }
}
function importCsvCell(value) {
  let text = String(value ?? '');
  if (/^[\t\r\n]/.test(text) || /^[=+@-]/.test(text.trimStart())) text = "'" + text;
  return '"' + text.replaceAll('"','""') + '"';
}
const importRole = document.body.dataset.importRole;
let importing = false;
VIEWS[importRole]['bulk-import'] = () => `<div class="head"><div><h1>Bulk import</h1>
  <p class="sub">${importRole === 'admin' ? 'Create organizations, sponsor users, and drivers.' : 'Add drivers and sponsor users to your organization.'}</p></div></div>
  <div class="panel"><h2>Prepare your file</h2>
  <p>Choose a UTF-8 text file. One record per line, no header. Separate fields with a pipe (<code>|</code>); pipes cannot appear inside values.</p>
  <p style="overflow-wrap:anywhere"><code>type|organization name|first name|last name|email|points|reason</code></p>
  <ul><li><b>D</b> = driver; <b>S</b> = sponsor user.${importRole === 'admin' ? ' <b>O</b> = organization; use <code>O|Organization name</code> before its users.' : ' Organization records (O) are not allowed. Leave the organization column empty: <code>D||First|Last|email</code>.'}</li>
  <li>Points and reason are optional. Points must be a whole number; supplying points requires a reason. Negative amounts cannot take the balance below zero.</li>
  <li>Points on sponsor-user records are reported and ignored. ${importRole === 'sponsor' ? 'An organization name is also reported and ignored; all users go into your own organization.' : 'New organizations start active at $0.01 per point; change the rate in organization settings if needed.'}</li>
  <li>Existing users are matched by email. Drivers are accepted automatically. Existing passwords and other sponsor balances are preserved.</li>
  <li>Existing account limits apply: names 50 characters, email/organization 100, reason 500. Invalid records are skipped; later lines continue.</li></ul>
  <p>No total file-size limit is imposed. Each valid line is saved independently. Importing the same points again adds them again.</p>
  <form id="bulkForm"><label class="field">User file<input type="file" id="bulkFile" accept=".txt,text/plain" required></label>
  <p>New accounts receive generated login details in the credentials download. Share these privately with their users and ask them to change their initial password.</p>
  <button class="btn go" id="bulkSubmit" ${!LIVE || App.me?.viewed_by ? 'disabled' : ''}>Import file</button>
  ${!LIVE ? '<p>Imports require signing in to the live server.</p>' : ''}</form></div>
  <div class="panel"><p id="bulkStatus" role="status" aria-live="polite">No file imported yet.</p>
  <p id="bulkError" role="alert"></p><div class="row"><button class="btn ghost" id="bulkReport" disabled>Download line report</button>
  <button class="btn ghost" id="bulkCredentials" disabled>Download new-user credentials</button></div>
  <p class="dim">Downloads are available only on this page. The table shows the latest 100 results; the report contains every processed line.</p>
  <div class="tw"><table><thead><tr><th>Line</th><th>Result</th><th>Details</th></tr></thead><tbody id="bulkRows"></tbody></table></div></div>`;

bind[importRole]['bulk-import'] = () => {
  let report = [], credentials = [], created = 0;
  const download = (parts, filename) => {
    const url=URL.createObjectURL(new Blob(['\ufeff',...parts], {type:'text/csv;charset=utf-8'}));
    const a=document.createElement('a');a.href=url;a.download=filename;document.body.appendChild(a);a.click();a.remove();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
  };
  $('#bulkReport').onclick=()=>download(report,'bulk-import-results.csv');
  $('#bulkCredentials').onclick=()=>download(credentials,'bulk-import-credentials.csv');
  const guard=e=>{if(importing || created){e.preventDefault();e.returnValue='';}};
  window.addEventListener('beforeunload',guard);
  $('#bulkForm').onsubmit=async e=>{
    e.preventDefault(); if(importing || !LIVE || App.me?.viewed_by)return;
    const file=$('#bulkFile').files[0];if(!file)return;
    if(report.length && !confirm('Starting a new import replaces the current downloadable report and credentials. Have you saved what you need?'))return;
    importing=true;created=0;
    report=['Line,Result,Details\r\n'];credentials=['Line,Email,Username,Initial password\r\n'];
    $('#bulkRows').textContent='';$('#bulkError').textContent='';
    $('#bulkSubmit').disabled=true;$('#bulkFile').disabled=true;
    $('#bulkReport').disabled=true;$('#bulkCredentials').disabled=true;
    let processed=0, succeeded=0, warnings=0, errors=0, currentLine=0;
    try {
      for await(const line of importFileLines(file)) {
        currentLine=line.number;
        $('#bulkStatus').textContent=`Processing line ${currentLine}… ${succeeded} saved, ${warnings} with warnings, ${errors} skipped.`;
        // One line per request keeps a connection failure's uncertain outcome to one record.
        const {results}=await App.api('/api/bulk-import',{method:'POST',body:{lines:[line]},redirectOn401:false});
        const r=results[0];processed++;
        if(r.status==='error')errors++;else{succeeded++;if(r.status==='warning')warnings++;}
        const details=[r.message,...r.warnings].join(' ');
        report.push([r.line,r.status,details].map(importCsvCell).join(',')+'\r\n');
        if(r.initial_password){credentials.push([r.line,r.email,r.username,r.initial_password].map(importCsvCell).join(',')+'\r\n');created++;}
        $('#bulkRows').insertAdjacentHTML('beforeend',`<tr><td>${r.line}</td><td>${esc(r.status)}</td><td>${esc(details)}</td></tr>`);
        if($('#bulkRows').children.length>100)$('#bulkRows').firstElementChild.remove();
      }
      $('#bulkStatus').textContent=processed ? `Finished: ${processed} lines processed; ${succeeded} saved (${warnings} with warnings), ${errors} skipped.` : 'The file is empty. Nothing was changed.';
    } catch(error) {
      $('#bulkStatus').textContent=`Stopped after ${processed} confirmed results. Earlier successful lines remain saved.`;
      $('#bulkError').textContent=`${error.message} Check line ${currentLine || 1} before resuming: if a request lost its response, that line may have been saved. Do not reimport confirmed points. Save the report and credentials below.`;
    } finally {
      importing=false;$('#bulkSubmit').disabled=false;$('#bulkFile').disabled=false;
      $('#bulkReport').disabled=processed===0;$('#bulkCredentials').disabled=created===0;
    }
  };
};
App.start(importRole,'bulk-import');
