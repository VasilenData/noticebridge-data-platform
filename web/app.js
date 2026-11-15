import {asList,comparisonLabel,countryLabel,deadlineBrief,filterNotices,noticesCsv,pageWindow,readState,safeReleaseAsset,safeTedUrl,stateQuery,validateBundle,validateOperations,validatePointer,valueText,verifiedJson} from './ui-utils.mjs';

const $ = id => document.getElementById(id);
const number = value => new Intl.NumberFormat('en-GB').format(value);
let bundle;
let operations;
let pointer;
let requestSequence=0;
let page=0;
const PAGE_SIZE=50;
let filtered = [];
let state = readState(location.search);

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
function dateText(value, full=false) {
  if (!value) return 'Not stated';
  const d = new Date(value);
  if (Number.isNaN(d.valueOf())) return String(value);
  return new Intl.DateTimeFormat('en-GB',{day:'numeric',month:full?'long':'short',year:'numeric',timeZone:'UTC'}).format(d);
}
function detailFact(label, value, wide=false) {
  const div = el('div',wide?'fact-wide':'');
  div.append(el('dt','',label),el('dd','',valueText(value)));
  return div;
}
function setLink(anchor, url) {
  const safe = safeTedUrl(url);
  if (!safe) return false;
  anchor.href = safe;
  anchor.target = '_blank';
  anchor.rel = 'noopener noreferrer';
  return true;
}
function statusClass(n) {
  return n.comparison.status === 'compared' && n.comparison.changes.length ? ' changed' : ['missing_parent','ambiguous_parent'].includes(n.comparison.status) ? ' unresolved' : '';
}
function writeUrl() {
  const query = stateQuery(state);
  history.replaceState(null,'',location.pathname + (query ? '?' + query : '') + location.hash);
}
function populateSelect(id, values, label) {
  const select = $(id);
  for (const value of values) {
    const option = el('option','',label(value)); option.value = value; select.append(option);
  }
}

function renderMetadata() {
  const {source,notices,release} = bundle;
  const captured = source.captured_at || release.generated_from_capture_at;
  $('capture-date').textContent = captured ? 'Observed through ' + dateText(captured,true) : 'Capture time not supplied';
  const retained=notices.filter(n=>n.scope==='retained').length;
  $('snapshot-note').textContent = `${number(notices.length)} stored publication identities; ${number(source.coverage?.selected_count || 0)} primary records in the selected capture.`;
  $('notice-total').textContent = number(notices.length);
  $('compared-total').textContent = number(notices.filter(n=>n.comparison.status==='compared').length);
  $('changed-total').textContent = number(notices.filter(n=>n.comparison.status==='compared'&&n.comparison.changes.length).length);
  $('scope-note').replaceChildren(el('strong','','Captured evidence, not current tender status. '),document.createTextNode(`${source.coverage?.description || source.scope || 'Bounded source selection.'} ${number(retained)} records are retained from earlier captures. Absence from a new selection is not a withdrawal.`));
  const captures = source.captured_at ? new Date(source.captured_at) : null;
  const age = captures && Number.isFinite(captures.valueOf()) ? Math.floor((Date.now()-captures.valueOf())/86400000) : null;
  if (age !== null && age >= 2) $('scope-note').append(document.createTextNode(` Captured ${age} days ago; consult the original notice for current deadlines.`));
  $('release-summary').textContent = 'Release ' + (release.id || 'identifier not supplied') + ' · The downloaded bytes were checked against the release ledger before display.';
  const fields = [
    ['Release ID',release.id],['Capture time (UTC)',captured],['Source fingerprint (SHA-256)',release.source_sha256],['Implementation fingerprint (SHA-256)',release.code_sha256],['Selection scope',source.scope],['Source query',typeof source.query==='object'?JSON.stringify(source.query):source.query],
  ];
  $('release-details').replaceChildren(...fields.map(([label,value])=>detailFact(label,value)));
  $('limitations').replaceChildren(...asList(bundle.methodology?.limitations).map(item=>el('li','',item)));
  const countries=[...new Set(notices.flatMap(n=>asList(n.countries)))].sort((a,b)=>countryLabel(a).localeCompare(countryLabel(b)));
  const categories=[...new Set(notices.flatMap(n=>asList(n.cpv_codes).map(v=>String(v).slice(0,2))))].sort();
  populateSelect('country',countries,countryLabel);
  populateSelect('category',categories,v=>'CPV '+v+(v==='72'?' · IT services':''));
  const run=operations.runs.find(item=>item.release_id===release.id);
  $('release-select').value=release.id;
  $('version-note').textContent=release.id===operations.current_release_id?'Latest accepted capture history':`Historical view after capture ${run.sequence} of ${operations.capture_count}`;
  $('release-download').href=run.release_path;$('release-download').hidden=false;
  renderBrief();
}

function renderList(keepPage=false) {
  filtered=filterNotices(bundle.notices,state);
  const list=$('notice-list');
  list.replaceChildren();
  $('empty-state').hidden=filtered.length>0;
  $('results-count').textContent=`${number(filtered.length)} of ${number(bundle.notices.length)} captured notices · newest publications first`;
  $('download-csv').disabled=filtered.length===0;
  if (!filtered.some(n=>n.id===state.notice)) state.notice=(!state.notice&&filtered.some(n=>n.id==='789562-2026')?'789562-2026':filtered[0]?.id) || '';
  if(!keepPage)page=Math.max(0,Math.floor(filtered.findIndex(n=>n.id===state.notice)/PAGE_SIZE));
  const window=pageWindow(filtered,page,PAGE_SIZE);page=window.page;
  $('pagination').hidden=window.pages<2;
  $('page-label').textContent=`${number(window.start+1)}–${number(Math.min(window.start+PAGE_SIZE,window.total))} of ${number(window.total)}`;
  $('page-previous').disabled=page===0;$('page-next').disabled=page===window.pages-1;
  for(const n of window.items) {
    const button=el('button','notice-card'); button.type='button';button.dataset.notice=n.id;
    button.setAttribute('aria-pressed',String(n.id===state.notice));
    button.setAttribute('aria-label',`${n.title}. ${comparisonLabel(n)}. View notice ${n.id}.`);
    const top=el('div','notice-top');top.append(el('span','notice-id',n.id),el('span','status'+statusClass(n),comparisonLabel(n)));
    const bottom=el('div','notice-bottom');
    for(const country of asList(n.countries).slice(0,2)) bottom.append(el('span','notice-country',countryLabel(country)));
    if(asList(n.countries).length>2) bottom.append(el('span','',`+${n.countries.length-2} countries`));
    if(n.scope==='context') bottom.append(el('span','context-mark','LINKED CONTEXT'));
    if(n.scope==='retained') bottom.append(el('span','context-mark','RETAINED HISTORY'));
    const date=el('time','',dateText(n.publication_date));if(n.publication_date)date.dateTime=n.publication_date;bottom.append(date);
    button.append(top,el('h3','',n.title),el('p','notice-buyer',n.buyer||'Buyer not stated in captured fields'),bottom);
    button.addEventListener('click',()=>selectNotice(n.id,true));list.append(button);
  }
  const selected=list.querySelector('[aria-pressed="true"]');
  if(selected){const offset=selected.getBoundingClientRect().top-list.getBoundingClientRect().top+list.scrollTop;if(offset<list.scrollTop||offset+selected.offsetHeight>list.scrollTop+list.clientHeight)list.scrollTop=offset;}
  renderDetail();writeUrl();
}

function selectNotice(id, userAction=false) {
  state.notice=id;
  for(const button of $('notice-list').querySelectorAll('button[data-notice]')) button.setAttribute('aria-pressed',String(button.dataset.notice===id));
  renderDetail();writeUrl();
  if(userAction && matchMedia('(max-width:620px)').matches) {
    $('notice-detail').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion:reduce)').matches?'auto':'smooth',block:'start'});
    $('notice-detail').focus({preventScroll:true});
  }
}

function renderDetail() {
  const pane=$('notice-detail');pane.replaceChildren();pane.tabIndex=-1;
  const n=bundle.notices.find(item=>item.id===state.notice);
  if(!n) {const blank=el('div','detail-placeholder');blank.append(el('span','eyebrow','NO NOTICE SELECTED'),el('h3','','A different filter can reveal more.'),el('p','','Reset your filters to return to the complete captured selection.'));pane.append(blank);return;}
  pane.setAttribute('aria-label','Selected notice '+n.id);
  const top=el('div','detail-top');top.append(el('p','eyebrow','NOTICE / '+n.id),el('span','status'+statusClass(n),comparisonLabel(n)));
  pane.append(top,el('h3','detail-title',n.title));
  const source=el('a','source-link','Read the official notice ↗');
  if(setLink(source,n.source_url))pane.append(source);else pane.append(el('p','revision-note unresolved','No validated TED source link is available.'));
  if(n.has_known_successor){
    const successors=bundle.notices.filter(item=>asList(item.previous_notice_ids).includes(n.id));
    const superseded=el('p','revision-note successor-note','A later linked notice is captured. ');
    for(const [index,item] of successors.entries()){
      if(index)superseded.append(document.createTextNode(' · '));
      const next=el('button','parent-link',item.id);next.type='button';next.addEventListener('click',()=>showNotice(item.id));superseded.append(next);
    }
    if(!successors.length)superseded.append(document.createTextNode('Consult the official source for the latest publication.'));
    pane.append(superseded);
  }
  const facts=el('dl','detail-facts');facts.append(detailFact('Buyer',n.buyer,true),detailFact('Buyer country',asList(n.countries).map(countryLabel)),detailFact('Published',dateText(n.publication_date)),detailFact('Earliest reported lot deadline',n.deadline?dateText(n.deadline,true):null),detailFact('CPV code',asList(n.cpv_codes).join(' · ')));
  if(asList(n.deadline_dates).length>1)facts.append(detailFact('All captured lot deadlines',n.deadline_dates.map(value=>dateText(value,true)),true));
  pane.append(facts);
  const caption=el('h4','section-caption','Revision evidence');caption.append(el('span','',n.comparison.status==='compared'?`${n.comparison.changes.length} field${n.comparison.changes.length===1?'':'s'} changed`: 'EXPLICIT SOURCE LINKS'));
  pane.append(caption);
  const c=n.comparison;
  if(c.status==='compared') {
    const desc=el('p','revision-summary','Compared with linked notice ');
    const parent=el('button','parent-link',c.parent_id);parent.type='button';parent.addEventListener('click',()=>{
      showNotice(c.parent_id);
      if(matchMedia('(max-width:620px)').matches)pane.focus({preventScroll:true});
    });desc.append(parent,document.createTextNode('. Only captured, normalized fields are compared.'));pane.append(desc);
    if(c.changes.length){const changes=el('div','change-list');for(const item of c.changes){const row=el('article','change-item');row.append(el('h5','',item.label||item.field));const vals=el('div','change-values');const before=el('div','change-value change-before');before.append(el('small','','PREVIOUS'),document.createTextNode(valueText(item.before)));const after=el('div','change-value change-after');after.append(el('small','','THIS NOTICE'),document.createTextNode(valueText(item.after)));vals.append(before,el('span','change-arrow','→'),after);row.append(vals);changes.append(row);}pane.append(changes);}else pane.append(el('p','revision-note','The compared fields are unchanged. Other details in the full source documents may differ.'));
  } else {
    const text=c.status==='missing_parent'?`The notice declares a previous version that is outside this capture${asList(c.missing_parent_ids).length?': '+c.missing_parent_ids.join(', '):''}. No change is inferred.`:c.status==='ambiguous_parent'?'More than one possible parent is declared or available. The platform does not choose one silently. Inspect the source notices.':'No previous-notice link is declared in the captured fields. This does not prove that no earlier publication exists.';
    pane.append(el('p','revision-note'+(c.status==='root'?'':' unresolved'),text));
  }
  const fitTitle=el('h4','section-caption','Why it may be relevant');fitTitle.append(el('span','fit-label','RULE-BASED SIGNALS'));pane.append(fitTitle);
  const reasons=asList(n.fit?.reasons);const list=el('ul','fit-reasons');
  for(const reason of reasons.length?reasons:['No configured matching signal is available for this notice.'])list.append(el('li','',typeof reason==='string'?reason:JSON.stringify(reason)));
  pane.append(list,el('p','fit-disclaimer','Matching rules indicate relevance to the configured supplier profile. They are not eligibility checks or award predictions.'));
  const technical=el('details','technical-details');technical.append(el('summary','','Inspect this record’s provenance'));
  const scopeText=n.scope==='context'?'Parent/context record fetched to support a comparison':n.scope==='retained'?'Retained from an earlier capture; not part of the current primary selection':'Primary source selection';
  const dl=el('dl','');dl.append(detailFact('Record scope',scopeText),detailFact('First observed in this dataset',n.first_seen_at),detailFact('Last observed in this dataset',n.last_seen_at),detailFact('Declared previous notices',asList(n.previous_notice_ids)),detailFact('Normalized content fingerprint (SHA-256)',n.content_sha256),detailFact('Matching criteria',asList(n.fit?.criteria).map(v=>typeof v==='string'?v:JSON.stringify(v))));technical.append(dl);pane.append(technical);
}

function syncFilters(){for(const key of ['q','country','category','comparison'])$(key==='q'?'search':key).value=state[key]||'';}
function readFilters(){state={...state,q:$('search').value,country:$('country').value,category:$('category').value,comparison:$('comparison').value};renderList();}

function showNotice(id) {
  state={q:'',country:'',category:'',comparison:'',notice:id,release:state.release};
  syncFilters();renderList();
}

function renderBrief() {
  const cards=$('brief-cards');cards.replaceChildren();
  const rows=deadlineBrief(bundle.notices);
  $('brief').hidden=rows.length===0;
  $('brief-scope').textContent=`From the selected evidence version · ${dateText(bundle.source.captured_at)}`;
  for(const {notice,change} of rows) {
    const card=el('article','brief-card');
    const title=el('h3','',notice.buyer || notice.title);
    const dates=el('div','brief-dates');
    dates.append(el('span','',dateText(change.before)),el('span','brief-arrow','→'),el('strong','',dateText(change.after)));
    const inspect=el('button','brief-inspect','Inspect the correction →');inspect.type='button';
    inspect.addEventListener('click',()=>{showNotice(notice.id);$('explorer').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion:reduce)').matches?'auto':'smooth'});});
    const source=el('a','brief-source','Official notice ↗');setLink(source,notice.source_url);
    const links=el('div','brief-links');links.append(inspect,source);
    card.append(el('span','brief-id',notice.id+' · '+asList(notice.countries).map(countryLabel).join(', ')),title,el('p','brief-date-label','Earliest reported lot deadline'),dates,links);cards.append(card);
  }
}

function renderOperations() {
  $('operations-content').hidden=false;$('operations-unavailable').hidden=true;
  const days=[...new Set(operations.publication_days)].sort();
  const observationDays=[...new Set(operations.runs.map(r=>r.captured_at.slice(0,10)))];
  const metrics=[['Accepted captures',number(operations.capture_count)],['Publication days selected',number(days.length)],['Actual observation days',number(observationDays.length)],['Replay boundary','From empty history']];
  $('operations-metrics').replaceChildren(...metrics.map(([label,value])=>detailFact(label,value)));
  $('clock-note').textContent=`Publication selections cover ${dateText(days[0])}${days.length>1?' to '+dateText(days.at(-1)):''}. These captures were actually collected between ${operations.first_capture_at} and ${operations.last_capture_at}. Historical backfills are labelled; they do not establish operation on those publication dates.`;
  $('operations-download').href=pointer.operations.path;
  const body=$('capture-ledger');body.replaceChildren();
  const select=$('release-select');select.replaceChildren();
  for(const run of [...operations.runs].reverse()) {
    const option=el('option','',`${run.sequence===operations.capture_count?'Latest · ':''}Capture ${run.sequence} · ${run.publication_day} selection · ${run.mode}`);option.value=run.release_id;select.append(option);
  }
  select.disabled=false;
  for(const run of operations.runs) {
    const row=el('tr','');
    const capture=el('th','');capture.scope='row';capture.append(el('strong','','#'+run.sequence),el('span','run-mode',run.mode));
    const observed=el('td','ledger-clock',run.captured_at.replace('T',' ').replace('Z',''));
    const evidence=el('td','');const link=el('a','','Inspect version ↗');link.href=run.release_path;link.target='_blank';link.rel='noopener noreferrer';evidence.append(link);
    row.append(capture,el('td','',run.publication_day),observed,el('td','ledger-numeric',`${number(run.counts.new)} / ${number(run.counts.already_seen)}`),el('td','ledger-numeric',number(run.counts.retained)),el('td','ledger-numeric',number(run.counts.total)),el('td','ledger-numeric',run.acquisition?`${number(run.acquisition.requests)} / ${number(run.acquisition.retries)}`:'Not recorded'),evidence);body.append(row);
  }
  $('replay-note').textContent=`All ${operations.capture_count} archived captures are replayed in actual observation order. Rebuilding from empty history reproduces each published version. Browser assets are checked against SHA-256 fingerprints.`;
  const transport=operations.acquisition;
  if(transport && ['requests','attempts','rate_limits','retries','xml_checks_passed','xml_checks_total'].every(k=>Number.isInteger(transport[k]) && transport[k]>=0)) {
    const proof=$('transport-proof');proof.replaceChildren(el('span','proof-check','↻'),el('strong','',`${number(transport.rate_limits)} real HTTP 429 responses`),el('p','',`${number(transport.requests)} source requests used ${number(transport.attempts)} attempts. ${number(transport.retries)} retries are recorded across accepted captures. ${number(transport.xml_checks_passed)}/${number(transport.xml_checks_total)} selected API/XML representation checks passed. These are observations, not simulated incidents.`));proof.hidden=false;
  }
  const incident=operations.incident_exercise;
  if(incident && Number.isInteger(incident.checks_passed) && Number.isInteger(incident.checks_total) && incident.checks_total>0 && incident.checks_passed<=incident.checks_total) {
    const proof=$('incident-proof');proof.replaceChildren(el('span','proof-check',incident.checks_passed===incident.checks_total?'✓':'!'),el('strong','',`${incident.checks_passed}/${incident.checks_total} recovery checks`),el('p','',incident.label || 'Labelled synthetic recovery exercise.'));
    if(typeof incident.report_url==='string' && /^https:\/\/github\.com\/VasilenData\/noticebridge-data-platform\/blob\/[a-zA-Z0-9._/-]+$/.test(incident.report_url)){const link=el('a','','Inspect the exercise ↗');link.href=incident.report_url;link.target='_blank';link.rel='noopener noreferrer';proof.append(link);}
    proof.hidden=false;
  }
  $('operations-limitations').replaceChildren(...asList(operations.limitations).map(item=>el('li','',item)));
  const capacity=operations.archive_capacity;
  if(Number.isInteger(capacity?.maximum) && Number.isInteger(capacity?.remaining) && capacity.remaining>=0 && capacity.maximum-capacity.remaining===operations.capture_count) {
    const note=$('archive-capacity');note.textContent=`Bounded archive: ${operations.capture_count} of ${capacity.maximum} capture slots used; ${capacity.remaining} remain. The limit counts captures, not days. Collection stops at capacity rather than silently discarding history.`;note.classList.toggle('capacity-warning',capacity.remaining<10);note.hidden=false;
  }
}

async function fetchAsset(asset) {
  if(!safeReleaseAsset(asset))throw new Error('Unsafe release asset path.');
  const response=await fetch(asset.path,{cache:'no-cache'});
  if(!response.ok)throw new Error(`Evidence request failed (${response.status}).`);
  return verifiedJson(await response.arrayBuffer(),asset.sha256);
}

function applyBundle(data,run) {
  const checked=validateBundle(data);
  if(checked.release.id!==run.release_id || checked.source.captured_at!==run.captured_at || checked.notices.length!==run.counts.total)throw new Error('Release does not match its capture ledger.');
  bundle=checked;
  state.release=run.release_id===operations.current_release_id?'':run.release_id;
  for(const id of ['country','category'])while($(id).options.length>1)$(id).remove(1);
  renderMetadata();
  for(const key of ['country','category','comparison'])if(!Array.from($(key).options).some(o=>o.value===state[key]))state[key]='';
  syncFilters();renderList();
}

async function selectRelease(id) {
  const run=operations?.runs.find(item=>item.release_id===id);
  if(!run){$('version-error').textContent='That version is not present in the verified release ledger.';$('version-error').hidden=false;if(bundle){state.release=bundle.release.id===operations.current_release_id?'':bundle.release.id;writeUrl();}return;}
  const request=++requestSequence;
  $('version-error').hidden=true;$('workspace').setAttribute('aria-busy','true');
  try {
    const data=await fetchAsset({path:run.release_path,sha256:run.release_sha256});
    if(request!==requestSequence)return;
    applyBundle(data,run);
  } catch(error) {
    if(request!==requestSequence)return;
    $('version-error').textContent='That historical version could not be verified. The previous verified view remains displayed.';$('version-error').hidden=false;
    if(bundle){$('release-select').value=bundle.release.id;state.release=bundle.release.id===operations.current_release_id?'':bundle.release.id;writeUrl();}
    console.error('NoticeBridge refused a historical view:',error.message);
  } finally {if(request===requestSequence)$('workspace').setAttribute('aria-busy','false');}
}

async function load(){
  const request=++requestSequence;
  $('load-error').hidden=true;$('workspace').setAttribute('aria-busy','true');
  try{
    const response=await fetch('current.json',{cache:'no-cache'});
    if(!response.ok)throw new Error(`Release pointer request failed (${response.status}).`);
    const nextPointer=validatePointer(await response.json());
    const nextOperations=validateOperations(await fetchAsset(nextPointer.operations));
    if(request!==requestSequence)return;
    const latest=nextOperations.runs.at(-1);
    if(latest.release_path!==nextPointer.release.path || latest.release_sha256!==nextPointer.release.sha256)throw new Error('Release pointer and ledger disagree.');
    const run=nextOperations.runs.find(item=>item.release_id===state.release) || latest;
    if(state.release && run.release_id!==state.release)throw new Error('The requested historical version is not in this verified ledger.');
    const data=await fetchAsset({path:run.release_path,sha256:run.release_sha256});
    if(request!==requestSequence)return;
    pointer=nextPointer;operations=nextOperations;renderOperations();applyBundle(data,run);
  }catch(error){
    if(request!==requestSequence)return;
    bundle=undefined;filtered=[];$('notice-list').replaceChildren();$('notice-detail').replaceChildren(el('p','revision-note unresolved','The published evidence could not be validated. No substitute records are displayed.'));$('download-csv').disabled=true;$('results-count').textContent='No evidence displayed';$('load-error').hidden=false;
    $('capture-date').textContent='Evidence unavailable';$('notice-total').textContent='—';$('compared-total').textContent='—';$('changed-total').textContent='—';
    $('operations-content').hidden=true;$('operations-unavailable').hidden=false;$('operations-unavailable').textContent='The capture ledger could not be verified. No operating claims are displayed.';$('release-select').disabled=true;$('release-download').hidden=true;$('brief').hidden=true;$('pagination').hidden=true;
    console.error('NoticeBridge could not load its published bundle:',error.message);
  }finally{if(request===requestSequence)$('workspace').setAttribute('aria-busy','false');}
}

$('filters').addEventListener('submit',event=>event.preventDefault());
$('search').addEventListener('input',()=>{if(bundle)readFilters();});
for(const id of ['country','category','comparison'])$(id).addEventListener('change',()=>{if(bundle)readFilters();});
$('clear-filters').addEventListener('click',()=>{state={...state,q:'',country:'',category:'',comparison:''};syncFilters();if(bundle)renderList();});
$('download-csv').addEventListener('click',()=>{if(!filtered.length)return;const blob=new Blob([noticesCsv(filtered)],{type:'text/csv;charset=utf-8'});const url=URL.createObjectURL(blob);const anchor=el('a','');anchor.href=url;anchor.download='noticebridge-filtered-notices.csv';document.body.append(anchor);anchor.click();anchor.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);});
$('retry-load').addEventListener('click',load);
$('release-select').addEventListener('change',event=>selectRelease(event.target.value));
$('page-previous').addEventListener('click',()=>{page--;renderList(true);$('notice-list').scrollTop=0;});
$('page-next').addEventListener('click',()=>{page++;renderList(true);$('notice-list').scrollTop=0;});
addEventListener('popstate',()=>{state=readState(location.search);if(operations){const id=state.release || operations.current_release_id;if(bundle?.release.id!==id)selectRelease(id);else{syncFilters();renderList();}}});
load();
