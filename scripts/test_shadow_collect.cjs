'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),cp=require('node:child_process');
const C=require('./shadow_collect.cjs'),S=require('./shadow_improvement.cjs'),E=require('./shadow_evidence.cjs'),Original=require('./build_momentum_boost.cjs');
const copy=x=>JSON.parse(JSON.stringify(x)),symbols=['BTC','ETH','SOL'];
const END=1791302399999,NOW=END+960335,GENERATED=Date.parse('2026-10-06T16:14:55.710Z');
const bar=t=>({t,end:t+C.STEP-1,open:100,high:100.01,low:99.99,close:100,volume:100});
const rows=Array.from({length:4000},(_,i)=>bar(END+1-(4000-i)*C.STEP));
const funding=Array.from({length:1001},(_,i)=>({time:rows[0].t+i*3600000,rate:0})).filter(r=>r.time<GENERATED);
const market={schemaVersion:1,generatedAt:new Date(GENERATED).toISOString(),stocks:{SPY:{rows:[],checkedDate:'2026-10-06'}},errors:[],
 crypto:Object.fromEntries(symbols.map(s=>[s,{frames:{'15m':copy(rows)},funding:copy(funding),errors:[],revisions:[]}]))};
const raw=m=>Buffer.from(JSON.stringify(m));
function fresh(at=NOW){
 const m=copy(market);m.generatedAt=new Date(at).toISOString();
 for(const s of symbols)m.crypto[s].frames['15m'].push(bar(END+1));return m;
}
function hashes(root){
 const out={};function visit(dir){for(const item of fs.readdirSync(path.join(root,dir),{withFileTypes:true})){
  const file=dir+'/'+item.name;if(item.isDirectory())visit(file);else out[file]=E.bytesHash(fs.readFileSync(path.join(root,file)));
 }}visit('simulation');return out;
}
function unchanged(root,before){const after=hashes(root);for(const [f,h] of Object.entries(before))assert.equal(after[f],h,'Existing file changed: '+f);}
let count=0;
async function test(name,run){await run();count++;console.log('PASS '+name);}
async function main(){
 await test('exact 960335 > 900000 regression authorizes recollection, never execution',()=>{
  const q=S.dataQuality(market,{},new Set(),NOW);
  assert.equal(q.passed,false);for(const s of symbols){assert.equal(q.executionPrices[s].ageMs,960335);assert.equal(q.executionPrices[s].maxAgeMs,900000);}
  assert.equal(C.boundaryRetry(market,NOW),true);
  assert.equal(S.dataQuality(market,{},new Set(),END+900000).passed,true);
  assert.equal(S.dataQuality(market,{},new Set(),END+900001).passed,false);
  assert.equal(S.dataQuality(fresh(),{},new Set(),NOW+5000).passed,true);
 });
 await test('only a fresh collection in the final two minutes can retry in the next first two minutes',()=>{
  const boundary=END+C.STEP+1,m=copy(market);
  m.generatedAt=new Date(boundary-C.BOUNDARY_WINDOW).toISOString();assert.equal(C.boundaryRetry(m,boundary),true);
  m.generatedAt=new Date(boundary-C.BOUNDARY_WINDOW-1).toISOString();assert.equal(C.boundaryRetry(m,boundary),false);
  assert.equal(C.boundaryRetry(market,boundary+C.BOUNDARY_WINDOW-1),true);
  assert.equal(C.boundaryRetry(market,boundary+C.BOUNDARY_WINDOW),false);
  m.generatedAt=new Date(NOW+1).toISOString();assert.equal(C.boundaryRetry(m,NOW),false);
  m.generatedAt=new Date(NOW).toISOString();assert.equal(C.boundaryRetry(m,NOW),false,'A newly stamped old candle is not a boundary snapshot');
 });
 await test('28-minute old, missing, gapped, revised and errored data cannot request a retry',()=>{
  assert.equal(C.boundaryRetry(market,END+28*60000),false);
  for(const change of [m=>m.errors.push('collector failure'),m=>m.crypto.BTC.errors.push('funding unavailable'),
   m=>m.crypto.BTC.revisions.push(rows[0].t),m=>m.crypto.BTC.frames['15m'].splice(3,1),m=>m.crypto.BTC.frames['15m']=[],
   m=>m.crypto.BTC.frames['15m'][0].close=200]){
   const m=copy(market);change(m);assert.equal(C.boundaryRetry(m,NOW),false);
  }
 });
 await test('refreshed inputs cannot rewrite candles/funding/stocks or include future information',()=>{
  assert.doesNotThrow(()=>C.assertExtension(market,fresh(),NOW+1));
  for(const change of [m=>m.crypto.BTC.frames['15m'][0].close=101,m=>m.crypto.BTC.frames['15m'].shift(),
   m=>m.crypto.BTC.funding[0].rate=.01,m=>m.stocks.SPY.checkedDate='2026-10-07',
   m=>m.generatedAt=new Date(NOW+2).toISOString(),m=>m.generatedAt=new Date(GENERATED-1).toISOString(),
   m=>m.crypto.BTC.frames['15m'].push(bar(END+1+C.STEP)),m=>m.crypto.BTC.funding.push({time:NOW,rate:0})]){
   const m=fresh();change(m);assert.throws(()=>C.assertExtension(market,m,NOW+1),/Refresh|snapshot/);
  }
 });
 const temp=fs.mkdtempSync(path.join(os.tmpdir(),'shadow-boundary-tests-')),base=path.join(temp,'base');fs.mkdirSync(base);
 try{
  for(const f of [...S.RUNTIME,'simulation/momentum-boost/model.json','ml/adaptive-summary.json']){
   fs.mkdirSync(path.dirname(path.join(base,f)),{recursive:true});fs.copyFileSync(path.join(S.ROOT,f),path.join(base,f));
  }
  cp.execFileSync('git',['init','-q'],{cwd:base});cp.execFileSync('git',['-c','user.name=Test','-c','user.email=test@example.invalid','commit','-q','--allow-empty','-m','Synthetic boundary fixture'],{cwd:base});
  Original.build(copy(market),GENERATED,path.join(base,'simulation'));fs.writeFileSync(path.join(base,'simulation/market.json'),raw(market));
  const candidate=S.register({root:base,now:GENERATED+1}),version=candidate.version;
  let serial=0;
  const isolated=()=>{const root=path.join(temp,'case-'+serial++);fs.cpSync(base,root,{recursive:true});return root;};
  await test('fresh input executes without requesting any network refresh',async()=>{
   const root=isolated(),before=hashes(root);let calls=0;
   const reports=await C.collect({root,clock:()=>GENERATED+2,refresh:()=>{calls++;throw Error('Unexpected network');}});
   assert.equal(calls,0);assert.equal(reports.length,1);assert.equal(reports[0].gates.completeData,true);unchanged(root,before);
   assert(!fs.existsSync(path.join(root,C.INPUTS)));
  });
  await test('real boundary retry archives exact bytes, preserves all old records and uses the actual retry time',async()=>{
   const root=isolated(),before=hashes(root),original=fs.readFileSync(path.join(root,'simulation/market.json'));let at=NOW,calls=0;
   const refreshed=raw(fresh(NOW+1000));
   const reports=await C.collect({root,version,clock:()=>at,refresh:()=>{calls++;at+=5000;return refreshed;}});
   assert.equal(calls,1);assert.equal(reports[0].gates.completeData,true);assert.equal(reports[0].gates.matchedForwardSample,true);
   assert.equal(reports[0].promotionCandidate,false);unchanged(root,before);
   assert.deepEqual(fs.readFileSync(path.join(root,'simulation/market.json')),original);
   const chain=S.readObservations(root,candidate),record=chain.records.at(-1),hash=E.bytesHash(refreshed);
   assert.equal(chain.records.length,2);assert.equal(record.recordedAt,NOW+5000);
   assert.equal(record.inputs.marketSha256,hash);assert.equal(record.inputs.marketGeneratedAt,NOW+1000);
   assert.deepEqual(fs.readFileSync(path.join(root,C.INPUTS,hash+'.json')),refreshed);
   assert.equal(record.inputs.quality.executionPrices.BTC.ageMs,65335);
   for(const account of Object.values(chain.accounts)){
    assert.equal(account.startedAt,record.recordedAt);assert(account.events.every(e=>e.recordedAt>=record.recordedAt));
    assert(account.trades.every(t=>t.entryAt>=t.orderCreatedAt));
   }
   assert.deepEqual(S.runtimeHashes(root),candidate.runtimeHashes);assert.equal(S.audit(root).versions[0].runtimeCompatible,true);
  });
  await test('unchanged provider candles wait once and only append after a genuinely fresh response',async()=>{
   const root=isolated(),before=hashes(root);let at=NOW,calls=0,waits=0;
   const reports=await C.collect({root,clock:()=>at,refresh:()=>{
    calls++;at+=1000;assert.deepEqual(hashes(root),before);
    const m=calls===1?copy(market):fresh(at);m.generatedAt=new Date(at).toISOString();return raw(m);
   },wait:async delay=>{assert.equal(delay,C.RETRY_DELAY);waits++;at+=delay;}});
   assert.equal(calls,2);assert.equal(waits,1);assert.equal(reports[0].gates.completeData,true);unchanged(root,before);
   assert.equal(S.readObservations(root,candidate).records.at(-1).recordedAt,at);
  });
  await test('persistent stale responses exhaust the bounded retry without any append',async()=>{
   const root=isolated(),before=hashes(root);let at=NOW,calls=0,waits=0;
   await assert.rejects(()=>C.collect({root,clock:()=>at,refresh:()=>{calls++;at+=1000;const m=copy(market);m.generatedAt=new Date(at).toISOString();return raw(m);},
    wait:async delay=>{waits++;at+=delay;}}),/refresh exhausted/);
   assert.equal(calls,C.RETRY_LIMIT);assert.equal(waits,C.RETRY_LIMIT-1);assert.deepEqual(hashes(root),before);
  });
  await test('refresh timeout and provider errors fail closed without a second request or an append',async()=>{
   for(const kind of ['timeout','error','deadline']){
    const root=isolated(),before=hashes(root);let at=NOW,calls=0;
    await assert.rejects(()=>C.collect({root,clock:()=>at,refresh:({timeoutMs})=>{
     calls++;assert.equal(timeoutMs,C.RETRY_BUDGET);
     if(kind==='timeout')throw Error('Provider timeout');
     if(kind==='deadline'){at+=C.RETRY_BUDGET;return raw(fresh());}
     const m=fresh();m.errors.push('Provider unavailable');return raw(m);
    }}),/timeout|not ready|exhausted/);
    assert.equal(calls,1);assert.deepEqual(hashes(root),before);
   }
  });
  await test('genuinely old input and future timestamps stay blocked without recollecting',async()=>{
   for(const kind of ['old','future']){
    const root=isolated();let calls=0;const m=copy(market);
    if(kind==='future'){m.generatedAt=new Date(NOW+1).toISOString();fs.writeFileSync(path.join(root,'simulation/market.json'),raw(m));}
    const before=hashes(root),reports=await C.collect({root,clock:()=>kind==='old'?END+28*60000:NOW,refresh:()=>{calls++;throw Error('Unexpected network');}});
    assert.equal(calls,0);assert.equal(reports[0].status,'blocked');assert.match(reports[0].reason,kind==='old'?/stale execution/:/Future input/);
    assert.deepEqual(hashes(root),before);
   }
  });
  await test('source checkpoint tampering is rejected before fetching or writing any input',async()=>{
   const root=isolated(),file=Object.keys(candidate.source.immutableFiles).find(f=>f.includes('/decisions/'));
   fs.appendFileSync(path.join(root,file),'\n');const before=hashes(root);let calls=0;
   await assert.rejects(()=>C.collect({root,clock:()=>NOW,refresh:()=>{calls++;return raw(fresh());}}),/changed or disappeared/);
   assert.equal(calls,0);assert.deepEqual(hashes(root),before);
  });
  await test('invalid refreshed bytes cannot alter old records or create input evidence',async()=>{
   for(const kind of ['revision','future','unfinished']){
    const root=isolated(),before=hashes(root),m=fresh();
    if(kind==='revision')m.crypto.BTC.frames['15m'][0].close=101;
    if(kind==='future')m.generatedAt=new Date(NOW+1).toISOString();
    if(kind==='unfinished')m.crypto.BTC.frames['15m'].push(bar(END+1+C.STEP));
    await assert.rejects(()=>C.collect({root,clock:()=>NOW,refresh:()=>raw(m)}),/Refresh|snapshot/);
    assert.deepEqual(hashes(root),before);
   }
  });
  await test('a candle expiring during preparation remains blocked at execution and the public file is restored',async()=>{
   const root=isolated(),before=hashes(root),bytes=raw(fresh()),name=path.join(root,C.INPUTS,E.bytesHash(bytes)+'.json');
   const reports=await C.collect({root,clock:()=>fs.existsSync(name)?NOW+C.STEP:NOW,refresh:()=>bytes});
   assert.equal(reports[0].status,'blocked');assert.match(reports[0].reason,/stale execution prices/);unchanged(root,before);
   assert.equal(S.readObservations(root,candidate).records.length,1);
  });
  await test('paused runtime skips acquisition and explicit paused-version updates fail without migration',async()=>{
   const root=isolated();fs.appendFileSync(path.join(root,S.RUNTIME[0]),'\n// Synthetic incompatible runtime\n');
   const before=hashes(root);let calls=0;const options={root,clock:()=>NOW,refresh:()=>{calls++;throw Error('Unexpected network');}};
   const all=await C.collect(options);assert.equal(all[0].status,'paused');
   const targeted=await C.collect({...options,version});assert.equal(targeted[0].status,'blocked');assert.match(targeted[0].reason,/NEW version/);
   assert.equal(calls,0);assert.deepEqual(hashes(root),before);
  });
  await test('input archive cannot overwrite a hash path or follow a symlink',()=>{
   const root=isolated(),bytes=raw(fresh()),name=C.archiveInput(root,bytes),before=hashes(root);
   assert.equal(C.archiveInput(root,bytes),name);assert.deepEqual(hashes(root),before);
   fs.writeFileSync(path.join(root,name),'altered');assert.throws(()=>C.archiveInput(root,bytes),/Immutable/);
   fs.unlinkSync(path.join(root,name));fs.symlinkSync(path.join(root,'simulation/market.json'),path.join(root,name));
   assert.throws(()=>C.archiveInput(root,bytes),/Immutable/);
  });
 }finally{fs.rmSync(temp,{recursive:true,force:true});}
 await test('current frozen version remains compatible and the two older versions remain paused',()=>{
  const versions=S.audit().versions;
  assert(versions.filter(v=>!v.runtimeCompatible).length>=2);
  assert.equal(versions.find(v=>v.version==='shadow-threshold-v1-1790996520188-ac0b896d93c8').runtimeCompatible,true);
 });
 console.log('PASS '+count+' shadow collection regression groups');
}
main().catch(e=>{console.error(e);process.exitCode=1;});
