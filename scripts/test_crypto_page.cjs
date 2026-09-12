const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),guide=require('../assets/crypto.js');
const V=require('../assets/market-visuals.js');
const F=require('../assets/spot-forecast.js');
for(const input of [{circulating:60,total:80,maximum:100},{circulating:60,total:80,maximum:null},{circulating:80.000001,total:80,maximum:null}]){
 const parts=V.supplyParts(input);assert(parts);assert(Math.abs(parts.segments.reduce((s,r)=>s+r.value,0)-parts.total)<1e-8);assert(parts.segments.every(r=>r.value>=0));
 assert(!/NaN|Infinity/.test(V.supply(input)));
}
assert.equal(V.supplyParts({circulating:90,total:80}),null);
assert.equal(V.supplyParts({circulating:null,total:80}),null);
const data=JSON.parse(fs.readFileSync('crypto/latest.json'));
let count=0;
for(const e of Object.values(data.coins))for(const mode of ['center','sample']){
 const full=guide.path(e,365,mode);if(!full.length)continue;
 for(const h of [30,120])assert.deepEqual(guide.path(e,h,mode),full.slice(0,h+1));
 for(const h of [30,120,365]){const x=F.simulate(e);assert(x.samples.every(p=>p.length===366));assert(new Set(x.samples.map(p=>p[h])).size>1);}
 assert.equal(full[0].base,e.spot.price);
 assert(full.every(q=>q.base>0&&q.bear<=q.bull&&Object.values(q).every(Number.isFinite)));count++;
}
const nodes=new Map(),node=id=>nodes.get(id)||nodes.set(id,{innerHTML:'',textContent:'',value:'BTC',addEventListener(){}}).get(id);
const ctx={document:{getElementById:node,querySelectorAll:()=>[]},window:{MarketVisuals:require('../assets/market-visuals.js'),SpotForecast:F,innerWidth:390,scrollTo(){}},fetch:async()=>({ok:true,json:async()=>data}),setInterval(){},console,Intl,Date};
vm.runInNewContext(fs.readFileSync('assets/crypto.js','utf8'),ctx);
setImmediate(()=>{const html=node('app').innerHTML;assert(html.includes('SPOT'));assert(!html.includes('PERPETUAL'));assert(html.includes('futures.html'));assert(html.includes('유통'));assert(html.includes('연구 전망 자료 없음'));assert(html.includes('가능 경로 3개'));assert(!/NaN|undefined|Infinity/.test(html));console.log(count+' common crypto paths and mobile-sized page render passed');});

// Stale or misaligned learned forecasts cannot be promoted to an AI direction.
const currentDate=new Date().toISOString().slice(0,10),coin={spot:{price:100},spotHistory:[{date:currentDate}],modelGeneratedAt:new Date().toISOString(),spotModel:{asOf:currentDate,anchor:100,predictions:{30:{status:'eligible',forecast:{base:120,logReturn:Math.log(1.2)},reasons:[]}}}};
assert(F.inspect(coin,30).eligible);coin.spot.price=130;assert(!F.inspect(coin,30).eligible);coin.spot.price=100;coin.modelGeneratedAt='2020-01-01';assert(!F.inspect(coin,30).eligible);

const smallChart=guide.chart(data.coins.SKR,365,'sample');assert(!/font-size="13">0<\/text>/.test(smallChart),'Small token axis must not round positive prices to zero');

const raw=JSON.parse(fs.readFileSync('crypto/learned.json'));
const studied={...data.coins.BTC,spotModel:raw.coins.BTC,modelGeneratedAt:raw.generatedAt};
const annual=F.inspect(studied,365);assert(annual.forecast,'A valid withheld forecast remains visible');assert.equal(annual.forecast.base,raw.coins.BTC.predictions['365'].forecast.base);
const study=F.simulate(studied);assert.equal(study.anchor,raw.coins.BTC.anchor);assert.equal(study.asOf,raw.coins.BTC.asOf);assert(Math.abs(study.bands[365].ai/annual.forecast.base-1)<1e-10);
assert(guide.chart(studied,365,'center').includes('stroke-width="2.6"'));
assert(guide.chart(studied,365,'center').includes('기준일'));
coin.modelGeneratedAt=new Date().toISOString();coin.spotModel.predictions[30].status='withheld';assert(!F.inspect(coin,30).eligible);assert(F.inspect(coin,30).forecast);
coin.spotModel.predictions[30].forecast.base=-1;assert.equal(F.inspect(coin,30).forecast,null);
