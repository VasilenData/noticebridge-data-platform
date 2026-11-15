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
      && !url.username && !url.password && !url.port && /^\/([a-z]{2}\/)?notice\/-\/detail\/\d{1,8}-\d{4}\/?$/.test(url.pathname)
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
  return {q:params.get('q') || '',country:params.get('country') || '',category:params.get('category') || '',comparison:params.get('comparison') || '',notice:params.get('notice') || ''};
}

export function stateQuery(state) {
  const params = new URLSearchParams();
  for (const key of ['q','country','category','comparison','notice']) if (state[key]) params.set(key,state[key]);
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
