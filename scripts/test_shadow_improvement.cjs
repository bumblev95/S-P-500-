'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),cp=require('node:child_process');
const E=require('./shadow_evidence.cjs'),G=require('./shadow_gates.cjs'),S=require('./shadow_improvement.cjs'),B=require('./momentum_boost.cjs'),P=require('./paper_engine.cjs'),Original=require('./build_momentum_boost.cjs');
const ROOT=path.resolve(__dirname,'..'),copy=x=>JSON.parse(JSON.stringify(x));let count=0;
function test(name,run){run();count++;console.log('PASS '+name);}
function write(root,file,value){fs.mkdirSync(path.dirname(path.join(root,file)),{recursive:true});fs.writeFileSync(path.join(root,file),JSON.stringify(value,file==='simulation/market.json'?(k,v)=>k.startsWith('_')?undefined:v:undefined));}
function snapshot(root,directory='simulation'){
 const out={};function visit(dir){for(const e of fs.readdirSync(path.join(root,dir),{withFileTypes:true})){const name=dir+'/'+e.name;if(name.startsWith('simulation/self-improvement'))continue;if(e.isDirectory())visit(name);else out[name]=E.bytesHash(fs.readFileSync(path.join(root,name)));}}visit(directory);return out;
}
const evidence=E.loadEvidence(ROOT);
test('current immutable inputs and pinned identity',()=>{
 assert.equal(evidence.pinnedModel.sha256,B.MODEL_SHA256);assert.ok(evidence.decisions.length>=95);
 assert.ok(evidence.accounts['boost-one'].trades.length>=2);
 for(const t of evidence.accounts['boost-one'].trades){assert.ok(t.entryAt>=t.orderCreatedAt);assert.ok(t.recordedAt>=t.exitAt);assert.ok(t.decisionHash&&t.entryRecordHash&&t.exitRecordHash);}
});
test('requested 2026-10-01 decision cannot enter on model gate alone',()=>{
 const file='simulation/momentum-boost/decisions/1790835023912-55292d4a88c7.json';
 const r=E.readFile(ROOT,file).value;for(const q of r.observations){assert.equal(q.modelPassed,true);assert.equal(q.breakoutPassed,false);assert.equal(q.side,null);assert.equal(B.apply(q,'momentumBoostOne').side,null);}
});
test('126-day failure and 252-day insufficiency stay contextual, never trading permission',()=>{
 const {value:a}=E.readFile(ROOT,'ml/adaptive-summary.json'),context=E.forecastContext(a);
 assert.equal(context.usedForTrading,false);
 // Freeze the exact cited regression; newer summaries remain allowed.
 const cited={model:'fixture',horizons:{126:{comparison:{status:'research',chosen:'regimeBlend',passed:false,checks:{average:false,consistency:false,direction:false},improvementVsOriginal:-.0019327440312792987,liveForecastChanged:false}},252:{comparison:{status:'insufficient',passed:false,reason:'보정 후 독립 검증 시점 부족'}}}};
 const frozen=E.forecastContext(cited);assert.equal(frozen.horizons[126].passed,false);assert.equal(frozen.horizons[252].status,'insufficient');assert.equal(frozen.horizons[126].improvementVsOriginal,-.0019327440312792987);
});

const temp=fs.mkdtempSync(path.join(os.tmpdir(),'shadow-improvement-'));
try{
 for(const f of [...S.RUNTIME,'simulation/momentum-boost/model.json','ml/adaptive-summary.json']){fs.mkdirSync(path.dirname(path.join(temp,f)),{recursive:true});fs.copyFileSync(path.join(ROOT,f),path.join(temp,f));}
 cp.execFileSync('git',['init','-q'],{cwd:temp});cp.execFileSync('git',['-c','user.name=Test','-c','user.email=test@example.invalid','commit','-q','--allow-empty','-m','Synthetic fixture'],{cwd:temp});
 const start=Date.UTC(2026,0,1),STEP=900000;
 const bar=(i,price=100+i*.012)=>({t:start+i*STEP,end:start+(i+1)*STEP-1,open:price,close:price,high:price+.01,low:price-.01,volume:100});
 const rows=Array.from({length:4000},(_,i)=>bar(i)),funding=Array.from({length:1200},(_,i)=>({time:start+i*3600000,rate:0}));
 const market={schemaVersion:1,generatedAt:rows.at(-1).end+7*60000,errors:[],crypto:Object.fromEntries(['BTC','ETH','SOL'].map(s=>[s,{frames:{'15m':copy(rows)},funding:copy(funding)}]))};
 Original.build(market,market.generatedAt,path.join(temp,'simulation'));write(temp,'simulation/market.json',market);
 const now=market.generatedAt+1,c=S.register({root:temp,thresholdR:.25,now});
 test('register fresh paired cash accounts and new immutable candidate only',()=>{
  assert.equal(c.baseModelSha256,B.MODEL_SHA256);assert.equal(c.source.closedTrades.length,0);assert.equal(c.thresholdR,.25);
  const chain=S.readObservations(temp,c);assert.equal(chain.records.length,1);assert.equal(chain.accounts.incumbent.cash,10000);assert.equal(chain.accounts.candidate.cash,10000);assert.equal(chain.accounts.incumbent.trades.length,0);
  assert.throws(()=>S.register({root:temp,thresholdR:.25,now}),/already exists/);
  assert.throws(()=>S.register({root:temp,thresholdR:.05,now:now+1}),/stricter/);
  assert.throws(()=>S.register({root:temp,thresholdR:NaN,now:now+1}),/finite/);
  assert.throws(()=>S.readCandidate(temp,'../momentum-boost'),/Invalid shadow version/);
 });
 let report;
 test('real engine update keeps original files and uses recorded decision gates',()=>{
  const before=snapshot(temp);report=S.update({root:temp,version:c.version,now:now+1});assert.deepEqual(snapshot(temp),before);
  const a=S.readObservations(temp,c).accounts;
  assert.equal(a.incumbent.positions.length,0);assert.equal(a.candidate.positions.length,0);
  assert.equal(a.incumbent.pending[0].symbol,'BTC');assert.equal(a.candidate.pending[0].symbol,'SOL');
  assert.equal(report.status,'insufficient');assert.equal(report.promotionCandidate,false);assert.equal(report.pinnedModelChanged,false);assert.equal(report.automaticPromotion,false);
  assert.deepEqual(S.update({root:temp,version:c.version,now:now+1}),report);
 });
 test('append forward fills after recording, preserve candidate version and all past data',()=>{
  for(const source of Object.values(market.crypto))for(let i=4000;i<4004;i++)source.frames['15m'].push(bar(i));
  market.generatedAt=market.crypto.BTC.frames['15m'].at(-1).end+7*60000;
  Original.build(market,market.generatedAt,path.join(temp,'simulation'));write(temp,'simulation/market.json',market);
  const before=snapshot(temp),prior=S.readObservations(temp,c),rawCandidate=fs.readFileSync(path.join(temp,S.BASE,c.version,'candidate.json'));
  S.update({root:temp,version:c.version,now:market.generatedAt});assert.deepEqual(snapshot(temp),before);
  const next=S.readObservations(temp,c);for(const key of ['incumbent','candidate']){
   assert.equal(next.accounts[key].positions.length,1);assert.ok(next.accounts[key].positions[0].entryAt>=next.accounts[key].positions[0].orderCreatedAt);
   for(const field of ['events','trades','curve'])assert.deepEqual(next.accounts[key][field].slice(0,prior.accounts[key][field].length),prior.accounts[key][field]);
  }
  assert.equal(next.accounts.incumbent.positions[0].symbol,'BTC');assert.equal(next.accounts.candidate.positions[0].symbol,'SOL');
  assert.deepEqual(fs.readFileSync(path.join(temp,S.BASE,c.version,'candidate.json')),rawCandidate);
 });
 test('immutable close snapshots and exact net economics survive later runs',()=>{
  for(const source of Object.values(market.crypto)){source.frames['15m'].push({...bar(4004),low:140});}
  market.generatedAt=market.crypto.BTC.frames['15m'].at(-1).end+7*60000;
  Original.build(market,market.generatedAt,path.join(temp,'simulation'));write(temp,'simulation/market.json',market);
  S.update({root:temp,version:c.version,now:market.generatedAt});const chain=S.readObservations(temp,c);
  for(const a of Object.values(chain.accounts)){assert.equal(a.trades.length,1);const t=a.trades[0];assert.ok(Math.abs(t.net-(t.gross-t.entryFee-t.exitFee-t.funding+t.isolatedLossAdjustment))<1e-9);}
  assert.equal(E.loadEvidence(temp,c.source.immutableFiles).accounts['boost-one'].trades.length,1);
 });
 test('tampered or truncated source chains fail closed',()=>{
  const name=Object.keys(c.source.immutableFiles).find(f=>f.includes('/decisions/')),file=path.join(temp,name),saved=fs.readFileSync(file),v=JSON.parse(saved);
  v.observations[0].modelScore=99;fs.writeFileSync(file,JSON.stringify(v));assert.throws(()=>E.loadEvidence(temp,c.source.immutableFiles),/hash\/link/);fs.writeFileSync(file,saved);
  fs.unlinkSync(file);assert.throws(()=>E.loadEvidence(temp,c.source.immutableFiles),/hash\/link|missing/);fs.writeFileSync(file,saved);
  assert.throws(()=>E.assertAppendOnly({'old.json':'abc'},{'old.json':'def'}),/changed or disappeared/);
 });
 test('rehashed source rewrite still fails the version checkpoint',()=>{
  const isolated=fs.mkdtempSync(path.join(os.tmpdir(),'shadow-chain-'));const directory='records';fs.mkdirSync(path.join(isolated,directory));
  const body={recordedAt:1,previousHash:null,value:1},hash=E.sha(body),name=directory+'/1-'+hash.slice(0,12)+'.json';write(isolated,name,{...body,hash});
  const first=E.readChain(isolated,directory);fs.unlinkSync(path.join(isolated,name));const changed={...body,value:2},h=E.sha(changed);write(isolated,directory+'/1-'+h.slice(0,12)+'.json',{...changed,hash:h});
  assert.throws(()=>E.assertAppendOnly(first.files,E.readChain(isolated,directory).files),/changed or disappeared/);fs.rmSync(isolated,{recursive:true});
 });
 test('missing shadow records never silently reset an existing version',()=>{
  const dir=path.join(temp,S.BASE,c.version,'observations'),backup=dir+'-backup';fs.renameSync(dir,backup);
  assert.throws(()=>S.update({root:temp,version:c.version,now:market.generatedAt+1}),/restore immutable records/);fs.renameSync(backup,dir);
  const first=fs.readdirSync(dir).sort()[0],raw=fs.readFileSync(path.join(dir,first));fs.unlinkSync(path.join(dir,first));assert.throws(()=>S.readObservations(temp,c),/hash\/link/);fs.writeFileSync(path.join(dir,first),raw);
 });
 test('candidate/runtime/model alteration and future timestamps cannot continue an account',()=>{
  const runtime=path.join(temp,S.RUNTIME[0]),saved=fs.readFileSync(runtime);fs.appendFileSync(runtime,'\n// changed\n');assert.throws(()=>S.readCandidate(temp,c.version),/NEW version/);fs.writeFileSync(runtime,saved);
  const modelFile=path.join(temp,'simulation/momentum-boost/model.json'),model=fs.readFileSync(modelFile);fs.appendFileSync(modelFile,' ');assert.throws(()=>E.loadEvidence(temp),/pinned input model hash/);fs.writeFileSync(modelFile,model);
  const candidateFile=path.join(temp,S.BASE,c.version,'candidate.json'),raw=fs.readFileSync(candidateFile),changed=JSON.parse(raw);changed.thresholdR=.01;fs.writeFileSync(candidateFile,JSON.stringify(changed));assert.throws(()=>S.readCandidate(temp,c.version),/hash mismatch/);fs.writeFileSync(candidateFile,raw);
  assert.throws(()=>S.update({root:temp,version:c.version,now:now-1}),/clock went backward/);
  const old=market.generatedAt;market.generatedAt+=1000000;write(temp,'simulation/market.json',market);assert.throws(()=>S.update({root:temp,version:c.version,now:old+1}),/Future input/);market.generatedAt=old;write(temp,'simulation/market.json',market);
 });
 test('missing, stale and revised data block qualification',()=>{
  assert.equal(S.dataQuality(market,{},new Set(),market.generatedAt).passed,true);
  assert.equal(S.dataQuality({...market,errors:['collector failure']},{},new Set(),market.generatedAt).passed,false);
  assert.equal(S.dataQuality(market,{},new Set(),market.generatedAt+86400000).passed,false);
  assert.equal(S.dataQuality(market,{},new Set(['BTC:fixture']),market.generatedAt).passed,false);
  assert.equal(S.dataQuality(market,{candidate:{estimatedFundingHours:1}},new Set(),market.generatedAt).passed,false);
 });
 test('an unreproducible original decision cannot supply an invented entry',()=>{
  const e=E.loadEvidence(temp),last=e.decisions.at(-1);for(const q of last.observations)q.price*=2;
  const feed=S.providers(e,market,c,market.generatedAt);for(const symbol of ['BTC','ETH','SOL'])assert.equal(feed.incumbent(symbol,market.crypto[symbol].frames['15m']).side,null);
  assert.ok(feed.mismatches.size>0);
 });
}finally{fs.rmSync(temp,{recursive:true,force:true});}

// Fabricated outcomes below test gate logic only. They are never registered in
// the repository, interpreted as real trades or offered as a profitable model.
const at=Date.UTC(2026,0,1),cfg=P.config(P.create('crypto',at,'momentumBoostOne')),candidate={version:'synthetic',registeredAt:at};
function trade(i,net,origin=at){
 const entryAt=origin+i*G.DAY+2*3600000,entry=100,qty=1,entryFee=entry*qty*cfg.fee,exit=(entry+net+entryFee)/(1-cfg.fee),exitFee=exit*qty*cfg.fee;
 return {id:'synthetic:'+origin+':'+i,symbol:'ETH',side:'long',signalAt:entryAt-3600000,orderCreatedAt:entryAt-1800000,entryAt,exitAt:entryAt+3600000,recordedAt:entryAt+3600001,entry,exit,qty,entryFee,exitFee,funding:0,riskBudget:100,net,leverage:3};
}
function account(proposed){
 const a=P.create('crypto',at,'momentumBoostOne');a.startedAt=at;let equity=10000;a.curve=[{at,equity,exposure:0}];
 for(let i=0;i<120;i++){const t=trade(i,proposed?20:i%2?-5:25);a.trades.push(t);equity+=t.net;a.curve.push({at:at+(i+1)*G.DAY-1,equity,exposure:0});}
 a.cash=equity;a.fees=a.trades.reduce((s,t)=>s+t.entryFee+t.exitFee,0);a.slippage=a.trades.reduce((s,t)=>s+G.slippage(t,cfg),0);return a;
}
const accounts={incumbent:account(false),candidate:account(true)},history=Array.from({length:30},(_,i)=>trade(i,1,at-32*G.DAY)),observations=Array.from({length:121},(_,i)=>({recordedAt:at+i*G.DAY}));
test('all gates required; successful synthetic screen is still shadow-only',()=>{
 const result=G.evaluate(candidate,history,accounts,observations,cfg);assert.equal(result.status,'promotion_candidate',JSON.stringify(result));assert.ok(Object.values(result.gates).every(Boolean));
 for(const k of ['automaticPromotion','defaultStrategyChanged','pinnedModelChanged','liveTrading'])assert.equal(result[k],false);
 assert.equal(G.evaluate(candidate,history,accounts,observations,cfg,{integrity:false}).promotionCandidate,false);
 assert.equal(G.evaluate(candidate,history,accounts,observations,cfg,{completeData:false}).promotionCandidate,false);
});
test('purging uses publication time, embargo and complete simultaneous signal groups',()=>{
 const fresh=trade(0,100,at-10*G.DAY);fresh.recordedAt=at+G.DAY;
 const overlapping=trade(1,100,at-10*G.DAY);overlapping.exitAt=at+G.DAY;
 const groupMate={...fresh,id:'same-time-other-symbol',symbol:'BTC',recordedAt:at-2*G.DAY};
 const wf=G.purgedWalkForward(candidate,[...history,fresh,overlapping,groupMate],accounts,at+120*G.DAY,cfg);
 for(const t of [fresh,overlapping,groupMate])assert.ok(!wf.folds[0].trainingIds.includes(t.id));
 assert.ok(wf.folds[1].trainingIds.includes(fresh.id));
 const later=G.purgedWalkForward(candidate,history,accounts,at+125*G.DAY,cfg);assert.equal(later.folds[0].testEnd,wf.folds[0].testEnd,'Later assessments must not move old test boundaries');
});
test('forward common period includes skips and never compares only shared winning trades',()=>{
 const altered=copy(accounts);altered.candidate.createdAt--;assert.equal(G.evaluate(candidate,history,altered,observations,cfg).promotionCandidate,false);
 const shorter=copy(accounts);shorter.candidate.curve.pop();assert.equal(G.evaluate(candidate,history,shorter,observations,cfg).gates.matchedForwardSample,false);
 const delayed=copy(accounts);delayed.incumbent.startedAt=delayed.candidate.startedAt=at+100*G.DAY;assert.equal(G.matchedSample(candidate,delayed,observations).forwardDays,20);
 const backfill=copy(accounts);backfill.candidate.trades[0].orderCreatedAt=at-1;assert.equal(G.matchedSample(candidate,backfill,observations).passed,false);
});
test('insufficient trade count, short time and insufficient training never pass',()=>{
 const tiny=copy(accounts);tiny.candidate.trades=tiny.candidate.trades.slice(0,99);assert.equal(G.evaluate(candidate,history,tiny,observations,cfg).gates.minimumTrades,false);
 assert.equal(G.evaluate(candidate,history,accounts,observations.slice(0,30),cfg).promotionCandidate,false);
 assert.equal(G.evaluate(candidate,history.slice(0,2),accounts,observations,cfg).gates.purgedWalkForward,false);
});
test('fees/slippage stress is incremental and weak economic improvement fails',()=>{
 const t=trade(0,1);assert.ok(Math.abs(G.tradeNet(t,cfg,true)-(t.net-t.entryFee-t.exitFee-G.slippage(t,cfg)))<1e-12);
 const equal=copy(accounts);equal.candidate=copy(equal.incumbent);assert.equal(G.evaluate(candidate,history,equal,observations,cfg).gates.costIncludedImprovement,false);
 const bad=copy(accounts);bad.candidate.trades[0].funding=NaN;assert.equal(G.evaluate(candidate,history,bad,observations,cfg).promotionCandidate,false);
});
test('improved return cannot excuse worse drawdown, exposure, funding uncertainty or liquidation',()=>{
 const drawdown=copy(accounts);drawdown.candidate.curve[20].equity=8000;assert.equal(G.evaluate(candidate,history,drawdown,observations,cfg).gates.drawdownNotWorse,false);
 const exposure=copy(accounts);exposure.candidate.curve[20].exposure=20000;assert.equal(G.evaluate(candidate,history,exposure,observations,cfg).gates.riskNotWorse,false);
 const budget=copy(accounts);budget.candidate.trades[0].riskBudget=300;assert.equal(G.evaluate(candidate,history,budget,observations,cfg).gates.riskNotWorse,false,'Intrabar closed positions still carried risk');
 for(const [k,v] of [['estimatedFundingHours',1],['isolatedLossAdjustment',1],['incompleteExecution',true]]){const bad=copy(accounts);bad.candidate[k]=v;assert.equal(G.evaluate(candidate,history,bad,observations,cfg).gates.riskNotWorse,false);}
 const bad=copy(accounts);bad.candidate.curve.at(-1).equity+=1000;assert.equal(G.evaluate(candidate,history,bad,observations,cfg).gates.costIncludedImprovement,false,'Invented equity cannot qualify');
});
console.log('PASS '+count+' shadow self-improvement regression groups');
