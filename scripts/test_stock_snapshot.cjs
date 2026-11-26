const assert=require('node:assert/strict');
const {test}=require('node:test');
const {reader}=require('../assets/stock-snapshot.js');

test('loads the catalog and one matching stock without reading the full forecast',async()=>{
 const revision='1'.repeat(64), paths=[];
 const catalog={schemaVersion:1,revision,items:[{symbol:'BRK-B'}],risk:{}};
 const data=reader(async path=>{
  paths.push(path);
  return {ok:true,json:async()=>path.endsWith('index.json')?catalog:{revision,stock:{symbol:'BRK-B'}}};
 });
 const index=await data.catalog();
 assert.equal((await data.stock(index,'BRK-B')).symbol,'BRK-B');
 await data.stock(index,'BRK-B');
 assert.deepEqual(paths,['forecasts/by-symbol/index.json','forecasts/by-symbol/BRK-B.json?v='+revision]);
});

test('rejects a different publication and makes an uncached retry possible',async()=>{
 const revision='1'.repeat(64);
 let calls=0;
 const data=reader(async()=>({ok:true,json:async()=>({revision:(++calls===1?'0':'1').repeat(64),stock:{symbol:'AAPL'}})}));
 await assert.rejects(data.stock({revision},'AAPL'),/Version mismatch/);
 assert.equal((await data.stock({revision},'AAPL')).symbol,'AAPL');
});
