'use strict';
// Fixed before results: no parameter search and no fitting to evaluation years.
const METHODS=[
 {id:'channel20',name:'20일 돌파 추세',description:'4시간 종가가 직전 20일 고점·저점을 돌파하면 진입. 반대 10일 채널을 이탈하면 종료.'},
 {id:'ema10_30',name:'10·30일 이동평균 추세',description:'4시간봉 EMA 60·180의 방향과 종가가 일치하면 진입. 평균선 방향이 바뀌면 종료.'},
 {id:'momentum14',name:'14일 모멘텀',description:'14일 가격 변화가 4시간 ATR의 2배를 넘으면 그 방향으로 진입. 모멘텀이 반전하면 종료.'}
];
const H4=14400000,STEP=900000;
function aggregate(rows){
 const out=[];let group=[];
 for(const r of rows){
  if(group.length&&Math.floor(r.t/H4)!==Math.floor(group[0].t/H4))group=[];
  group.push(r);
  if(group.length===16&&group[0].t%H4===0&&group.every((x,i)=>x.t===group[0].t+i*STEP)){
   out.push({t:group[0].t,end:r.end,open:group[0].open,high:Math.max(...group.map(x=>x.high)),low:Math.min(...group.map(x=>x.low)),close:r.close});group=[];
  }
 }
 return out;
}
function signals(rows,id){
 if(!METHODS.some(m=>m.id===id))throw Error('Unknown fixed method');
 const bars=aggregate(rows),out=new Map();let fast,slow,atr,segment=0;
 for(let i=0;i<bars.length;i++){
  const r=bars[i],p=bars[i-1];
  if(!p||r.t-p.t!==H4){fast=slow=r.close;atr=r.high-r.low;segment=i;}
  else{fast+=2/61*(r.close-fast);slow+=2/181*(r.close-slow);atr+=(Math.max(r.high-r.low,Math.abs(r.high-p.close),Math.abs(r.low-p.close))-atr)/14;}
  if(i-segment<180||!(atr>0))continue;
  let direction=0,exitLong=false,exitShort=false;
  if(id==='channel20'){
   const prior=bars.slice(i-120,i),exit=prior.slice(-60);
   direction=r.close>Math.max(...prior.map(x=>x.high))?1:r.close<Math.min(...prior.map(x=>x.low))?-1:0;
   exitLong=r.close<Math.min(...exit.map(x=>x.low));exitShort=r.close>Math.max(...exit.map(x=>x.high));
  }else if(id==='ema10_30'){
   direction=fast>slow&&r.close>fast?1:fast<slow&&r.close<fast?-1:0;exitLong=fast<=slow;exitShort=fast>=slow;
  }else{
   const change=r.close-bars[i-84].close;direction=change>2*atr?1:change< -2*atr?-1:0;exitLong=change<=0;exitShort=change>=0;
  }
  const distance=2.5*atr;
  out.set(r.end,{at:r.end,side:direction===1?'long':direction===-1?'short':null,price:r.close,atr,
   stop:r.close-direction*distance,target:null,holdBars:30*96,pattern:id,rank:Math.abs(fast-slow)/atr,
   reason:METHODS.find(m=>m.id===id).name+' · 완료된 4시간봉',exitLong,exitShort,trailLong:r.close-distance,trailShort:r.close+distance});
 }
 return out;
}
module.exports={METHODS,aggregate,signals};
