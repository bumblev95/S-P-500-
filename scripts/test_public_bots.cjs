'use strict';
const assert=require('node:assert/strict'),M=require('./public_bot_methods.cjs'),T=require('./trend_methods.cjs');
require('./research_public_bots.cjs');
const start=Date.UTC(2020,0,1),step=900000;
const rows=Array.from({length:24000},(_,i)=>{const price=100+i*.002+8*Math.sin(i/270);return {t:start+i*step,end:start+(i+1)*step-1,open:price,close:price+.01,high:price+.2,low:price-.2,volume:1};});
for(const method of M.METHODS){
 const prefix=M.signals(rows.slice(0,22000),method.id),full=M.signals(rows,method.id);
 assert(prefix.size>0,method.id+' needs warmup observations');
 for(const [at,q] of prefix)assert.deepEqual(full.get(at),q,'Future data changed '+method.id+' signal');
 for(const q of full.values())assert((q.at+1)%14400000===0&&q.atr>0&&q.holdBars===2880);
}
assert.deepEqual(M.signals(rows,'momentum14'),T.signals(rows,'momentum14'),'Existing comparison strategy changed');
const gapped=rows.filter((r,i)=>i!==16000),restart=rows[16016].t;
const gapSignals=M.signals(gapped,'rayner200');
assert(![...gapSignals.keys()].some(t=>t>=restart&&t<restart+1200*14400000),'200-day window bridged a data gap');
let state=M.supertrendStep(null,{high:101,low:99,close:100},null,10,3);
state=M.supertrendStep(state,{high:81,low:79,close:80},{close:100},10,3);assert.equal(state.direction,-1);
state=M.supertrendStep(state,{high:131,low:129,close:130},{close:80},10,3);assert.equal(state.direction,1);
console.log('Public methods: future-prefix invariance, complete 4h inputs, gap resets, Supertrend reversals, unchanged momentum baseline passed');
