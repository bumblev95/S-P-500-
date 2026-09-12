'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),vm=require('node:vm');
const P=require('./paper_engine.cjs'),B=require('./build_momentum.cjs');
const start=Date.UTC(2026,0,1),step=900000,bar=(i,open=100,high=101,low=99.5,close=100)=>({t:start+i*step,end:start+(i+1)*step-1,open,high,low,close,volume:1});
function settle(side='long',high=107,low=99){
 const rows=Array.from({length:24},(_,i)=>bar(i)),observed=start+16*step+7*60000;
 const q={side,at:rows[15].end,indicatorAt:rows[15].end,price:100,stop:side==='long'?97.5:102.5,target:side==='long'?106:94,atr:1,rank:1,pattern:'momentum14',reason:'fixture',holdBars:2880,trailLong:97.5,trailShort:102.5};
 const market={crypto:{BTC:{frames:{'15m':rows},funding:[]}}},provider=()=>q;
 let a=P.run(P.create('crypto',observed,'momentum14Target6'),market,{mode:'forward',now:observed,provider});
 assert.equal(a.cash,10000);assert.equal(a.positions.length,0);assert.equal(a.pending[0].target,q.target);
 rows[17]=bar(17,100,high,low,100);
 a=P.run(a,market,{mode:'forward',now:start+18*step+7*60000,provider});
 assert.equal(a.trades[0].entryAt,start+17*step,'No retrospective fills');
 assert.equal(a.trades.length,1);assert.equal(a.positions.length,0);
 assert.ok(Math.abs(P.equity(a)-10000-a.trades[0].net)<1e-8,'Costs and equity reconcile');
 const repeat=P.run(a,market,{mode:'forward',now:start+18*step+7*60000,provider});assert.deepEqual(repeat.events,a.events);
 return a.trades[0];
}
assert.equal(settle().exitReason,'익절 · 6 ATR 목표');
assert.equal(settle('short',101,93).exitReason,'익절 · 6 ATR 목표');
assert.equal(settle('long',107,97).exitReason,'손절 · 같은 봉 목표 동시 도달');
assert.equal(settle('short',103,93).exitReason,'손절 · 같은 봉 목표 동시 도달');
assert.equal(P.MOMENTUM.targets,undefined,'Original account still has no target exit');
for(const key of ['risk','maxOpenRisk','fee','slip','signalTtl','observedTrend','fundingReserveHours'])assert.deepEqual(P.MOMENTUM_TARGET6[key],P.MOMENTUM[key]);

const history=Array.from({length:4000},(_,i)=>bar(i,100+i*.01,101+i*.01,99+i*.01,100+i*.01));
const market={crypto:{BTC:{frames:{'15m':history},funding:[]}}};
const old=B.providers(market),next=B.providers(market,'momentum14Target6'),q=old.forward('BTC',history.slice(-260)),n=next.forward('BTC',history.slice(-260));
assert.equal(n.side,'long');assert.equal(n.target,n.price+6*n.atr);
assert.deepEqual({...n,target:null},q,'Only target changes; entries, stops and controls stay identical');
const cut=history.length-20,partial={crypto:{BTC:{frames:{'15m':history.slice(0,cut)},funding:[]}}};
assert.deepEqual(B.providers(partial,'momentum14Target6').forward('BTC',history.slice(cut-260,cut)),next.forward('BTC',history.slice(cut-260,cut)),'Future bars cannot alter prior signals');
assert.equal(next.forward('BTC',[{...history.at(-1),end:history.at(-1).end+14400000}]).side,null);

const dir=fs.mkdtempSync(path.join(os.tmpdir(),'momentum-target6-test-')),now=history.at(-1).end+7*60000;
B.build(market,now,dir);const oldState=fs.readFileSync(path.join(dir,'momentum/state.json'),'utf8'),oldReplay=fs.readFileSync(path.join(dir,'momentum/replay.json'),'utf8');
const built=B.build(market,now,dir,'momentum14Target6'),fwd=built.forward.accounts.crypto;
assert.equal(fwd.equity,10000);assert.equal(fwd.trades.length,0);assert.equal(fwd.profileVersion,'momentum14-target6-forward-v1');
assert.equal(fwd.positions.length,0);assert.equal(fwd.pending.length,1);assert.equal(fwd.pending[0].createdAt,now);
assert.equal(fs.readFileSync(path.join(dir,'momentum/state.json'),'utf8'),oldState);assert.equal(fs.readFileSync(path.join(dir,'momentum/replay.json'),'utf8'),oldReplay);
const targetDir=path.join(dir,'momentum-target6'),replay=fs.readFileSync(path.join(targetDir,'replay.json'),'utf8'),ledger=fs.readdirSync(path.join(targetDir,'ledger'));
B.build(market,now,dir,'momentum14Target6');
assert.deepEqual(fs.readdirSync(path.join(targetDir,'ledger')),ledger);assert.equal(fs.readFileSync(path.join(targetDir,'replay.json'),'utf8'),replay);
for(let i=4000;i<4004;i++)history.push(bar(i,140,141,139,140));
const after=B.build(market,history.at(-1).end+7*60000,dir,'momentum14Target6');
assert.equal(after.forward.accounts.crypto.positions.length,1);assert.equal(after.forward.accounts.crypto.positions[0].target,fwd.pending[0].target,'Target stays fixed after entry');
assert.equal(fs.readFileSync(path.join(dir,'momentum/state.json'),'utf8'),oldState);
const crypto=require('node:crypto');let priorHash=null;
for(const name of fs.readdirSync(path.join(targetDir,'ledger')).sort()){
 const {hash,...record}=JSON.parse(fs.readFileSync(path.join(targetDir,'ledger',name)));assert.equal(record.previousHash,priorHash);assert.equal(hash,crypto.createHash('sha256').update(JSON.stringify(record)).digest('hex'));priorHash=hash;
}

async function uiTest(){
 const nodes={},document={getElementById(id){return nodes[id]||(nodes[id]={innerHTML:'',addEventListener(){}})},querySelectorAll(){return []}};
 const data={generatedAt:now,config:P.CONFIG,momentum:built,momentumTarget6:built,preview:{crypto:{}},notes:[]};
 const source=fs.readFileSync(path.join(__dirname,'../assets/simulation-page.js'),'utf8');
 vm.runInNewContext(source,{document,location:{search:'?profile=momentum14Target6'},URLSearchParams,history:{replaceState(){}},fetch:async()=>({ok:true,json:async()=>data})});
 await new Promise(resolve=>setImmediate(resolve));
 assert.ok(nodes.simulationApp.innerHTML.includes('기존 · 모멘텀 + 6 ATR'));assert.ok(nodes.simulationApp.innerHTML.includes('momentum-target6/state.json'));assert.ok(nodes.simulationApp.innerHTML.includes('$10,000.00'));
 delete data.momentumTarget6;
 vm.runInNewContext(source,{document,location:{search:'?profile=momentum14Target6'},URLSearchParams,history:{replaceState(){}},fetch:async()=>({ok:true,json:async()=>data})});
 await new Promise(resolve=>setImmediate(resolve));assert.ok(nodes.simulationApp.innerHTML.includes('첫 자동 갱신'));
 console.log('PASS: long/short targets, stop priority, observed fills, frozen targets, unchanged old profile, independent account/ledger, prefix invariance and new default UI');
}
uiTest().catch(e=>{console.error(e);process.exitCode=1});
