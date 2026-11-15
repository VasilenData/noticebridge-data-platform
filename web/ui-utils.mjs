const COUNTRIES = {
  AUT:'Austria',AT:'Austria',BEL:'Belgium',BE:'Belgium',BGR:'Bulgaria',BG:'Bulgaria',
  HRV:'Croatia',HR:'Croatia',CYP:'Cyprus',CY:'Cyprus',CZE:'Czechia',CZ:'Czechia',
  DNK:'Denmark',DK:'Denmark',EST:'Estonia',EE:'Estonia',FIN:'Finland',FI:'Finland',
  FRA:'France',FR:'France',DEU:'Germany',DE:'Germany',GRC:'Greece',GR:'Greece',
  HUN:'Hungary',HU:'Hungary',IRL:'Ireland',IE:'Ireland',ITA:'Italy',IT:'Italy',
  LVA:'Latvia',LV:'Latvia',LTU:'Lithuania',LT:'Lithuania',LUX:'Luxembourg',LU:'Luxembourg',
  MLT:'Malta',MT:'Malta',NLD:'Netherlands',NL:'Netherlands',POL:'Poland',PL:'Poland',
  PRT:'Portugal',PT:'Portugal',ROU:'Romania',RO:'Romania',SVK:'Slovakia',SK:'Slovakia',
  SVN:'Slovenia',SI:'Slovenia',ESP:'Spain',ES:'Spain',SWE:'Sweden',SE:'Sweden',
  CHE:'Switzerland',CH:'Switzerland',NOR:'Norway',NO:'Norway',ISL:'Iceland',IS:'Iceland',
  GBR:'United Kingdom',GB:'United Kingdom',UK:'United Kingdom',USA:'United States',US:'United States',
};

export const countryLabel = code => COUNTRIES[String(code).toUpperCase()] || String(code);
export const asList = value => Array.isArray(value) ? value : value == null ? [] : [value];
export const normalize = value => String(value ?? '').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLocaleLowerCase();
export const safeTedUrl = value => {
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && ['ted.europa.eu','www.ted.europa.eu'].includes(url.hostname)
      && !url.username && !url.password && !url.port && !url.search && !url.hash && /^\/([a-z]{2}\/)?notice\/-\/detail\/\d{1,8}-\d{4}\/?$/.test(url.pathname)
      ? url.href : null;
  } catch { return null; }
};

export function comparisonLabel(notice) {
  const c = notice.comparison || {};
  if (c.status === 'compared') return (c.changes || []).length ? 'Fields changed' : 'Selected fields unchanged';
  if (c.status === 'missing_parent') return 'Parent missing';
  if (c.status === 'ambiguous_parent') return 'Parent ambiguous';
  return 'No parent declared';
}

export function filterNotices(notices, {q='',country='',category='',comparison=''} = {}) {
  const terms = normalize(q).trim().split(/\s+/).filter(Boolean);
  return notices.filter(notice => {
    const text = normalize([notice.id,notice.title,notice.buyer,...asList(notice.countries).map(countryLabel)].join(' '));
    const c = notice.comparison || {};
    return terms.every(term => text.includes(term))
      && (!country || asList(notice.countries).includes(country))
      && (!category || asList(notice.cpv_codes).some(code => String(code).startsWith(category)))
      && (!comparison || (comparison === 'changed' ? c.status === 'compared' && (c.changes || []).length > 0
        : comparison === 'unresolved' ? ['missing_parent','ambiguous_parent'].includes(c.status)
        : c.status === comparison));
  });
}

export function csvCell(value) {
  let text = Array.isArray(value) ? value.join('; ') : String(value ?? '');
  // Excel and similar spreadsheets can interpret a leading formula after whitespace.
  if (/^[\s\u0000-\u001F\uFEFF]*[=+\-@]/.test(text) || /^[\t\r\n]/.test(text)) text = "'" + text;
  return '"' + text.replaceAll('"','""') + '"';
}

export function noticesCsv(notices) {
  const header = ['Notice ID','Title','Buyer','Buyer countries','CPV codes','Publication date','Earliest reported lot deadline','All captured lot deadlines','Revision evidence','Parent ID','Changed fields','TED source'];
  return '\uFEFF' + [header,...notices.map(n => [n.id,n.title,n.buyer,asList(n.countries).map(countryLabel),n.cpv_codes,n.publication_date,n.deadline,asList(n.deadline_dates),comparisonLabel(n),n.comparison?.parent_id,asList(n.comparison?.changes).map(c=>c.label || c.field),safeTedUrl(n.source_url) || ''])].map(row => row.map(csvCell).join(',')).join('\r\n') + '\r\n';
}

export function readState(search) {
  const params = new URLSearchParams(search);
  return {q:params.get('q') || '',country:params.get('country') || '',category:params.get('category') || '',comparison:params.get('comparison') || '',notice:params.get('notice') || '',release:params.get('release') || ''};
}

export function stateQuery(state) {
  const params = new URLSearchParams();
  for (const key of ['q','country','category','comparison','notice','release']) if (state[key]) params.set(key,state[key]);
  return params.toString();
}

export function validateBundle(data) {
  if (data?.schema_version !== 1 || !Array.isArray(data.notices) || !data.source || !data.release) throw new Error('Unsupported evidence bundle.');
  const ids = new Set();
  for (const notice of data.notices) {
    if (typeof notice.id !== 'string' || !notice.id || ids.has(notice.id) || typeof notice.title !== 'string'
      || !['root','compared','missing_parent','ambiguous_parent'].includes(notice.comparison?.status)
      || !Array.isArray(notice.comparison.changes)) throw new Error('Invalid or duplicated notice identity.');
    ids.add(notice.id);
  }
  return data;
}

export const valueText = value => value == null || value === '' ? 'Not stated in captured fields' : Array.isArray(value) ? value.join(' · ') || 'Not stated in captured fields' : String(value);

const HASH = /^[a-f0-9]{64}$/;
export function safeReleaseAsset(asset) {
  return !!asset && HASH.test(asset.sha256) && asset.path === `releases/${asset.sha256}.json`;
}

export function validatePointer(pointer) {
  if (pointer?.schema_version !== 1 || !safeReleaseAsset(pointer.release) || !safeReleaseAsset(pointer.operations)) throw new Error('Invalid release pointer.');
  return pointer;
}

export async function verifiedJson(bytes, sha256) {
  if (!(bytes instanceof ArrayBuffer) || bytes.byteLength > 64 * 1024 * 1024 || !HASH.test(sha256)) throw new Error('Invalid or oversized evidence asset.');
  const digest = new Uint8Array(await globalThis.crypto.subtle.digest('SHA-256',bytes));
  const actual = Array.from(digest,b=>b.toString(16).padStart(2,'0')).join('');
  if (actual !== sha256) throw new Error('Evidence bytes do not match the published fingerprint.');
  return JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes));
}

export function validateOperations(ops) {
  const iso = value => typeof value === 'string' && /(?:Z|\+00:00)$/.test(value) && Number.isFinite(Date.parse(value));
  if (ops?.schema_version !== 1 || !Array.isArray(ops.runs) || !ops.runs.length || ops.runs.length > 1000
    || ops.capture_count !== ops.runs.length || ops.replay_verified !== true || !HASH.test(ops.current_release_id)
    || !Array.isArray(ops.publication_days) || !ops.publication_days.every(d=>/^\d{4}-\d{2}-\d{2}$/.test(d))
    || !iso(ops.first_capture_at) || !iso(ops.last_capture_at) || !HASH.test(ops.code_sha256)) throw new Error('Invalid operating evidence.');
  const capacity = ops.archive_capacity;
  if (!Number.isInteger(capacity?.maximum) || !Number.isInteger(capacity?.remaining)
    || capacity.maximum < ops.capture_count || capacity.remaining !== capacity.maximum - ops.capture_count) throw new Error('Archive capacity does not reconcile.');
  const seen = new Set();
  let previous = -Infinity, priorTotal = 0;
  for (const [index,run] of ops.runs.entries()) {
    const time = Date.parse(run.captured_at);
    if (run.sequence !== index + 1 || !['bootstrap','backfill','refresh'].includes(run.mode)
      || !iso(run.captured_at) || time < previous || !/^\d{4}-\d{2}-\d{2}$/.test(run.publication_day)
      || !HASH.test(run.source_sha256) || !HASH.test(run.release_id) || seen.has(run.release_id)
      || !safeReleaseAsset({path:run.release_path,sha256:run.release_sha256})
      || !['incoming','new','already_seen','retained','resolved_parents','total'].every(k=>Number.isInteger(run.counts?.[k]) && run.counts[k]>=0)
      || run.counts.incoming !== run.counts.new + run.counts.already_seen
      || run.counts.total !== run.counts.incoming + run.counts.retained
      || run.counts.total !== priorTotal + run.counts.new
      || run.counts.retained !== priorTotal - run.counts.already_seen
      || run.counts.resolved_parents > priorTotal
      || (run.duration_ms != null && (!Number.isFinite(run.duration_ms) || run.duration_ms<0))) throw new Error('Invalid capture ledger entry.');
    previous = time; priorTotal = run.counts.total; seen.add(run.release_id);
  }
  const days = [...new Set(ops.runs.map(run=>run.publication_day))].sort();
  if (JSON.stringify(days) !== JSON.stringify(ops.publication_days) || ops.runs.at(-1).release_id !== ops.current_release_id || ops.runs[0].captured_at !== ops.first_capture_at || ops.runs.at(-1).captured_at !== ops.last_capture_at) throw new Error('Operating evidence does not reconcile.');
  return ops;
}

export function pageWindow(rows, requestedPage=0, size=50) {
  if (!Number.isInteger(size) || size < 1 || size > 100) throw new Error('Invalid page size.');
  const pages = Math.max(1,Math.ceil(rows.length/size));
  const page = Math.max(0,Math.min(Number.isInteger(requestedPage)?requestedPage:0,pages-1));
  const start = page*size;
  return {items:rows.slice(start,start+size),page,pages,start,total:rows.length};
}

export function deadlineBrief(notices, limit=3) {
  return notices.filter(n=>!n.has_known_successor && n.comparison?.status==='compared' && safeTedUrl(n.source_url))
    .map(n=>({notice:n,change:asList(n.comparison.changes).find(c=>c.field==='deadline')}))
    .filter(({change})=>change && /^\d{4}-\d{2}-\d{2}$/.test(change.before) && /^\d{4}-\d{2}-\d{2}$/.test(change.after) && change.before!==change.after)
    .sort((a,b)=>String(b.notice.publication_date).localeCompare(String(a.notice.publication_date)) || b.notice.id.localeCompare(a.notice.id))
    .slice(0,Math.max(0,Math.min(limit,10)));
}
