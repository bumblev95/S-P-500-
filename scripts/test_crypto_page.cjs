const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),guide=require('../assets/crypto.js');
const data=JSON.parse(fs.readFileSync('crypto/latest.json'));
let count=0;
for(const e of Object.values(data.coins))for(const mode of ['center','sample']){
 const full=guide.path(e,365,mode);if(!full.length)continue;
 for(const h of [30,120])assert.deepEqual(guide.path(e,h,mode),full.slice(0,h+1));
 for(const h of [30,120,365])assert(Math.abs(full[h].base/e.predictions[h].base-1)<1e-10);
 assert(full.every(q=>q.base>0&&q.bear<=q.bull&&Object.values(q).every(Number.isFinite)));count++;
}
const nodes=new Map(),node=id=>nodes.get(id)||nodes.set(id,{innerHTML:'',textContent:'',value:'BTC',addEventListener(){}}).get(id);
const ctx={document:{getElementById:node,querySelectorAll:()=>[]},window:{innerWidth:390,scrollTo(){}},fetch:async()=>({ok:true,json:async()=>data}),setInterval(){},console,Intl,Date};
vm.runInNewContext(fs.readFileSync('assets/crypto.js','utf8'),ctx);
setImmediate(()=>{const html=node('app').innerHTML;assert(html.includes('SPOT'));assert(html.includes('PERPETUAL'));assert(html.includes('유통'));assert(!/NaN|undefined|Infinity/.test(html));console.log(count+' common crypto paths and mobile-sized page render passed');});
