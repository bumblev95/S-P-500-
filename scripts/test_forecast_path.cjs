const assert=require('node:assert/strict'),fs=require('fs'),path=require('../assets/forecast-path.js');
const data=JSON.parse(fs.readFileSync('forecasts/latest.json')),ml=JSON.parse(fs.readFileSync('ml/latest.json'));
let checked=0,turns=0;
for(const e of Object.values(data.stocks))for(const h of [21,84,252]){
  const p=e.predictions?.[h];if(!p)continue;
  for(const f of [p,ml.stocks?.[e.symbol]?.predictions?.[h]?.forecast].filter(Boolean)){
    const a=path.build(e,f,h),b=path.build(e,f,h),center=path.build(e,f,h,'center');
    assert.deepEqual(a,b);assert.equal(a.points.length,h+1);
    assert(Math.abs(a.points[0].base/f.anchor-1)<1e-10);
    assert(Math.abs(center.points.at(-1).base/f.base-1)<1e-10);
    if(a.sampled)assert.notEqual(a.points.at(-1).base,center.points.at(-1).base);
    assert(a.points.every(q=>Object.values(q).every(Number.isFinite)&&q.base>0));
    assert.equal(path.build({...e,history:[]},f,h).sampled,false);checked++;
    const ds=a.points.slice(1).map((q,i)=>Math.sign(q.base-a.points[i].base));
    if(ds.includes(1)&&ds.includes(-1))turns++;
  }
}
console.log(`${checked} paths: deterministic, finite, anchored and missing-data safe; ${turns} have both rises and falls`);
const guide=require('../assets/learned-guide.js');let shared=0;
for(const e of Object.values(data.stocks)){
  const forecasts=guide.allPeriods(ml,e);if(![21,84,252].every(h=>forecasts[h]))continue;
  for(const mode of ['center','sample']){
    const full=path.build(e,forecasts[252],252,mode,forecasts);
    for(const h of [21,84])assert.deepEqual(path.build(e,forecasts[h],h,mode,forecasts).points,full.points.slice(0,h+1));
    for(const h of [21,84,252]){if(mode==='center')assert.equal(full.points[h].base,forecasts[h].base);else if(full.sampled)assert.notEqual(full.points[h].base,forecasts[h].base);}
    assert(full.points.every(q=>q.base>0&&q.bear<=q.bull&&Object.values(q).every(Number.isFinite)));shared++;
  }
}
console.log(`${shared} shared paths: exact cross-horizon prefixes and separate AI targets / unconstrained sample endpoints passed`);
