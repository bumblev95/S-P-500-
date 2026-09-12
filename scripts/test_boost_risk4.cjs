'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),vm=require('node:vm'),crypto=require('node:crypto');
const F=require('./boost_risk4_forward.cjs'),E=require('./leverage_engine.cjs'),B=require('./build_boost_risk4.cjs');
const root=path.resolve(__dirname,'..'),start=Date.UTC(2026,0,1),step=900000,hour=3600000;
const candle=(i,price=100)=>({t:start+i*step,end:start+(i+1)*step-1,open:price,close:price,high:price+.2,low:price-.2,volume:100000});
const rows=Array.from({length:40},(_,i)=>candle(i)),market={crypto:{BTC:{frames:{'15m':rows},funding:[]}}};
const q={at:rows[15].end,indicatorAt:rows[15].end,side:'long',candidateSide:'long',price:100,stop:97,rank:1,trailLong:97,trailShort:103,modelScore:.2,modelPassed:true,featureReady:true,breakoutPassed:true,reason:'fixture'};
const feed=()=>q,observed=start+4*hour+7*60000;
let a=F.run(F.create(observed),market,observed,feed);assert.equal(a.cash,10000);assert.equal(a.positions.length,0);assert.equal(a.pending.length,1);
a=F.run(a,market,start+4*hour+37*60000,feed);assert.equal(a.positions.length,1);assert.equal(a.positions[0].entryAt,start+4*hour+15*60000);assert.equal(a.positions[0].leverage,5);assert(Math.abs(a.positions[0].riskBudget-400)<1e-8);
const again=F.run(a,market,start+4*hour+37*60000,feed);assert.deepEqual(again.events,a.events);assert.deepEqual(again.trades,a.trades);
// Delayed stop observations cannot act on earlier catch-up bars.
rows[31].low=98;rows[32].low=98;rows[33].low=98;
const trail=()=>({...q,at:rows[31].end,indicatorAt:rows[31].end,trailLong:99});
const late=F.run(a,market,start+8*hour+7*60000,trail);assert.equal(late.positions[0].stop,97);assert.equal(late.positions[0].pendingStop.price,99);assert.equal(late.trades.length,0);
const stopped=F.run(late,market,start+8*hour+37*60000,trail);assert.equal(stopped.trades.length,1);assert.equal(stopped.trades[0].exitAt,rows[33].end);
const reverse=()=>({...q,at:rows[31].end,indicatorAt:rows[31].end,side:null,exitLong:true});
const exitLate=F.run(a,market,start+8*hour+7*60000,reverse);assert.equal(exitLate.trades.length,0);const exited=F.run(exitLate,market,start+8*hour+37*60000,reverse);assert.equal(exited.trades[0].exitAt,rows[33].t);
assert.equal(exited.trades[0].exitReason,'14일 모멘텀 반전');
// A single queued candidate and no retrospective entries during a job gap.
const all={crypto:Object.fromEntries(['BTC','ETH','SOL'].map(s=>[s,{frames:{'15m':rows},funding:[]}]))};
const one=F.run(F.create(observed),all,observed,s=>({...q,rank:3-['BTC','ETH','SOL'].indexOf(s)}));assert.equal(one.pending.length,1);assert.equal(one.pending[0].symbol,'BTC');
const expired=F.run(one,all,start+9*hour,()=>({...q,side:null}));assert(expired.trades.every(t=>t.entryAt>=observed));
// The frozen research execution and the forward execution agree without scheduling delay.
const parityRows=rows.map(r=>({...r}));parityRows[18].low=96;
const parityMarket={crypto:{BTC:{frames:{'15m':parityRows},funding:[]}}},at=start+16*step;
const entered=F.run(F.create(at),parityMarket,at,feed),finished=F.run(entered,parityMarket,start+19*step,feed);
const prepared={features:{},events:{fixture:new Map([[15,{...q,side:1,exit:'swing',liquidityQty:500}]])}},data={start,symbols:{BTC:{rows:parityRows,offset:0,prepared,funding:new Map()}}};
const research=E.evaluate(data,{id:'fixture',kind:'스윙'},{id:'risk4',risk:.04},5,start+15*step,parityRows[18].end);
assert(Math.abs(F.equity(finished)-research.equity)<1e-8);assert(Math.abs(finished.trades[0].net-research.closed[0].net)<1e-8);
// Real hourly funding is normalized, debited once, and included in account reconciliation.
const fundedMarket={crypto:{BTC:{frames:{'15m':rows},funding:[{time:start+5*hour+3,rate:.001}]}}};
const funded=F.run(a,fundedMarket,start+5*hour+37*60000,feed);assert(Math.abs(funded.funding-a.positions[0].qty*100*.001)<1e-8);assert.equal(funded.estimatedFundingHours,0);
// Missing execution bars stop catch-up instead of fabricating fills.
const gap={crypto:{BTC:{frames:{'15m':rows.filter((r,i)=>i!==19)},funding:[]}}};const blocked=F.run(a,gap,start+6*hour,feed);assert.equal(blocked.executionBlocked,true);assert.equal(blocked.lastProcessed,rows[18].t);
const future=F.run(F.create(observed),market,observed,()=>({...q,at:start+9*hour,indicatorAt:start+9*hour}));assert.equal(future.pending.length,0);
// Builder creates one independent account, preserves its ledger and refuses state resets.
const dir=fs.mkdtempSync(path.join(os.tmpdir(),'risk4-forward-'));
fs.mkdirSync(path.join(dir,'leverage-lab'));fs.copyFileSync(path.join(root,'simulation/leverage-lab/latest.json'),path.join(dir,'leverage-lab/latest.json'));
const history=Array.from({length:4000},(_,i)=>candle(i,100+i*.012)),live={crypto:Object.fromEntries(['BTC','ETH','SOL'].map(s=>[s,{frames:{'15m':history},funding:[]}]))},now=history.at(-1).end+7*60000;
fs.writeFileSync(path.join(dir,'existing-account.json'),'preserve');const built=B.build(live,now,dir);assert.equal(built.forward.accounts.crypto.equity,10000);assert.equal(built.forward.accounts.crypto.trades.length,0);assert.equal(built.forward.createdAt,now);
assert.deepEqual(B.build(live,now,dir),built);assert.equal(fs.readFileSync(path.join(dir,'existing-account.json'),'utf8'),'preserve');
const ledger=path.join(dir,'boost-risk4/ledger');let previous=null;for(const file of fs.readdirSync(ledger).sort()){const {hash,...r}=JSON.parse(fs.readFileSync(path.join(ledger,file)));assert.equal(r.previousHash,previous);assert.equal(hash,crypto.createHash('sha256').update(JSON.stringify(r)).digest('hex'));previous=hash;}
const statePath=path.join(dir,'boost-risk4/state.json'),save=fs.readFileSync(statePath);fs.unlinkSync(statePath);assert.throws(()=>B.build(live,now,dir),/restore/);fs.writeFileSync(statePath,save);
const expPath=path.join(dir,'boost-risk4/experiment.json'),exp=fs.readFileSync(expPath);fs.writeFileSync(expPath,JSON.stringify({modified:true}));assert.throws(()=>B.build(live,now+step,dir),/Frozen/);assert.deepEqual(fs.readFileSync(statePath),save);fs.writeFileSync(expPath,exp);
assert.throws(()=>F.run({...a,profileVersion:'modified'},market,now,feed),/identity/);
async function testUI(){
 const nodes={},document={getElementById(id){return nodes[id]||(nodes[id]={innerHTML:'',addEventListener(){}});},querySelectorAll(){return [];}},data={generatedAt:now,momentumBoost5xRisk4:built,notes:[],preview:{crypto:{}}},source=fs.readFileSync(path.join(root,'assets/simulation-page.js'),'utf8'),view=fs.readFileSync(path.join(root,'assets/boost-risk4-view.js'),'utf8');
 const load=async(query='')=>{const context=vm.createContext({console,document,window:{},location:{search:query},history:{replaceState(){}},URLSearchParams,fetch:async()=>({ok:true,json:async()=>data})});vm.runInContext(view,context);assert.equal(typeof context.window.BoostRisk4View.render(data,'forward'),'string');vm.runInContext(source,context);await new Promise(resolve=>setImmediate(resolve));return nodes.simulationApp.innerHTML;};
 let html=await load();assert(html.includes('새 기본 모의운용'),html);assert(html.includes('$10,000.00'));assert(html.includes('$400.00'));assert(html.includes('현재 포지션 · 0 / 1개'));assert(!html.includes('424.64%'));assert(!html.includes('undefined')&&!html.includes('NaN'));
 html=await load('?profile=momentumBoost5xRisk4&mode=replay');assert(html.includes('424.64%'));assert(html.includes('현재 모의계좌 잔고와 별개'));
 delete data.momentumBoost5xRisk4;html=await load();assert(html.includes('첫 자동 갱신'));
 console.log('PASS risk4 forward timing, stops/exit observations, idempotence, one position, research parity, hourly funding, gaps, immutable ledger/model identity and default/replay UI.');
}
testUI().catch(e=>{console.error(e);process.exitCode=1});
