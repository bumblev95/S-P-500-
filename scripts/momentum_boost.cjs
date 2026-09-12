'use strict';
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const T=require('./trend_methods.cjs'),D=require('./selector_data.cjs');
const H4=14400000,MODEL_SHA256='eb059abb6a4b5a6cbf05d1bb2db5f1e89cffae99e7b76579ac25edbd6254c025';
const PROFILES=Object.freeze([
 {id:'momentumBreakoutThree',directory:'control-three',label:'돌파 · 최대 3종목'},
 {id:'momentumBreakoutOne',directory:'control-one',label:'돌파 · 최대 1종목'},
 {id:'momentumBoostOne',directory:'boost-one',label:'돌파 + ML · 최대 1종목'}
]);
function loadModel(){
 const raw=fs.readFileSync(path.join(__dirname,'../simulation/momentum-boost/model.json'));
 if(crypto.createHash('sha256').update(raw).digest('hex')!==MODEL_SHA256)throw Error('Frozen boosting model changed: start a new study version');
 const m=JSON.parse(raw);if(JSON.stringify(m.features)!==JSON.stringify(D.FEATURES)||m.id!=='momentum14-breakout3-boost-2026-frozen-v1'||m.thresholdR!==.1)throw Error('Boost model schema mismatch');
 return m;
}
function predict(model,x){
 if(!Array.isArray(x)||x.length!==model.features.length||!x.every(Number.isFinite))return null;
 let score=model.baseline;
 for(const tree of model.trees){
  let i=0,steps=0;
  while(!tree[i].leaf){if(++steps>tree.length)throw Error('Invalid boosting tree');const node=tree[i];i=x[node.feature]<=node.threshold?node.left:node.right;}
  score+=tree[i].value;
 }
 return Number.isFinite(score)?score:null;
}
function mapsFor(market,model){
 const out={};
 for(const [symbol,source] of Object.entries(market.crypto||{})){
  const base=T.signals(source.frames?.['15m']||[],'momentum14'),bars=T.aggregate(source.frames?.['15m']||[]);
  const vectors=new Map(D.features(source,symbol,base).map(r=>[r.at,r.x]));
  for(let i=180;i<bars.length;i++){
   const b=bars[i],q=base.get(b.end);if(!q)continue;
   const prior=bars.slice(i-18,i),high=Math.max(...prior.map(r=>r.high)),low=Math.min(...prior.map(r=>r.low));
   const score=q.side?predict(model,vectors.get(q.at)):null;
   Object.assign(q,{candidateSide:q.side,breakoutHigh:high,breakoutLow:low,breakoutPassed:q.side==='long'?b.close>high:q.side==='short'?b.close<low:false,
    modelScore:score,modelPassed:Number.isFinite(score)&&score>=model.thresholdR,modelId:model.id,featureReady:vectors.has(q.at)});
  }
  out[symbol]=base;
 }
 return out;
}
function apply(q,profile){
 if(!PROFILES.some(p=>p.id===profile))throw Error('Unknown breakout study profile');
 if(!q)return {side:null};
 const usesModel=profile==='momentumBoostOne',accepted=!!q.candidateSide&&q.breakoutPassed&&(!usesModel||q.modelPassed);
 const reason=!q.candidateSide?'14일 변화가 변동폭 기준 미달 · 관망':!q.breakoutPassed?'14일 '+(q.candidateSide==='long'?'상승':'하락')+' 흐름 · 최근 3일 돌파 대기':usesModel&&!q.featureReady?'돌파 확인 · ML 입력 자료 부족':usesModel&&!q.modelPassed?'돌파 확인 · ML 점수 미달':usesModel?'14일 흐름 + 3일 돌파 + ML 통과':'14일 흐름 + 3일 돌파 확인';
 return {...q,side:accepted?q.candidateSide:null,reason,target:null};
}
function providers(market,profile='momentumBoostOne',model=loadModel(),sharedMaps){
 const maps=sharedMaps||mapsFor(market,model),times=Object.fromEntries(Object.entries(maps).map(([s,m])=>[s,[...m.keys()]]));
 const replay=(symbol,rows)=>apply(maps[symbol]?.get(rows.at(-1).end),profile);
 const forward=(symbol,rows)=>{
  const end=rows.at(-1).end,at=times[symbol]||[];let lo=0,hi=at.length;
  while(lo<hi){const mid=(lo+hi)>>1;if(at[mid]<=end)lo=mid+1;else hi=mid;}
  const q=maps[symbol]?.get(at[lo-1]);
  if(!q||end-q.at>=H4)return {side:null,at:end,reason:'연속된 4시간봉 준비 또는 최신 자료 대기',stale:true};
  return {...apply(q,profile),indicatorAt:q.at};
 };
 return {maps,forward,replay};
}
module.exports={MODEL_SHA256,PROFILES,loadModel,predict,mapsFor,apply,providers};
