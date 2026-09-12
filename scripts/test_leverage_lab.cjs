'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),crypto=require('node:crypto');
const root=path.resolve(__dirname,'..'),data=JSON.parse(fs.readFileSync(path.join(root,'simulation/leverage-lab/latest.json'))),source=fs.readFileSync(path.join(root,'assets/leverage-lab.js'),'utf8'),key=r=>r.method+':'+r.policy+':'+r.leverage;
async function load(fail=false){const elements=new Map(),buttons=[];const element=id=>{if(!elements.has(id))elements.set(id,{innerHTML:'',querySelectorAll(){buttons.length=0;for(const m of this.innerHTML.matchAll(/data-pick="([^"]+)"/g))buttons.push({dataset:{pick:m[1]}});return buttons;}});return elements.get(id);};vm.runInNewContext(source,{document:{getElementById:element},fetch:async()=>{if(fail)throw Error('offline');return {ok:true,json:async()=>data};},console,Number,Date,Math,Infinity});await new Promise(resolve=>setImmediate(resolve));return {element,buttons};}
(async()=>{
 const ui=await load(),html=()=>ui.element('leverageLab').innerHTML;
 assert(html().includes('1,630회'));assert(html().includes('771.12%'));assert(html().includes('424.64%'));assert(html().includes('186.45%'));assert(html().includes('실제 계좌 실적이나 15년 선물 백테스트가 아닙니다'));
 assert(!html().includes('NaN')&&!html().includes('undefined'));
 ui.element('levKind').onchange({target:{value:'단타'}});assert.equal(ui.buttons.length,60);
 ui.element('levFilter').onchange({target:{value:'10'}});assert.equal(ui.buttons.length,30);
 ui.element('levOnly').onchange({target:{checked:true}});assert.equal(ui.buttons.length,0);
 ui.element('levOnly').onchange({target:{checked:false}});ui.element('levKind').onchange({target:{value:'all'}});ui.element('levFilter').onchange({target:{value:'all'}});
 ui.buttons.find(b=>b.dataset.pick==='boost_swing:risk4:5').onclick();ui.element('levCapital').onchange({target:{value:'25000'}});assert(html().includes('$1,000'));
 assert((await load(true)).element('leverageLab').innerHTML.includes('불러오지 못했습니다'));
 assert.equal(data.fixed.length,108);assert.equal(new Set(data.fixed.map(key)).size,108);assert.equal(data.yearly.length,6);assert.equal(data.walkForward.selected.length,5);
 const all=[...data.fixed,...data.yearly.flatMap(y=>y.results)];
 for(const r of all){assert([5,10].includes(r.leverage));assert(Number.isFinite(r.return)&&r.return>=-1);assert(r.maxDrawdown>=0&&r.maxDrawdown<=1);assert(r.averageEntryMargin<=.9+1e-9);assert(r.estimatedFundingPayments>=0);assert(Math.abs(r.averageEntryExposure-r.averageEntryMargin*r.leverage)<1e-8);const p=data.policies.find(p=>p.id===r.policy);if(p.risk)assert(r.averageEntryRisk<=p.risk+1e-8);else assert(r.averageEntryMargin<=p.margin+1e-8);}
 let equity=10000;for(const s of data.walkForward.selected){assert(s.validationEnd<Date.UTC(s.year,0,1));assert.equal(s.validationYear,s.year-1);equity*=1+s.return;assert(Math.abs(equity-s.equity)<1e-6);}
 assert(Math.abs(equity-data.walkForward.equity)<1e-6);
 for(const [file,expected] of Object.entries(data.sourceHashes)){const actual=crypto.createHash('sha256').update(fs.readFileSync(path.join(root,'scripts',file))).digest('hex');assert.equal(actual,expected,'Source provenance: '+file);}
 const old=JSON.parse(fs.readFileSync(path.join(root,'simulation/signal-tournament/latest.json')));assert.equal(data.marketHash,old.marketHash);assert.equal(data.scoreHash,old.scoreHash);
 console.log('PASS leverage report, capital calculator, strategy/leverage filters, selection, loading failure,108 combinations, allocation bounds, chronological balance carry and input/source hashes.');
})();
