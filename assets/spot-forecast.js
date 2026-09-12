(function(root){
'use strict';
const finite=Number.isFinite;
function rng(seed){let x=2166136261;for(const c of seed)x=Math.imul(x^c.charCodeAt(0),16777619);return()=>{x^=x<<13;x^=x>>>17;x^=x<<5;return (x>>>0)/4294967296}}
function inspect(e,h,now=Date.now()){
 const m=e.spotModel,r=m?.predictions?.[h],f=r?.forecast,age=(now-Date.parse(m?.asOf))/86400000,history=e.spotHistory?.at(-1),diff=Math.abs(e.spot?.price/m?.anchor-1),trainedAge=(now-Date.parse(e.modelGeneratedAt))/86400000;
 const valid=!!m&&m.asOf===history?.date&&age>=0&&age<=3&&trainedAge>=0&&trainedAge<=3&&finite(diff)&&diff<=.1&&finite(f?.logReturn)&&finite(f?.base)&&f.base>0;
 const eligible=valid&&r?.status==='eligible';
 return {eligible,record:r,model:m,forecast:eligible?f:null,reason:!m?'학습 결과를 확인할 수 없습니다':!valid&&r?.forecast?'예측과 최신 현물 날짜·가격을 다시 확인해야 합니다':(r?.reasons||[]).join(' · ')||'과거 검증 기준 통과'};
}
const cache=new WeakMap();
function simulate(e){
 const state=[30,120,365].map(h=>inspect(e,h)),key=state.map(s=>s.eligible?'1':'0').join('')+'|'+e.spot?.price;
 if(cache.get(e)?.key===key)return cache.get(e).value;
 const anchor=e.spot?.price,history=e.spotHistory||[],returns=[];
 if(!finite(anchor)||anchor<=0)return null;
 for(let i=Math.max(1,history.length-120);i<history.length;i++){
  if(Date.parse(history[i].date)-Date.parse(history[i-1].date)!==86400000)return null;
  const x=Math.log(history[i].close/history[i-1].close);if(!finite(x))return null;returns.push(x);
 }
 if(returns.length<60)return null;
 const mean=returns.reduce((s,r)=>s+r,0)/returns.length,random=rng(e.symbol+'|'+history.at(-1).date+'|spot-bootstrap-v2');
 // No estimated trend where the model is withheld. This is a neutral stress reference, not a forecast.
 const knots=[{t:0,v:0},...[30,120,365].map((t,i)=>({t,v:state[i].eligible?state[i].forecast.logReturn:0}))];
 const drift=t=>{const b=knots.findIndex(k=>k.t>=t);if(b<=0)return 0;const a=knots[b-1],z=knots[b];return a.v+(z.v-a.v)*(t-a.t)/(z.t-a.t)};
 const paths=[];
 for(let n=0;n<400;n++){
  const p=[0];let start=0;
  for(let t=1;t<=365;t++){if((t-1)%5===0)start=Math.floor(random()*(returns.length-4));p.push(p.at(-1)+returns[start+(t-1)%5]-mean);}
  paths.push(p.map((v,t)=>anchor*Math.exp(v+drift(t))));
 }
 const quantile=(a,p)=>{const s=[...a].sort((x,y)=>x-y),i=(s.length-1)*p,l=Math.floor(i);return s[l]+(s[Math.ceil(i)]-s[l])*(i-l)};
 const bands=Array.from({length:366},(_,t)=>({t,base:quantile(paths.map(p=>p[t]),.5),bear:quantile(paths.map(p=>p[t]),.1),bull:quantile(paths.map(p=>p[t]),.9),ai:anchor*Math.exp(drift(t))}));
 // Fixed seeded samples across ALL horizon buttons; endpoints remain free, never bridged to a target.
 const samples=[paths[7],paths[83],paths[219]];
 const value={bands,samples,paths,state};cache.set(e,{key,value});return value;
}
function path(e,h,style='center'){
 const s=simulate(e);if(!s)return [];
 return s.bands.slice(0,h+1).map((p,i)=>({...p,base:style==='sample'?s.samples[0][i]:p.base}));
}
const api={inspect,simulate,path};if(typeof module!=='undefined')module.exports=api;else root.SpotForecast=api;
})(typeof window!=='undefined'?window:globalThis);
