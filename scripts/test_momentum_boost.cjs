'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),crypto=require('node:crypto'),vm=require('node:vm');
const B=require('./momentum_boost.cjs'),S=require('./build_momentum_boost.cjs'),P=require('./paper_engine.cjs'),OLD=require('./build_momentum.cjs');
const model=B.loadModel(),fixture=JSON.parse(fs.readFileSync(path.join(__dirname,'fixtures/momentum-boost-parity.json')));
assert.equal(fixture.modelSha256,B.MODEL_SHA256);
for(const r of fixture.rows)assert.ok(Math.abs(B.predict(model,r.x)-r.score)<1e-12,'JavaScript and sklearn predictions differ');
assert.equal(B.predict(model,[NaN]),null);
const q={at:1,price:100,atr:1,target:null,reason:'fixture',candidateSide:'long',side:'long',breakoutPassed:true,modelPassed:true,modelScore:.1,featureReady:true,exitLong:false,trailLong:97.5,trailShort:102.5};
assert.equal(B.apply(q,'momentumBoostOne').side,'long');
assert.equal(B.apply({...q,modelPassed:false,modelScore:.0999},'momentumBoostOne').side,null);
assert.equal(B.apply({...q,modelPassed:false},'momentumBreakoutOne').side,'long','No-ML control must ignore ML');
assert.equal(B.apply({...q,breakoutPassed:false},'momentumBoostOne').side,null);
assert.equal(B.apply({...q,modelPassed:false,exitLong:true},'momentumBoostOne').exitLong,true,'Rejected entries must not suppress exits');
assert.equal(B.apply({...q,modelPassed:false},'momentumBoostOne').trailLong,97.5);
for(const id of ['momentumBoostOne','momentumBreakoutOne'])assert.equal(P.config(P.create('crypto',1,id)).maxPositions,1);
assert.equal(P.config(P.create('crypto',1,'momentumBreakoutThree')).maxPositions,3);
assert.equal(P.MOMENTUM.maxPositions,3);assert.equal(P.MOMENTUM_TARGET6.maxPositions,3);

const start=Date.UTC(2026,0,1),step=900000;
const bar=(i,price=100)=>({t:start+i*step,end:start+(i+1)*step-1,open:price,close:price,high:price+.2,low:price-.2,volume:1});
function onePosition(profile,side='long',gap=false){
 const observed=start+16*step+7*60000,rows=Array.from({length:25},(_,i)=>bar(i));
 const market={crypto:Object.fromEntries(['BTC','ETH','SOL'].map(s=>[s,{frames:{'15m':rows.map(r=>({...r}))},funding:[]}]))};
 if(gap)market.crypto.BTC.frames['15m'][17]=bar(17,103);
 const provider=s=>({...q,at:rows[15].end,indicatorAt:rows[15].end,side,candidateSide:side,stop:side==='long'?97.5:102.5,holdBars:2880,pattern:'momentum14',rank:3-['BTC','ETH','SOL'].indexOf(s),modelId:model.id,modelScore:s==='BTC'?.11:.8});
 let a=P.run(P.create('crypto',observed,profile),market,{mode:'forward',now:observed,provider});
 assert.equal(a.positions.length,0);assert.equal(P.equity(a),10000);assert.equal(a.pending.length,3);
 a=P.run(a,market,{mode:'forward',now:start+18*step+7*60000,provider});
 assert.equal(a.positions.length,profile==='momentumBreakoutThree'?3:1);
 assert.ok(a.positions.every(p=>p.entryAt===start+17*step&&p.entryAt>=observed),'Never fill before observed order');
 assert.equal(a.positions[0].symbol,gap?'ETH':'BTC','Preserve historical rank and next-price fallback');
 assert.equal(a.positions[0].modelId,model.id);assert.equal(a.positions[0].target,null);
 const repeat=P.run(a,market,{mode:'forward',now:start+18*step+7*60000,provider});assert.deepEqual(repeat.events,a.events);
}
onePosition('momentumBoostOne');onePosition('momentumBoostOne','short');onePosition('momentumBoostOne','long',true);onePosition('momentumBreakoutThree');

const history=Array.from({length:4000},(_,i)=>bar(i,100+i*.012));
const market={crypto:Object.fromEntries(['BTC','ETH','SOL'].map(s=>[s,{frames:{'15m':history.map(r=>({...r}))},funding:[]}]))};
const full=B.mapsFor(market,model),cut=3808,part={crypto:Object.fromEntries(Object.entries(market.crypto).map(([s,v])=>[s,{...v,frames:{'15m':v.frames['15m'].slice(0,cut)}}]))};
const partial=B.mapsFor(part,model);
for(const symbol of ['BTC','ETH','SOL'])for(const [at,sig] of partial[symbol])assert.deepEqual(sig,full[symbol].get(at),'Future candles changed an earlier indicator');
const feed=B.providers(market),last=history.at(-1),now=last.end+7*60000;
assert.equal(feed.forward('BTC',[{...last,end:last.end+14400000}]).side,null);
const dir=fs.mkdtempSync(path.join(os.tmpdir(),'boost-study-'));
OLD.build(market,now,dir);OLD.build(market,now,dir,'momentum14Target6');
const oldFiles=['momentum/state.json','momentum/replay.json','momentum-target6/state.json','momentum-target6/replay.json'];
const before=oldFiles.map(n=>fs.readFileSync(path.join(dir,n),'utf8'));
const built=S.build(market,now,dir);
for(const spec of B.PROFILES){
 const a=built.accounts[spec.id].forward.accounts.crypto;
 assert.equal(a.equity,10000);assert.equal(a.positions.length,0);assert.equal(a.trades.length,0);assert.equal(a.createdAt,now);
}
oldFiles.forEach((n,i)=>assert.equal(fs.readFileSync(path.join(dir,n),'utf8'),before[i]));
const studyDir=path.join(dir,'momentum-boost'),snapshot=JSON.stringify(built);
assert.equal(JSON.stringify(S.build(market,now,dir)),snapshot,'Same observation must be idempotent');
const frozen=B.PROFILES.map(s=>fs.readFileSync(path.join(studyDir,s.directory,'replay.json'),'utf8'));
for(const v of Object.values(market.crypto))for(let i=4000;i<4008;i++)v.frames['15m'].push(bar(i,100+i*.012));
S.build(market,history.at(-1).end+8*step+7*60000,dir);
for(const [i,spec] of B.PROFILES.entries()){
 assert.equal(fs.readFileSync(path.join(studyDir,spec.directory,'replay.json'),'utf8'),frozen[i]);
 let prior=null;
 for(const name of fs.readdirSync(path.join(studyDir,spec.directory,'ledger')).sort()){
  const {hash,...r}=JSON.parse(fs.readFileSync(path.join(studyDir,spec.directory,'ledger',name)));assert.equal(r.previousHash,prior);assert.equal(hash,crypto.createHash('sha256').update(JSON.stringify(r)).digest('hex'));prior=hash;
 }
}
let prior=null;
for(const name of fs.readdirSync(path.join(studyDir,'decisions')).sort()){
 const {hash,...r}=JSON.parse(fs.readFileSync(path.join(studyDir,'decisions',name)));assert.equal(r.previousHash,prior);assert.equal(hash,crypto.createHash('sha256').update(JSON.stringify(r)).digest('hex'));assert.ok(r.observations.every(q=>q.indicatorAt<=r.recordedAt));prior=hash;
}
const stateFile=path.join(studyDir,'boost-one/state.json'),saved=fs.readFileSync(stateFile);fs.unlinkSync(stateFile);assert.throws(()=>S.build(market,now,dir),/restore account records/);fs.writeFileSync(stateFile,saved);

async function uiTest(){
 const nodes={},document={getElementById(id){return nodes[id]||(nodes[id]={innerHTML:'',addEventListener(){}})},querySelectorAll(){return []}};
 const data={generatedAt:now,config:P.CONFIG,...built.accounts,momentumBoostStudy:built.study,preview:{crypto:{}},notes:[]};
 const source=fs.readFileSync(path.join(__dirname,'../assets/simulation-page.js'),'utf8');
 const render=async query=>{vm.runInNewContext(source,{document,location:{search:query},URLSearchParams,history:{replaceState(){}},fetch:async()=>({ok:true,json:async()=>data})});await new Promise(resolve=>setImmediate(resolve));return nodes.simulationApp.innerHTML;};
 let html=await render('?profile=momentumBoostOne');assert.ok(html.includes('이전 · 동시 1종목 + ML'));assert.ok(html.includes('0 / 1개 보유'));assert.ok(html.includes('같은 날 시작한 세 계좌'));assert.ok(html.includes('ML 필터 점수'));
 html=await render('?profile=momentumBreakoutThree');assert.ok(html.includes('0 / 3개 보유'));
 delete data.momentumBoostOne;html=await render('?profile=momentumBoostOne');assert.ok(html.includes('첫 자동 갱신'));assert.ok(html.includes('기존 6 ATR 계좌 보기'));
 console.log('PASS: sklearn parity, entry gates and controls, one-position cap, recorded-time fills, fallback rank, immutable study/decision ledgers, model locks, default UI and position counts');
}
uiTest().catch(e=>{console.error(e);process.exitCode=1});
