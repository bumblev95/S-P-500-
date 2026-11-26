(function(root){
  'use strict';
  function reader(fetcher=root.fetch.bind(root)){
    const directory='forecasts/by-symbol/';
    const requests=new Map();
    function request(path){
      if(!requests.has(path))requests.set(path,fetcher(path,{cache:'no-cache'}).then(response=>{
        if(!response.ok)throw new Error('Snapshot unavailable');
        return response.json();
      }).catch(error=>{requests.delete(path);throw error;}));
      return requests.get(path);
    }
    async function catalog(){
      const data=await request(directory+'index.json');
      if(data?.schemaVersion!==1||!/^[a-f0-9]{64}$/.test(data.revision)||
         !Array.isArray(data.items)||!data.items.length||!data.risk)throw new Error('Invalid stock index');
      return data;
    }
    async function stock(index,symbol){
      const path=directory+encodeURIComponent(symbol)+'.json?v='+index.revision;
      const data=await request(path);
      if(data?.revision!==index.revision||data.stock?.symbol!==symbol){
        requests.delete(path);
        throw new Error('Version mismatch');
      }
      return data.stock;
    }
    function full(){return request('forecasts/latest.json');}
    return {catalog,stock,full};
  }
  const api={reader};
  if(typeof module!=='undefined')module.exports=api;else root.StockSnapshot=api;
})(typeof window!=='undefined'?window:globalThis);
