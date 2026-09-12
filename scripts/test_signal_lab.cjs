'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const root=path.resolve(__dirname,'..'),data=JSON.parse(fs.readFileSync(path.join(root,'simulation/signal-tournament/latest.json'))),source=fs.readFileSync(path.join(root,'assets/signal-lab.js'),'utf8');
async function load(fail=false){
 const elements=new Map(),buttons=[];const element=id=>{if(!elements.has(id))elements.set(id,{innerHTML:'',querySelectorAll(){buttons.length=0;for(const m of this.innerHTML.matchAll(/data-pick="([^"]+)"/g))buttons.push({dataset:{pick:m[1]}});return buttons;}});return elements.get(id);};
 const context={document:{getElementById:element},fetch:async()=>{if(fail)throw Error('offline');return {ok:true,json:async()=>data};},console,Number,Date,Math,Infinity};
 vm.runInNewContext(source,context);await new Promise(resolve=>setImmediate(resolve));return {elements,buttons,element};
}
(async()=>{
 const ui=await load(),html=()=>ui.element('signalLab').innerHTML;
 assert(html().includes('454회'));assert(html().includes('62.77%'));assert(html().includes('9.63%'));assert(html().includes('-2.26%'));
 assert(!html().includes('NaN')&&!html().includes('undefined'));
 assert(html().includes('원본 봇의 수익률이나 실제 계좌 실적이 아닙니다'));
 ui.element('labSort').onchange({target:{value:'return'}});assert(html().includes('value="return" selected'));
 ui.element('labOnly').onchange({target:{checked:true}});assert(html().includes('type="checkbox" checked'));
 ui.element('labOnly').onchange({target:{checked:false}});ui.buttons.find(b=>b.dataset.pick==='squeeze_ema').onclick();assert(html().includes('Squeeze 해제 · EMA 200 방향 · 상세'));
 const failed=await load(true);assert(failed.element('signalLab').innerHTML.includes('불러오지 못했습니다'));
 for(const r of data.fixed){assert.equal(r.cap,1);assert(r.maxHeld<=1);assert(Number.isFinite(r.estimatedFundingHours)&&r.estimatedFundingHours>=0);if(r.estimatedFundingHours)assert(r.warnings.some(w=>w.includes('펀딩 누락')));}
 assert.equal(data.fixed.length,32);assert.equal(data.yearly.length,6);assert.equal(data.evaluations,454);
 for(const selected of data.walkForward.selected)assert(selected.validationEnd<Date.UTC(selected.year,0,1));
 const expected=JSON.parse(fs.readFileSync(path.join(root,'simulation/momentum-boost/research.json')));
 const boost=data.fixed.find(r=>r.method==='momentum_boost');assert(Math.abs(boost.return-expected.results.boost.return)<1e-12);assert(Math.abs(boost.maxDrawdown-expected.results.boost.maxDrawdown)<1e-12);
 console.log('PASS: published report values, filtering/sorting/selection/failure UI, funded data, chronology and previous boosting baseline exact parity.');
})();
