import assert from 'node:assert/strict';
import test from 'node:test';
import {csvCell,filterNotices,noticesCsv,readState,safeTedUrl,stateQuery,validateBundle,valueText} from './ui-utils.mjs';

const rows=[
  {id:'10-2026',title:'Sécurité du réseau',buyer:'Ville de Liège',countries:['BEL'],cpv_codes:['72000000'],publication_date:'2026-11-01',comparison:{status:'compared',parent_id:'9-2026',changes:[{field:'deadline',label:'Deadline',before:'2026-10-01',after:'2026-11-01'}]},source_url:'https://ted.europa.eu/en/notice/-/detail/10-2026'},
  {id:'11-2026',title:'Network support',buyer:'Public buyer',countries:['PRT'],cpv_codes:['72200000'],comparison:{status:'missing_parent',changes:[]},source_url:'javascript:alert(1)'},
  {id:'12-2026',title:'Office equipment',buyer:'Buyer',countries:['BEL'],cpv_codes:['30000000'],comparison:{status:'root',changes:[]}},
];

test('combined filters preserve accent-insensitive word matching and actual revision status',()=>{
  assert.deepEqual(filterNotices(rows,{q:'securite liege',country:'BEL',category:'72',comparison:'changed'}).map(n=>n.id),['10-2026']);
  assert.deepEqual(filterNotices(rows,{comparison:'unresolved'}).map(n=>n.id),['11-2026']);
  assert.equal(filterNotices(rows,{country:'DEU'}).length,0);
  assert.equal(filterNotices(rows,{q:'security'}).length,0);
});

test('source links require an exact TED host, HTTPS, no credentials and a notice path',()=>{
  assert.equal(safeTedUrl(rows[0].source_url),rows[0].source_url);
  for(const url of ['javascript:alert(1)','https://ted.europa.eu.evil.test/en/notice/-/detail/1','http://ted.europa.eu/en/notice/-/detail/1','https://user@ted.europa.eu/en/notice/-/detail/1','https://ted.europa.eu/redirect?to=evil.test','https://ted.europa.eu:444/en/notice/-/detail/1'])assert.equal(safeTedUrl(url),null,url);
});

test('CSV treats formula prefixes as literal text, including whitespace and control prefixes',()=>{
  for(const value of ['=SUM(A1:A2)','+123','-42','@cmd','  =1','\t=1','\rhello','\nhello','\u0000=1'])assert.ok(csvCell(value).startsWith('"\''),JSON.stringify(value));
  assert.equal(csvCell('A "quoted", title'),'"A ""quoted"", title"');
  assert.equal(csvCell('ordinary\nmultiline'),'"ordinary\nmultiline"');
  const csv=noticesCsv(rows);
  assert.ok(csv.startsWith('\uFEFF'));
  assert.ok(!csv.includes('javascript:'));
  assert.ok(csv.includes('Deadline'));
});

test('query state roundtrips punctuation, Unicode and selected notice without executable interpolation',()=>{
  const state={q:'réseau & support <script>',country:'PRT',category:'72',comparison:'changed',notice:'10-2026'};
  assert.deepEqual(readState('?'+stateQuery(state)),state);
  assert.equal(stateQuery({q:'',country:'',category:'',comparison:'',notice:''}),'');
});

test('bundle validation rejects duplicate identities and unsupported comparison states',()=>{
  const base={schema_version:1,source:{},release:{},notices:rows};
  assert.equal(validateBundle(base),base);
  assert.throws(()=>validateBundle({...base,notices:[rows[0],rows[0]]}));
  assert.throws(()=>validateBundle({...base,notices:[{...rows[0],comparison:{status:'probably_same',changes:[]}}]}));
  assert.throws(()=>validateBundle({...base,schema_version:2}));
});

test('missing information stays explicit in comparisons',()=>{
  assert.equal(valueText(null),'Not stated in captured fields');
  assert.equal(valueText([]),'Not stated in captured fields');
  assert.equal(valueText(['A','B']),'A · B');
});
