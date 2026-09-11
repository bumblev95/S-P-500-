const assert=require('node:assert/strict'),J=require('../assets/trade-journal.js');
const now=Date.now(),day=new Date(now).toISOString().slice(0,10),yesterday=new Date(now-86400000).toISOString().slice(0,10);
const p={version:1,id:'one',symbol:'NVDA',horizon:84,type:'held',entry:100,quantity:2,stop:90,target:120,reason:'Original thesis',savedAt:yesterday+'T23:59:59Z',snapshot:{asOf:yesterday,price:100}};
assert.equal(J.validate(p),p);
for(const edit of [{quantity:-1},{entry:NaN},{stop:Infinity},{symbol:'<script>'},{reason:' '},{savedAt:'bad'},{savedAt:2026},{symbol:['NVDA']},{id:''}])assert.throws(()=>J.validate({...p,...edit}));
assert.doesNotThrow(()=>J.validate({...p,stop:105})); // A held position may have a trailing stop above cost.
assert.throws(()=>J.validate({...p,type:'watch',stop:105}));
const e={symbol:'NVDA',price:110,fresh:true,asOf:day,history:[]};
const copy=JSON.stringify(p);
assert.equal(J.assessment(p,e).profit,20);
assert.equal(J.assessment(p,{...e,fresh:false}).profit,null);
assert.match(J.assessment(p,{...e,price:85}).label,/이탈/);
assert.match(J.assessment(p,{...e,history:[{date:day,close:85}]}).label,/이탈/);
assert.doesNotMatch(J.assessment(p,{...e,history:[{date:yesterday,close:85}]}).label,/이탈/);
assert.equal(J.assessment(p,{...e,history:[{date:yesterday,close:50}]}).profit,null);
assert.equal(JSON.stringify(p),copy); // Latest analysis must not mutate the saved plan.
const live=JSON.parse(require('node:fs').readFileSync('ml/live-results.json'));
assert.match(J.livePanel(live,'NVDA',252),/실제 발표한 예측/);
assert(!J.livePanel(live,'NVDA',252).includes('0.0%'));
// Exercise render and both mode handlers without a browser.
const callbacks={},classes={};
const host={innerHTML:'',closest:()=>({classList:{toggle:(k,v)=>classes[k]=v}}),querySelector:s=>({addEventListener:(event,fn)=>callbacks[s+event]=fn}),querySelectorAll:()=>['entry','held'].map(mode=>({dataset:{mode},addEventListener:(event,fn)=>callbacks[mode]=fn}))};
global.document={getElementById:()=>host};
J.mount({e,plan:{stop:95,target1:130},h:84,ai:{eligible:false},live});
assert.match(host.innerHTML,/계획 파일 불러오기/);
callbacks.held();assert.equal(classes.holdingMode,true);assert.match(host.innerHTML,/내 보유 계획/);
callbacks.entry();assert.equal(classes.holdingMode,false);
console.log('Plan validation, frozen criteria, stale/split guards, modes and pending score display passed');
