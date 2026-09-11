const assert=require('node:assert/strict'),fs=require('fs'),path=require('../assets/forecast-path.js');
const data=JSON.parse(fs.readFileSync('forecasts/latest.json')),ml=JSON.parse(fs.readFileSync('ml/latest.json'));
let checked=0,turns=0;
for(const e of Object.values(data.stocks))for(const h of [21,84,252]){
  const p=e.predictions?.[h];if(!p)continue;
  for(const f of [p,ml.stocks?.[e.symbol]?.predictions?.[h]?.forecast].filter(Boolean)){
    const a=path.build(e,f,h),b=path.build(e,f,h),center=path.build(e,f,h,'center');
    assert.deepEqual(a,b);assert.equal(a.points.length,h+1);
    assert(Math.abs(a.points[0].base/f.anchor-1)<1e-10);
    assert(Math.abs(a.points.at(-1).base/f.base-1)<1e-10);
    assert.equal(a.points.at(-1).base,center.points.at(-1).base);
    assert(a.points.every(q=>Object.values(q).every(Number.isFinite)&&q.base>0));
    assert.equal(path.build({...e,history:[]},f,h).sampled,false);checked++;
    const ds=a.points.slice(1).map((q,i)=>Math.sign(q.base-a.points[i].base));
    if(ds.includes(1)&&ds.includes(-1))turns++;
  }
}
console.log(`${checked} paths: deterministic, finite, anchored and missing-data safe; ${turns} have both rises and falls`);
