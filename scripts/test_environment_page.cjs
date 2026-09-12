const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const data=JSON.parse(fs.readFileSync('research/environment.json'));
const nodes=new Map(),node=id=>nodes.get(id)||nodes.set(id,{value:id==='assetClass'?'stocks':id==='researchHorizon'?'2':'NVDA',innerHTML:'',textContent:'',addEventListener(ev,cb){this.change=cb}}).get(id);
vm.runInNewContext(fs.readFileSync('assets/environment-research.js','utf8'),{document:{getElementById:node},fetch:async()=>({ok:true,json:async()=>data}),console});
setImmediate(()=>{
 for(const cls of ['stocks','crypto'])for(const h of ['0','1','2']){
  node('assetClass').value=cls;node('researchHorizon').value=h;node('assetClass').change();
  const html=node('researchApp').innerHTML;assert(html.includes('개인')||html.includes('환경'));assert(!/NaN|Infinity|undefined/.test(html));assert(html.includes('기본 전망 자동 교체 안 함'));assert(html.includes('후반 평가'));assert(html.includes(cls==='stocks'?'NVDA':'BTC'));
 }
 console.log('Environment research page: both asset classes, all horizons, holdout distinction and missing-probability labels passed');
});
