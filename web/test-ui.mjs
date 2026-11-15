import assert from 'node:assert/strict';
import test from 'node:test';
import {createHash} from 'node:crypto';
import {csvCell,deadlineBrief,filterNotices,noticesCsv,pageWindow,readState,safeReleaseAsset,safeTedUrl,stateQuery,validateBundle,validateOperations,validatePointer,valueText,verifiedJson} from './ui-utils.mjs';

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
  for(const url of ['javascript:alert(1)','https://ted.europa.eu.evil.test/en/notice/-/detail/1','http://ted.europa.eu/en/notice/-/detail/1','https://user@ted.europa.eu/en/notice/-/detail/1','https://ted.europa.eu/redirect?to=evil.test','https://ted.europa.eu:444/en/notice/-/detail/1','https://ted.europa.eu/en/notice/-/detail/10-2026?redirect=bad','https://ted.europa.eu/en/notice/-/detail/10-2026#untrusted'])assert.equal(safeTedUrl(url),null,url);
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
  const state={q:'réseau & support <script>',country:'PRT',category:'72',comparison:'changed',notice:'10-2026',release:'a'.repeat(64)};
  assert.deepEqual(readState('?'+stateQuery(state)),state);
  assert.equal(stateQuery({q:'',country:'',category:'',comparison:'',notice:''}),'');
});

const hash='a'.repeat(64),otherHash='b'.repeat(64);
const asset={path:`releases/${hash}.json`,sha256:hash};

test('release pointers reject traversal, external assets and fingerprints without weakening to old data',()=>{
  assert.equal(validatePointer({schema_version:1,release:asset,operations:asset}).release,asset);
  for(const path of ['../data.json',`https://evil.example/releases/${hash}.json`,`releases/${hash}.json?other=1`,`releases/${hash}.json#x`,`releases/../${hash}.json`,`releases/${hash.toUpperCase()}.json`])assert.equal(safeReleaseAsset({...asset,path}),false,path);
  assert.equal(safeReleaseAsset({...asset,sha256:'xyz'}),false);
  assert.throws(()=>validatePointer({schema_version:1,release:asset}));
});

test('consumer refuses a single changed byte even when changed JSON remains valid',async()=>{
  const data=new TextEncoder().encode('{"notice_count":2}\n');
  const digest=createHash('sha256').update(data).digest('hex');
  assert.deepEqual(await verifiedJson(data.buffer,digest),{notice_count:2});
  const changed=new TextEncoder().encode('{"notice_count":3}\n');
  await assert.rejects(()=>verifiedJson(changed.buffer,digest),/fingerprint/);
  await assert.rejects(()=>verifiedJson(data.buffer,'not-a-hash'));
});

test('pagination covers a filtered population exactly once and bounds rendered rows',()=>{
  const input=Array.from({length:123},(_,i)=>i);
  const windows=[0,1,2].map(page=>pageWindow(input,page));
  assert.deepEqual(windows.flatMap(w=>w.items),input);
  assert.deepEqual(windows.map(w=>w.items.length),[50,50,23]);
  assert.equal(pageWindow(input,99).page,2);
  assert.equal(pageWindow([],7).page,0);
  assert.deepEqual(pageWindow([],7).items,[]);
  assert.throws(()=>pageWindow(input,0,1000));
});

test('deadline brief excludes superseded, missing and unsafe evidence instead of implying an open tender',()=>{
  const current={...rows[0],has_known_successor:false};
  const old={...rows[0],id:'9-2026',has_known_successor:true};
  const missing={...rows[0],id:'8-2026',comparison:{status:'compared',changes:[{field:'deadline',before:null,after:'2026-12-01'}]}};
  const unsafe={...rows[0],id:'7-2026',source_url:'javascript:alert(1)'};
  assert.deepEqual(deadlineBrief([old,missing,unsafe,current]).map(x=>x.notice.id),['10-2026']);
  assert.equal(deadlineBrief([current],0).length,0);
});

function validOperations() {
  const captured='2026-11-15T16:00:00Z';
  return {schema_version:1,capture_count:1,archive_capacity:{maximum:100,remaining:99},replay_verified:true,current_release_id:hash,code_sha256:otherHash,publication_days:['2026-11-09'],first_capture_at:captured,last_capture_at:captured,runs:[{sequence:1,mode:'backfill',publication_day:'2026-11-09',captured_at:captured,source_sha256:otherHash,release_id:hash,release_path:asset.path,release_sha256:hash,counts:{incoming:3,new:3,already_seen:0,retained:0,resolved_parents:0,total:3},duration_ms:2}]};
}

test('operating ledger preserves historical publication time separate from actual collection',()=>{
  const ops=validOperations();
  assert.equal(validateOperations(ops),ops);
  assert.equal(ops.runs[0].publication_day,'2026-11-09');
  assert.equal(ops.runs[0].captured_at,'2026-11-15T16:00:00Z');
});

test('operating ledger refuses reconciliation, ordering and release identity inconsistencies',()=>{
  for(const mutate of [o=>o.capture_count=2,o=>o.current_release_id=otherHash,o=>o.runs[0].counts.already_seen=1,o=>o.runs[0].sequence=2,o=>o.runs[0].mode='production',o=>o.last_capture_at='2026-11-14T00:00:00Z',o=>o.runs[0].duration_ms=-1,o=>o.replay_verified=false]){
    const ops=validOperations();mutate(ops);assert.throws(()=>validateOperations(ops));
  }
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

test('capacity and history conservation remain checked even for validly hashed JSON',()=>{
  for(const mutate of [o=>o.archive_capacity.remaining=100,o=>o.archive_capacity.maximum=true,o=>delete o.archive_capacity,o=>o.runs[0].counts.total=99,o=>o.runs[0].counts.retained=2,o=>o.runs[0].counts.resolved_parents=1,o=>o.publication_days=['2026-11-08']]) {
    const ops=validOperations();mutate(ops);assert.throws(()=>validateOperations(ops));
  }
});

test('a recapture reconciles new, seen-again and retained identities across editions',()=>{
  const ops=validOperations(),second=structuredClone(ops.runs[0]);
  second.sequence=2;second.mode='refresh';second.captured_at='2026-11-15T17:00:00Z';
  second.release_id=otherHash;second.release_path=`releases/${otherHash}.json`;second.release_sha256=otherHash;
  second.counts={incoming:2,new:1,already_seen:1,retained:2,resolved_parents:1,total:4};
  ops.runs.push(second);ops.capture_count=2;ops.archive_capacity.remaining=98;ops.last_capture_at=second.captured_at;ops.current_release_id=otherHash;
  assert.equal(validateOperations(ops),ops);
  second.counts.retained=1;second.counts.total=3;
  assert.throws(()=>validateOperations(ops));
});
