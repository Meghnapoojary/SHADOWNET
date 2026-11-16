const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const state = { overview: null, cases: [], links: [], selectedCase: null, selectedLink: null, threshold: 90, weights: {} };
const api = async (url, options = {}) => {
  const response = await fetch(url, options);
  const type = response.headers.get('content-type') || '';
  const data = type.includes('application/json') ? await response.json() : await response.text();
  if (!response.ok) throw new Error(data?.detail || data || `Request failed (${response.status})`);
  return data;
};
const fmtNum = n => new Intl.NumberFormat('en-IN').format(Number(n || 0));
const money = n => '₹' + new Intl.NumberFormat('en-IN', {maximumFractionDigits:0}).format(Number(n || 0));
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let toastTimer;
function toast(message, isError = false) {
  const el = $('#toast'); el.textContent = message; el.style.borderColor = isError ? 'rgba(255,116,126,.45)' : 'rgba(69,220,196,.28)';
  el.style.background = isError ? '#482b34' : '#183b43'; el.classList.add('show'); clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 3500);
}
function setBusy(button, busy, label = 'Working…') {
  if (!button) return;
  if (busy) { button.dataset.oldLabel = button.innerHTML; button.disabled = true; button.textContent = label; }
  else { button.disabled = false; if (button.dataset.oldLabel) button.innerHTML = button.dataset.oldLabel; }
}

async function loadCore() {
  const [overview, cases, links, validation] = await Promise.all([
    api('/api/overview'), api('/api/cases'), api('/api/links'), api('/api/validation')
  ]);
  state.overview = overview; state.cases = cases; state.links = links;
  renderOverview(overview, validation); renderCaseList(); populateCompareSelects(); updateDataMode();
  await renderAnomalyPreview();
  $('#nav-link-count').textContent = links.length;
  $('#signal-direct-count').textContent = overview.direct_link_count;
  $('#signal-fingerprint-count').textContent = overview.fingerprint_link_count;
  $('#threshold-slider').value = overview.threshold; $('#threshold-value').textContent = `${overview.threshold} / 100`;
}

async function renderAnomalyPreview() {
  const holder = $('#anomaly-list');
  try {
    const data = await api('/api/anomalies');
    if (!data.available) { holder.innerHTML = `<p class="subtle-label" style="margin-top:14px">${escapeHTML(data.reason)}</p>`; return; }
    holder.innerHTML = data.items.slice(0,5).map(item => `<div class="anomaly-row"><div><strong>${escapeHTML(item.transaction_id)}</strong><small>${escapeHTML(item.case_id)} · ${escapeHTML(item.bank)} · ${escapeHTML(item.timestamp.slice(0,16).replace('T',' '))} UTC</small></div><div class="anomaly-meter"><i style="width:${item.relative_unusualness_index}%"></i></div><b>${item.relative_unusualness_index}</b></div>`).join('');
  } catch (e) { holder.innerHTML = `<p class="subtle-label">Anomaly screen unavailable: ${escapeHTML(e.message)}</p>`; }
}

function updateDataMode() {
  const label = $('#data-mode-label'); label.textContent = state.overview?.data_mode || 'DATA LOADED';
  label.style.color = (state.overview?.data_mode || '').includes('SIMULATED') ? 'var(--amber)' : 'var(--teal)';
}
function renderOverview(o, validation) {
  $('#stat-cases').textContent = fmtNum(o.case_count); $('#stat-transactions').textContent = fmtNum(o.transaction_count);
  $('#stat-direct').textContent = fmtNum(o.direct_link_count); $('#stat-fingerprint').textContent = fmtNum(o.fingerprint_link_count);
  $('#validation-snapshot').innerHTML = validation.checks.map(c => `<div class="validation-mini"><span class="check-dot">${c.passed?'✓':'!'}</span><span>${escapeHTML(c.name)}</span><strong style="margin-left:auto;color:${c.passed?'var(--green)':'var(--red)'}">${c.passed?'PASS':'REVIEW'}</strong></div>`).join('');
  const top = [...state.links].sort((a,b) => (a.type === b.type ? (b.score||100)-(a.score||100) : a.type === 'direct' ? -1 : 1)).slice(0,4);
  $('#recent-links').innerHTML = top.length ? top.map(l => `<div class="recent-link"><span class="link-type-dot ${l.type==='fingerprint'?'fingerprint':''}"></span><div class="recent-link-main"><strong>${escapeHTML(l.case_a)} ↔ ${escapeHTML(l.case_b)}</strong><small>${l.type==='direct'?'Shared account '+escapeHTML(l.shared_account_id):'Disconnected fingerprint match'}</small></div><span class="recent-link-score">${l.type==='direct'?'DIRECT':`${l.score}/100`}</span></div>`).join('') : '<p class="subtle-label">No qualifying relationships in this dataset.</p>';
}
function navigate(view) {
  $$('.view').forEach(v => v.classList.toggle('active', v.id === `view-${view}`));
  $$('.nav-item').forEach(n => n.classList.toggle('active', n.dataset.view === view));
  const title = ({overview:'Overview',graph:'Relationship graph',cases:'Case explorer',fingerprints:'Fingerprint lab',scenario:'Scenario lab',validation:'Validation & data'})[view] || 'Overview';
  $('#current-section').textContent = title;
  if (view === 'graph') renderRelationshipGraph();
  if (view === 'validation') loadValidation();
  if (view === 'cases' && !state.selectedCase && state.cases.length) selectCase(state.cases[0].case_id);
  window.scrollTo({top:0, behavior:'smooth'});
}
$$('.nav-item').forEach(btn => btn.addEventListener('click', () => navigate(btn.dataset.view)));
$$('[data-go]').forEach(btn => btn.addEventListener('click', () => navigate(btn.dataset.go)));

function renderCaseList(filter = '') {
  const list = state.cases.filter(c => `${c.case_id} ${c.bank}`.toLowerCase().includes(filter.toLowerCase()));
  $('#case-list-count').textContent = list.length;
  $('#case-list').innerHTML = list.map(c => `<button class="case-item ${state.selectedCase===c.case_id?'selected':''}" data-case="${escapeHTML(c.case_id)}"><strong>${escapeHTML(c.case_id)}</strong><small>${escapeHTML(c.bank)}</small><div class="case-item-meta"><span>${c.transaction_count} TRANSACTIONS</span><span>${money(c.total_amount)}</span></div></button>`).join('') || '<p class="subtle-label">No cases match your search.</p>';
  $$('.case-item').forEach(b => b.addEventListener('click', () => selectCase(b.dataset.case)));
}
$('#case-search').addEventListener('input', e => renderCaseList(e.target.value));
function populateCompareSelects() {
  const options = state.cases.map(c => `<option value="${escapeHTML(c.case_id)}">${escapeHTML(c.case_id)} — ${escapeHTML(c.bank)}</option>`).join('');
  $('#compare-a').innerHTML = options; $('#compare-b').innerHTML = options;
  if (state.cases.length > 1) $('#compare-b').selectedIndex = Math.min(1, state.cases.length-1);
}

// SVG graph uses textContent for every user/data label; no uploaded value is inserted as SVG markup.
const SVG_NS = 'http://www.w3.org/2000/svg';
function svgEl(tag, attrs = {}, text = null) {
  const el = document.createElementNS(SVG_NS, tag);
  Object.entries(attrs).forEach(([k,v]) => el.setAttribute(k, String(v)));
  if (text !== null) el.textContent = String(text);
  return el;
}
function renderRelationshipGraph() {
  const holder = $('#relationship-graph'); holder.innerHTML = '';
  if (!state.cases.length) { holder.textContent = 'No case data loaded.'; return; }
  const width = Math.max(holder.clientWidth, 760), height = Math.max(holder.clientHeight, 430);
  const svg = svgEl('svg', {viewBox:`0 0 ${width} ${height}`, role:'img', 'aria-label':'Cross-case relationships'});
  const defs = svgEl('defs');
  const marker = svgEl('marker',{id:'arrowDirect',viewBox:'0 0 10 10',refX:'8',refY:'5',markerWidth:'5',markerHeight:'5',orient:'auto-start-reverse'});
  marker.appendChild(svgEl('path',{d:'M 0 0 L 10 5 L 0 10 z',fill:'#62e2a1'})); defs.appendChild(marker);
  const glow = svgEl('filter',{id:'softGlow',x:'-50%',y:'-50%',width:'200%',height:'200%'}); glow.appendChild(svgEl('feGaussianBlur',{stdDeviation:'2',result:'b'})); defs.appendChild(glow); svg.appendChild(defs);
  const cx=width/2, cy=height/2, rx=Math.min(width*.37,340), ry=Math.min(height*.34,170), positions={};
  state.cases.forEach((c,i)=>{const a=(-Math.PI/2)+(2*Math.PI*i/state.cases.length);positions[c.case_id]={x:cx+Math.cos(a)*rx,y:cy+Math.sin(a)*ry};});
  state.links.forEach((l,i)=>{
    const a=positions[l.case_a], b=positions[l.case_b]; if(!a||!b)return;
    const curve=`M ${a.x} ${a.y} Q ${(a.x+b.x)/2+(i%2?25:-25)} ${(a.y+b.y)/2-22} ${b.x} ${b.y}`;
    const hit=svgEl('path',{d:curve,class:'graph-edge-hit','data-link-hit':i,tabindex:'0',role:'button','aria-label':`${l.type==='direct'?'Direct shared-account link':'Behavioural fingerprint match'} between ${l.case_a} and ${l.case_b}`});
    hit.addEventListener('click',()=>selectLink(l,path));
    hit.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();selectLink(l,path);}});
    svg.appendChild(hit);
    const path=svgEl('path',{d:curve,class:`graph-edge ${l.type}`, 'data-link':i, 'marker-end': l.type==='direct'?'url(#arrowDirect)':'none'});
    path.addEventListener('click',()=>selectLink(l,path));
    svg.appendChild(path);
    if(l.type==='fingerprint'){
      const mid=svgEl('text',{x:(a.x+b.x)/2,y:(a.y+b.y)/2-15,class:'graph-edge-label','text-anchor':'middle'},`${l.score}`);
      svg.appendChild(mid);
    } else {
      const mid=svgEl('text',{x:(a.x+b.x)/2,y:(a.y+b.y)/2-15,class:'graph-edge-label','text-anchor':'middle'},'SHARED ID'); svg.appendChild(mid);
    }
  });
  state.cases.forEach((c,i)=>{
    const p=positions[c.case_id], g=svgEl('g',{class:'graph-node','data-case':c.case_id, tabindex:'0', role:'button'});
    g.appendChild(svgEl('circle',{cx:p.x,cy:p.y,r:35}));
    g.appendChild(svgEl('text',{x:p.x,y:p.y-2},c.case_id.replace('CASE-','')));
    g.appendChild(svgEl('text',{x:p.x,y:p.y+13,class:'node-sub'},`${c.transaction_count} TX`));
    const title=svgEl('title',{},`${c.case_id} · ${c.bank}`);g.appendChild(title);
    g.addEventListener('click',()=>{state.selectedCase=c.case_id; renderCaseList($('#case-search').value); navigate('cases'); selectCase(c.case_id);});
    g.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();g.dispatchEvent(new Event('click'));}});
    svg.appendChild(g);
  });
  holder.appendChild(svg); $('#graph-total-label').textContent = `${state.links.length} relationships · ${state.cases.length} cases`;
  if (state.selectedLink) {
    const idx=state.links.findIndex(l=>l.link_id===state.selectedLink.link_id); if(idx>=0) selectLink(state.selectedLink, svg.querySelector(`[data-link="${idx}"]`));
  }
}
function selectLink(link, element) {
  state.selectedLink=link; $$('.graph-edge').forEach(e=>e.classList.remove('selected')); if(element)element.classList.add('selected');
  const panel=$('#link-inspector');
  if(link.type==='direct') {
    const all=[...(link.evidence_a||[]).map(x=>({...x,case:link.case_a})),...(link.evidence_b||[]).map(x=>({...x,case:link.case_b}))];
    panel.innerHTML=`<div class="inspector-content"><span class="tag tag-green">DIRECT ACCOUNT OVERLAP</span><h3>${escapeHTML(link.case_a)} ↔ ${escapeHTML(link.case_b)}</h3><p class="inspector-meta">${escapeHTML(link.bank_a)} · ${escapeHTML(link.bank_b)}</p><div class="inspector-score direct">Shared ID</div><div class="inspector-meta">Canonical identifier: <strong>${escapeHTML(link.shared_account_id)}</strong></div><div class="evidence-block"><h4>TRANSACTION-LEVEL EVIDENCE</h4><div class="evidence-list">${all.map(x=>`<div class="evidence-chip"><b>${escapeHTML(x.case)} · ${escapeHTML(x.institution||'Institution not supplied')}</b><br/>${escapeHTML(x.transaction_id)} · Role: ${escapeHTML(x.role)} · ${money(x.amount)}<br/>Original ID: ${escapeHTML(x.raw_account_id||link.shared_account_id)}<br/>Canonical ID: ${escapeHTML(x.canonical_account_id||link.shared_account_id)}${x.alias_mapped?`<br/><strong style="color:var(--amber)">OPERATOR-ATTESTED ALIAS</strong><br/>Operator: ${escapeHTML(x.attested_by||'Not recorded')}<br/>Provenance: ${escapeHTML(x.source_reference||'Not recorded')}`:'<br/>Resolution: Exact identifier match'}<br/>${new Date(x.timestamp).toLocaleString()}</div>`).join('')}</div></div><div class="evidence-block"><h4>INTERPRETATION</h4><p class="inspector-meta">${escapeHTML(link.explanation)} This shows an identifier overlap in the supplied records; it does not establish beneficial ownership or common control. Alias mappings are operator-supplied and are not independently authenticated by this prototype.</p></div></div>`;
  } else {
    const comp=link.comparison;
    panel.innerHTML=`<div class="inspector-content"><span class="tag tag-amber">DISCONNECTED FINGERPRINT MATCH</span><h3>${escapeHTML(link.case_a)} ↔ ${escapeHTML(link.case_b)}</h3><p class="inspector-meta">${escapeHTML(link.bank_a)} · ${escapeHTML(link.bank_b)}</p><div class="inspector-score">${link.score}<small style="font-size:14px;color:var(--muted2)"> / 100</small></div><div class="inspector-meta">Heuristic similarity score · No canonical account IDs shared · Both cases meet sample-size gate</div><div class="evidence-block"><h4>STRONGEST ALIGNMENTS</h4><div class="evidence-list">${comp.strongest_alignments.map(f=>`<div class="evidence-chip"><b>${escapeHTML(f.label)}</b><br/>Similarity ${f.similarity}% · A: ${f.value_a} · B: ${f.value_b} · Weight: ${(f.weight*100).toFixed(1)}%</div>`).join('')}</div></div><div class="evidence-block"><h4>NOTABLE DIFFERENCES</h4><div class="evidence-list">${comp.notable_differences.map(f=>`<div class="evidence-chip"><b>${escapeHTML(f.label)}</b><br/>Similarity ${f.similarity}% · Difference ${f.difference} · A: ${f.value_a} · B: ${f.value_b}</div>`).join('')}</div></div><div class="evidence-block"><h4>ALL 16 FEATURE CHECKS</h4><div class="evidence-list">${comp.features.map(f=>`<div class="evidence-chip"><b>${escapeHTML(f.label)}</b><br/>A: ${f.value_a} · B: ${f.value_b} · Similarity: ${f.similarity}%</div>`).join('')}</div></div><div class="evidence-block"><h4>INTERPRETATION</h4><p class="inspector-meta">${escapeHTML(link.explanation)} Similarity is not proof of a shared actor or criminal conduct.</p></div></div>`;
  }
}
$('#graph-refresh').addEventListener('click', async()=>{try{state.links=await api('/api/links');renderRelationshipGraph();toast('Relationship graph refreshed.')}catch(e){toast(e.message,true)}});

async function selectCase(caseId) {
  state.selectedCase=caseId; renderCaseList($('#case-search').value);
  const target=$('#case-detail-area'); target.innerHTML='<div class="panel empty-state"><div class="loading-line" style="width:60%"></div></div>';
  try {
    const detail=await api(`/api/cases/${encodeURIComponent(caseId)}`);
    target.innerHTML=`<div class="case-detail-top"><div class="mini-stat"><span>TRANSACTIONS</span><strong>${detail.transaction_count}</strong></div><div class="mini-stat"><span>REPORTED VALUE</span><strong>${money(detail.total_amount)}</strong></div><div class="mini-stat"><span>INSTITUTION</span><strong style="font-size:12px">${escapeHTML(detail.bank)}</strong></div></div><div class="case-detail-grid"><div class="panel detail-panel"><div class="panel-heading"><div><div class="eyebrow">ACCOUNT NETWORK</div><h3>Money-flow trail</h3></div><span class="subtle-label">SOURCE → BENEFICIARY</span></div><div class="account-graph" id="account-graph"></div></div><div class="panel detail-panel"><div class="eyebrow">BEHAVIOURAL PROFILE</div><h3 style="font-size:14px;margin:6px 0">16-feature fingerprint</h3><div class="fingerprint-list">${Object.entries(detail.fingerprint).map(([k,v])=>`<div class="fp-row"><span title="${escapeHTML(k)}">${escapeHTML(k.replaceAll('_',' '))}</span><div class="fp-track"><i style="width:${Math.min(100,Math.max(2,Number(v)*100))}%"></i></div><strong>${Number(v).toFixed(2)}</strong></div>`).join('')}</div></div></div><div class="panel detail-panel" style="margin-top:12px"><div class="panel-heading"><div><div class="eyebrow">SOURCE RECORDS</div><h3>Transaction history</h3></div><span class="subtle-label">${detail.transactions.length} ROWS</span></div><div class="tx-table-wrap"><table class="tx-table"><thead><tr><th>TRANSACTION</th><th>TIMESTAMP (UTC)</th><th>SOURCE</th><th>BENEFICIARY</th><th>CHANNEL</th><th style="text-align:right">AMOUNT</th></tr></thead><tbody>${detail.transactions.map(t=>`<tr><td>${escapeHTML(t.transaction_id)}</td><td>${new Date(t.timestamp).toLocaleString()}</td><td>${escapeHTML(t.source_account)}</td><td>${escapeHTML(t.target_account)}</td><td>${escapeHTML(t.channel)}</td><td class="amount">${money(t.amount)}</td></tr>`).join('')}</tbody></table></div></div>`;
    const graph=await api(`/api/cases/${encodeURIComponent(caseId)}/graph`); renderAccountGraph(graph);
  } catch(e) { target.innerHTML=`<div class="panel empty-state"><h3>Could not load case</h3><p>${escapeHTML(e.message)}</p></div>`; }
}
function renderAccountGraph(data) {
  const holder=$('#account-graph'); if(!holder)return;
  const w=Math.max(holder.clientWidth,400), h=260, svg=svgEl('svg',{viewBox:`0 0 ${w} ${h}`});
  const nodes=data.nodes, pos={};
  const defs=svgEl('defs'); const marker=svgEl('marker',{id:'miniArrow',viewBox:'0 0 10 10',refX:'8',refY:'5',markerWidth:'4',markerHeight:'4',orient:'auto'}); marker.appendChild(svgEl('path',{d:'M0 0 L10 5 L0 10 z',fill:'#45dcc4'})); defs.appendChild(marker); svg.appendChild(defs);
  nodes.forEach((n,i)=>{const a=-Math.PI/2+2*Math.PI*i/nodes.length;pos[n.id]={x:w/2+Math.cos(a)*Math.min(w*.34,150),y:h/2+Math.sin(a)*92};});
  data.edges.forEach(e=>{const a=pos[e.source],b=pos[e.target];if(!a||!b)return;svg.appendChild(svgEl('line',{x1:a.x,y1:a.y,x2:b.x,y2:b.y,stroke:'#3c9f94','stroke-width':1.6,'marker-end':'url(#miniArrow)'}));});
  nodes.forEach(n=>{const p=pos[n.id];svg.appendChild(svgEl('circle',{cx:p.x,cy:p.y,r:13,fill:'#1b4a53',stroke:'#45dcc4','stroke-width':1.2}));svg.appendChild(svgEl('text',{x:p.x,y:p.y+28,fill:'#a8c0c4','font-size':7,'text-anchor':'middle'},n.id.length>15?n.id.slice(0,14)+'…':n.id));});
  holder.appendChild(svg);
}

$('#compare-btn').addEventListener('click', async()=>{
  const a=$('#compare-a').value,b=$('#compare-b').value,btn=$('#compare-btn');
  if(!a||!b||a===b){toast('Choose two different cases.',true);return;}
  setBusy(btn,true,'Comparing…');
  try {const r=await api(`/api/fingerprints/compare?case_a=${encodeURIComponent(a)}&case_b=${encodeURIComponent(b)}`);renderComparison(r);}
  catch(e){toast(e.message,true)} finally{setBusy(btn,false)}
});
function renderComparison(r) {
  const c=r.comparison; const eligible=r.fingerprint_eligible; const linked=eligible&&r.meets_threshold;
  $('#compare-result').innerHTML=`<div class="compare-summary"><div class="panel score-panel"><div class="eyebrow">BEHAVIOURAL SIMILARITY</div><div class="score-number">${c.score}<small style="font-size:16px;color:var(--muted2)">/100</small></div><div class="score-label">Heuristic resemblance score</div><div class="score-track"><i style="width:${c.score}%"></i></div><div class="result-pills"><span class="result-pill ${r.has_direct_overlap?'warn':'good'}">${r.has_direct_overlap?`${r.shared_account_ids.length} shared ID(s)`:'No shared account IDs'}</span><span class="result-pill ${eligible?'good':'warn'}">${eligible?'Sample size eligible':'Below minimum sample size'}</span><span class="result-pill ${linked?'good':'warn'}">${linked?'Meets link threshold':'Does not qualify as fingerprint link'}</span></div></div><div class="panel comparison-panel"><div class="eyebrow">COMPARISON CONTEXT</div><h3 style="margin:7px 0 12px;font-size:15px">${escapeHTML(r.case_a)} <span style="color:var(--teal)">vs</span> ${escapeHTML(r.case_b)}</h3><div class="evidence-row"><span>Transactions in A</span><strong>${r.transactions_a}</strong></div><div class="evidence-row"><span>Transactions in B</span><strong>${r.transactions_b}</strong></div><div class="evidence-row"><span>Minimum required in each case</span><strong>5</strong></div><div class="evidence-row"><span>Configured threshold</span><strong>${r.threshold}/100</strong></div><div class="evidence-row"><span>Interpretation</span><strong>${r.has_direct_overlap?'Direct overlap takes precedence':linked?'Disconnected behavioural match':'No qualifying fingerprint link'}</strong></div><p class="subtle-label" style="line-height:1.6;margin-top:12px">${escapeHTML(c.interpretation)}</p></div></div><div class="panel feature-results"><div class="panel-heading"><div><div class="eyebrow">EXPLAINABLE COMPARISON</div><h3>Feature-by-feature alignment</h3></div><span class="subtle-label">16 FEATURES · NORMALISED CONTRIBUTION</span></div><div style="margin-top:14px">${c.features.map(f=>`<div class="feature-row"><span class="feature-name" title="${escapeHTML(f.feature)}">${escapeHTML(f.label)}</span><div class="feature-compare-track"><i style="width:${f.similarity}%"></i></div><div class="feature-compare-track"><i style="width:${Math.min(100,f.weight*100)}%;background:#7f9eaa"></i></div><strong>${f.similarity}%</strong></div>`).join('')}</div><p class="subtle-label" style="margin-top:12px">Each feature's similarity is shown beside its configured relative weight. Similarity is not a fraud probability.</p></div>`;
}

const exampleScenario = [
  {timestamp:'2026-11-02T09:10:00Z',source_account:'SCN-A',target_account:'SCN-B',amount:1100,channel:'UPI'},
  {timestamp:'2026-11-02T09:20:00Z',source_account:'SCN-A',target_account:'SCN-C',amount:900,channel:'UPI'},
  {timestamp:'2026-11-02T10:00:00Z',source_account:'SCN-B',target_account:'SCN-D',amount:1050,channel:'IMPS'},
  {timestamp:'2026-11-02T10:10:00Z',source_account:'SCN-C',target_account:'SCN-D',amount:850,channel:'IMPS'},
  {timestamp:'2026-11-02T11:00:00Z',source_account:'SCN-D',target_account:'SCN-E',amount:1800,channel:'NEFT'},
  {timestamp:'2026-11-02T12:15:00Z',source_account:'SCN-E',target_account:'SCN-F',amount:900,channel:'UPI'},
  {timestamp:'2026-11-02T12:20:00Z',source_account:'SCN-E',target_account:'SCN-G',amount:900,channel:'UPI'},
  {timestamp:'2026-11-02T13:05:00Z',source_account:'SCN-F',target_account:'SCN-H',amount:890,channel:'IMPS'}
];
$('#load-scenario-example').addEventListener('click',()=>{$('#scenario-json').value=JSON.stringify(exampleScenario,null,2);toast('Example sequence loaded. It is fictional test data.');});
$('#scenario-json').value=JSON.stringify(exampleScenario,null,2);
$('#evaluate-scenario').addEventListener('click',async()=>{
  const btn=$('#evaluate-scenario'); $('#scenario-error').textContent='';
  let transactions; try{transactions=JSON.parse($('#scenario-json').value);}catch(e){$('#scenario-error').textContent='JSON format error: '+e.message;return;}
  setBusy(btn,true,'Evaluating…');
  try{const r=await api('/api/scenario/evaluate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({transactions})});renderScenario(r);}
  catch(e){$('#scenario-error').textContent=e.message;toast(e.message,true)}finally{setBusy(btn,false)}
});
function renderScenario(r){
  const el=$('#scenario-result');
  if(!r.fingerprint_eligible){el.innerHTML=`<div class="empty-state"><div class="empty-icon">!</div><h3>More evidence required</h3><p>${escapeHTML(r.message)}</p></div>`;return;}
  el.innerHTML=`<div class="eyebrow">SCENARIO RESULT</div><h3 style="font-size:17px;margin:7px 0">${r.transaction_count} transactions compared</h3><p class="subtle-label">Top five behavioural neighbours in the loaded reference dataset.</p>${r.nearest_matches.map((m,i)=>`<div class="match-card"><div class="match-head"><strong>${i+1}. ${escapeHTML(m.case_id)}</strong><b>${m.score}/100</b></div><div class="score-track"><i style="width:${m.score}%"></i></div><p>${m.comparison.strongest_alignments.slice(0,3).map(x=>escapeHTML(x.label)).join(' · ')||'No dominant feature alignments'}</p></div>`).join('')}<div class="scenario-note">${escapeHTML(r.interpretation)} A high score is a lead for review, not a conclusion of fraud or common control.</div>`;
}

function validationEvidenceLine(check){
  const e=check.evidence||{};
  if(check.name==='Known shared-account pair'){
    return e.shared_account_id ? `Shared ID: ${e.shared_account_id} · ${e.case_pair} · Evidence rows: ${(e.evidence_rows||0)} · A: ${(e.transactions_a||[]).join(', ')} · B: ${(e.transactions_b||[]).join(', ')}` : 'Expected fixture pair was not found in the loaded data.';
  }
  if(check.name==='Disconnected high-match pair'){
    return e.case_pair ? `No shared IDs · ${e.transactions_a} + ${e.transactions_b} transactions · ${e.score}/100 vs ${e.threshold} threshold · Alignments: ${(e.top_alignments||[]).join(', ')||'see fingerprint comparison'}` : 'Expected disconnected fixture pair was not found.';
  }
  if(check.name==='Benign look-alike pair'){
    return e.case_pair ? `No shared IDs · ${e.transactions_a} + ${e.transactions_b} transactions · ${e.score}/100 remains below ${e.threshold} threshold.` : 'Expected negative-control pair was not found.';
  }
  return `${e.transactions_supplied||4} transactions supplied · ${e.minimum_required||5} required · ${e.nearest_matches_returned||0} nearest matches returned.`;
}
function renderAliasAudit(aliases){
  const holder=$('#alias-audit-list');
  if(!holder)return;
  if(!aliases.items?.length){
    holder.innerHTML='<p class="subtle-label">No alias mappings applied in this session. Use the synthetic example to demonstrate the workflow.</p>';
    return;
  }
  holder.innerHTML=`<div class="alias-audit-heading"><b>APPLIED MAPPING AUDIT</b><span>${aliases.items.length} RECORD(S)</span></div><div class="alias-audit-table-wrap"><table class="alias-audit-table"><thead><tr><th>INSTITUTION</th><th>ORIGINAL ID</th><th>CANONICAL ID</th><th>OPERATOR / AUTHORITY</th><th>SOURCE REFERENCE</th></tr></thead><tbody>${aliases.items.map(a=>`<tr><td>${escapeHTML(a.institution)}</td><td>${escapeHTML(a.account_id)}</td><td><strong>${escapeHTML(a.canonical_account_id)}</strong></td><td>${escapeHTML(a.attested_by)}</td><td>${escapeHTML(a.source_reference)}</td></tr>`).join('')}</tbody></table></div><p class="alias-audit-note">Mappings are operator-attested and include provenance. SHADOWNET does not independently authenticate the operator or source record, and it does not infer aliases.</p>`;
}
async function loadValidation(){
  const [v,aliases,settings]=await Promise.all([api('/api/validation'),api('/api/aliases'),api('/api/settings')]);
  $('#validation-summary').innerHTML=`<div><div class="eyebrow">DETERMINISTIC DEMO CHECKS · ${escapeHTML(v.dataset_mode||'REFERENCE FIXTURES')}</div><strong style="display:block;font-size:15px;margin-top:5px">Four required cases test links, non-links and minimum evidence</strong><span class="subtle-label">Shared-ID detection · disconnected match · benign negative control · minimum sample gate</span></div><div class="validation-score">${v.passed}/${v.total} <small>checks passed</small></div>`;
  $('#validation-cards').innerHTML=v.checks.map((c,i)=>`<article class="validation-card ${c.passed?'passed':'failed'}"><span class="state">${c.passed?'✓ PASS':'! REVIEW'} · 0${i+1}</span><h4>${escapeHTML(c.name)}</h4><p><b>Expected:</b> ${escapeHTML(c.expected)}<br/><b>Actual:</b> ${escapeHTML(c.actual)}<br/>${escapeHTML(c.detail)}</p><div class="validation-evidence"><b>Observed evidence</b><span>${escapeHTML(validationEvidenceLine(c))}</span></div></article>`).join('');
  $('#alias-count').textContent=`${aliases.count} operator-attested mappings applied`;
  renderAliasAudit(aliases);
  state.threshold=settings.threshold; state.weights=settings.weights;
  renderWeightControls(settings.features);
}
function renderWeightControls(features){
  const holder=$('#weight-controls'); if(!holder)return;
  holder.innerHTML=features.map(f=>`<div class="weight-control"><label for="weight-${f.key}">${escapeHTML(f.label)}</label><input type="range" min="0" max="0.20" step="0.01" value="${f.weight}" data-weight="${f.key}" id="weight-${f.key}"/><strong>${Math.round(f.weight*100)}%</strong></div>`).join('');
  $$('[data-weight]',holder).forEach(input=>input.addEventListener('input',()=>{input.nextElementSibling.textContent=Math.round(Number(input.value)*100)+'%';state.weights[input.dataset.weight]=Number(input.value);}));
}
$('#run-validation').addEventListener('click',async()=>{const btn=$('#run-validation');setBusy(btn,true,'Running checks…');try{await loadValidation();toast('Validation complete.');}catch(e){toast(e.message,true)}finally{setBusy(btn,false)}});
async function loadBundledDemo(dataset, button){
  setBusy(button,true,'Loading sample data…');
  try{
    await api('/api/load-demo-sample',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({dataset})});
    state.selectedCase=null;state.selectedLink=null;
    await loadCore();await loadValidation();renderCaseList();
    if($('#view-graph').classList.contains('active'))renderRelationshipGraph();
    toast(dataset==='evaluator'?'Evaluator sample loaded: 11 cases / 86 transactions.':'Reference sample loaded: 9 cases / 74 transactions.');
  }catch(e){toast(e.message,true)}finally{setBusy(button,false)}
}
$('#load-evaluator-data').addEventListener('click',e=>loadBundledDemo('evaluator',e.currentTarget));
$('#load-reference-data').addEventListener('click',e=>loadBundledDemo('reference',e.currentTarget));
$('#run-validation-top').addEventListener('click',()=>navigate('validation'));
$('#threshold-slider').addEventListener('input',e=>$('#threshold-value').textContent=`${e.target.value} / 100`);
$('#save-threshold').addEventListener('click',async()=>{
  const btn=$('#save-threshold');setBusy(btn,true,'Re-analysing…');
  try{await api('/api/settings',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({threshold:Number($('#threshold-slider').value),weights:state.weights})});await loadCore();await loadValidation();toast('Threshold applied; cross-case links re-analysed.');if($('#view-graph').classList.contains('active'))renderRelationshipGraph();}
  catch(e){toast(e.message,true)}finally{setBusy(btn,false)}
});
const csvInput = $('#csv-file');
const selectedFileMeta = $('#selected-file-meta');
const requiredCsvHeaders = ['transaction_id','case_id','bank','timestamp','source_account','target_account','amount'];

csvInput.addEventListener('change', async () => {
  const file = csvInput.files?.[0];
  $('#upload-status').textContent = '';
  if (!file) { selectedFileMeta.textContent = 'No file selected. Choose a transaction CSV, not the dataset index or ZIP.'; return; }
  if (file.name.toLowerCase().includes('dataset_index')) {
    selectedFileMeta.textContent = `${file.name} is an index, not transaction data. Choose 00_full_reference_9cases_74transactions.csv or 07_evaluator_combined_with_low_sample.csv.`;
    selectedFileMeta.style.color = 'var(--red)';
    return;
  }
  if (!file.name.toLowerCase().endsWith('.csv')) {
    selectedFileMeta.textContent = 'This is not a .csv file. Extract the ZIP first, then select a CSV inside it.';
    selectedFileMeta.style.color = 'var(--red)';
    return;
  }
  if (file.size > 5 * 1024 * 1024) {
    selectedFileMeta.textContent = 'File is larger than the 5 MB upload limit.';
    selectedFileMeta.style.color = 'var(--red)';
    return;
  }
  try {
    const headerLine = (await file.slice(0, 65536).text()).split(/\r?\n/, 1)[0];
    const headers = headerLine.split(',').map(v => v.trim().replace(/^\uFEFF/, '').replace(/^"|"$/g, '').toLowerCase());
    const missing = requiredCsvHeaders.filter(h => !headers.includes(h));
    if (missing.length) {
      selectedFileMeta.textContent = `Wrong CSV format. Missing required columns: ${missing.join(', ')}. Use a SHADOWNET transaction dataset.`;
      selectedFileMeta.style.color = 'var(--red)';
      return;
    }
    selectedFileMeta.textContent = `Ready: ${file.name} · ${(file.size / 1024).toFixed(1)} KB · transaction columns detected.`;
    selectedFileMeta.style.color = 'var(--green)';
  } catch (err) {
    selectedFileMeta.textContent = `Could not read the file header: ${err.message}`;
    selectedFileMeta.style.color = 'var(--red)';
  }
});

$('#upload-form').addEventListener('submit', async e => {
  e.preventDefault();
  const file = csvInput.files?.[0];
  if (!file) { toast('Choose a transaction CSV first.', true); return; }
  if (!file.name.toLowerCase().endsWith('.csv') || file.name.toLowerCase().includes('dataset_index') || file.size > 5 * 1024 * 1024) {
    toast('Choose a valid transaction CSV under 5 MB. Do not upload the ZIP or dataset index.', true); return;
  }
  const form = new FormData(); form.append('file', file, file.name);
  const btn = $('#upload-form button'); setBusy(btn, true, 'Uploading and analysing…');
  $('#upload-status').textContent = 'Uploading file and validating transaction records…';
  $('#upload-status').style.color = 'var(--muted)';
  try {
    const result = await api('/api/upload', {method: 'POST', body: form});
    // The server has accepted and analysed the dataset. Keep that success distinct
    // from a later dashboard-refresh problem so users are not told upload failed.
    $('#upload-status').textContent = `Uploaded successfully: ${result.overview.transaction_count} transactions across ${result.overview.case_count} cases (${result.overview.account_count} account IDs).`;
    $('#upload-status').style.color = 'var(--green)';
    csvInput.value = '';
    selectedFileMeta.textContent = 'Upload complete. Choose another transaction CSV to replace the active dataset.';
    try {
      await loadCore();
      await loadValidation();
      toast('Dataset validated and loaded.');
    } catch (refreshError) {
      $('#upload-status').textContent += ` Dashboard refresh warning: ${refreshError.message}. The server accepted the dataset; refresh the page.`;
      $('#upload-status').style.color = 'var(--amber)';
      toast('Upload succeeded; refresh the page to update the dashboard.', true);
    }
  } catch (error) {
    const message = error.message || 'Unknown upload error.';
    $('#upload-status').textContent = `Upload not completed: ${message}`;
    $('#upload-status').style.color = 'var(--red)';
    selectedFileMeta.style.color = 'var(--red)';
    toast(message, true);
  } finally { setBusy(btn, false); }
});
$('#load-alias-demo').addEventListener('click',()=>{
  const form=$('#alias-form');
  const sample={institution:'Lighthouse Credit',account_id:'LIGHT-L1',canonical_account_id:'NORTH-M1',attested_by:'SHADOWNET demo operator (synthetic test)',source_reference:'SYNTHETIC-ALIAS-TEST-001'};
  Object.entries(sample).forEach(([key,value])=>{form.elements[key].value=value;});
  $('#alias-status').textContent='Synthetic example loaded. This is a fictional operator-attestation workflow, not real bank verification.';
  $('#alias-status').style.color='var(--amber)';
});
$('#alias-form').addEventListener('submit',async e=>{
  e.preventDefault();const form=e.currentTarget;const data=Object.fromEntries(new FormData(form).entries());
  const isSynthetic=String(data.source_reference||'').startsWith('SYNTHETIC-');
  try{
    const r=await api('/api/aliases',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
    $('#alias-status').textContent=isSynthetic
      ? 'Synthetic demo mapping applied. The relationship graph has been recalculated; this is not external bank verification.'
      : 'Operator-attested mapping applied with provenance. Confirm the source authority independently.';
    $('#alias-status').style.color=isSynthetic?'var(--amber)':'var(--green)';
    await loadCore();await loadValidation();
    if($('#view-graph').classList.contains('active'))renderRelationshipGraph();
    form.reset();toast('Alias mapping applied and audit record displayed.');
  }
  catch(err){$('#alias-status').textContent=err.message;$('#alias-status').style.color='var(--red)';toast(err.message,true)}
});
$('#reset-demo-btn').addEventListener('click',async()=>{if(!confirm('Restore the fictional reference dataset and remove uploaded data and alias mappings?'))return;try{await api('/api/reset-demo',{method:'POST'});state.selectedCase=null;state.selectedLink=null;await loadCore();renderCaseList();toast('Reference dataset restored.');if($('#view-graph').classList.contains('active'))renderRelationshipGraph();}catch(e){toast(e.message,true)}});

// First paint
(async()=>{
  try{await loadCore();await loadValidation();if(state.cases.length)$('#compare-a').selectedIndex=4;$('#compare-b').selectedIndex=5;}
  catch(e){toast('Could not connect to the API: '+e.message,true);}
})();
