'use strict';
// Single predeclared ablation. Statistical BOCPD, NOT the cited GP + LSTM model.
const T=require('./trend_methods.cjs');
const H4=14400000,DAY=86400000;
const RULES=Object.freeze({version:'momentum14-bocpd-ablation-v1',hazard:1/126,kappa:1,alpha:3,
 maxHypotheses:128,recentBars:6,threshold:.5,oppositeAtr:.5,cooldownBars:6,minObservations:42});
function logGamma(z){
 const c=[676.5203681218851,-1259.1392167224028,771.32342877765313,-176.61502916214059,12.507343278686905,-.13857109526572012,9.984369578019572e-6,1.5056327351493116e-7];
 if(z<.5)return Math.log(Math.PI)-Math.log(Math.sin(Math.PI*z))-logGamma(1-z);
 z--;let x=.99999999999980993;for(let i=0;i<c.length;i++)x+=c[i]/(z+i+1);
 const t=z+7.5;return .5*Math.log(2*Math.PI)+(z+.5)*Math.log(t)-t+Math.log(x);
}
class Detector{
 constructor(variance,rules=RULES){
  if(!(variance>0&&Number.isFinite(variance)))throw Error('Positive prior variance required');
  this.rules=rules;this.variance=variance;this.normalizers=new Map();this.reset();
 }
 prior(){return {n:0,p:1,mu:0,k:this.rules.kappa,a:this.rules.alpha,b:this.variance*(this.rules.alpha-1)};}
 reset(){this.states=[this.prior()];this.observations=0;this.maxDiscardedMass=0;}
 update(x){
  if(!Number.isFinite(x))throw Error('Invalid return');
  const logs=this.states.map(s=>{
   const df=2*s.a,scale=s.b*(s.k+1)/(s.a*s.k);
   let norm=this.normalizers.get(s.n);if(norm===undefined){norm=logGamma((df+1)/2)-logGamma(df/2)-.5*Math.log(df*Math.PI);this.normalizers.set(s.n,norm);}
   return Math.log(s.p)+norm-.5*Math.log(scale)-(df+1)/2*Math.log1p((x-s.mu)**2/(df*scale));
  });
  const max=Math.max(...logs),weights=logs.map(v=>Math.exp(v-max)),total=weights.reduce((s,v)=>s+v,0),h=this.rules.hazard;
  const next=[{...this.prior(),p:h}];
  for(let i=0;i<this.states.length;i++){
   const s=this.states[i],k=s.k+1;
   next.push({n:s.n+1,p:(1-h)*weights[i]/total,mu:(s.k*s.mu+x)/k,k,a:s.a+.5,b:s.b+s.k*(x-s.mu)**2/(2*k)});
  }
  // Keep the reset hypothesis plus highest posterior run lengths. No forced
  // reset at a maximum duration; record approximation mass discarded.
  const kept=[next[0],...next.slice(1).sort((a,b)=>b.p-a.p).slice(0,this.rules.maxHypotheses-1)];
  const retained=kept.reduce((s,v)=>s+v.p,0);this.maxDiscardedMass=Math.max(this.maxDiscardedMass,Math.max(0,1-retained));
  this.states=kept.map(s=>({...s,p:s.p/retained}));this.observations++;
  const recentProbability=this.states.filter(s=>s.n<=this.rules.recentBars).reduce((s,v)=>s+v.p,0);
  return {recentProbability,ready:this.observations>=this.rules.minObservations,observations:this.observations};
 }
}
function fitPrior(bars,from,before){
 const xs=[];let first,last;
 for(let i=1;i<bars.length;i++){
  const r=bars[i],p=bars[i-1];if(r.end<from||r.end>=before||r.t-p.t!==H4)continue;
  xs.push(Math.log(r.close/p.close));first??=r.end;last=r.end;
 }
 if(xs.length<60)throw Error('Insufficient pre-evaluation prior calibration');
 const mean=xs.reduce((s,x)=>s+x,0)/xs.length;
 const variance=xs.reduce((s,x)=>s+(x-mean)**2,0)/(xs.length-1);
 return {variance:Math.max(variance,1e-12),observations:xs.length,start:first,end:last};
}
function overlay(q,diagnostic,fastChange,at,memory,rules=RULES){
 const alarm=diagnostic.ready&&diagnostic.recentProbability>=rules.threshold;
 const up=alarm&&fastChange>rules.oppositeAtr*q.atr,down=alarm&&fastChange< -rules.oppositeAtr*q.atr;
 if(up)memory.shortUntil=at+rules.cooldownBars*H4;
 if(down)memory.longUntil=at+rules.cooldownBars*H4;
 const blockLong=at<(memory.longUntil||0),blockShort=at<(memory.shortUntil||0);
 const blocked=q.side==='long'&&blockLong||q.side==='short'&&blockShort;
 return {...q,pattern:'momentum14_cpd',side:blocked?null:q.side,
  exitLong:q.exitLong||blockLong,exitShort:q.exitShort||blockShort,
  reason:blocked?'변화 감지 후 반대 흐름 · 기존 방향 진입 보류':'14일 모멘텀 + 온라인 변화 감지',
  cpd:{probability:diagnostic.recentProbability,up,down,blockLong,blockShort,blocked,fastChange}};
}
function signals(rows,{start,end,trainingStart,trainingEnd},rules=RULES){
 const bars=T.aggregate(rows.filter(r=>r.end<=end)),base=T.signals(rows.filter(r=>r.end<=end),'momentum14');
 const prior=fitPrior(bars,trainingStart,trainingEnd);if(prior.end>=start)throw Error('Calibration leaks evaluation data');
 const detector=new Detector(prior.variance,rules),maps=new Map(),events=[],memory={};let segment=0;
 const counts={eligibleSignals:0,blockedSignals:0,upAlarms:0,downAlarms:0,probabilityAlarms:0};
 for(let i=1;i<bars.length;i++){
  const r=bars[i],p=bars[i-1];if(r.end<trainingEnd)continue;
  if(r.t-p.t!==H4){detector.reset();segment=i;delete memory.shortUntil;delete memory.longUntil;continue;}
  const d=detector.update(Math.log(r.close/p.close)),q=base.get(r.end);
  if(!q)continue;
  const fast=i-segment>=rules.recentBars?r.close-bars[i-rules.recentBars].close:0;
  const v=overlay(q,d,fast,r.end,memory,rules);maps.set(r.end,v);
  if(r.end>=start){
   if(q.side)counts.eligibleSignals++;if(v.cpd.blocked)counts.blockedSignals++;
   if(d.ready&&d.recentProbability>=rules.threshold)counts.probabilityAlarms++;
   if(v.cpd.up)counts.upAlarms++;if(v.cpd.down)counts.downAlarms++;
   if(v.cpd.up||v.cpd.down)events.push({at:r.end,probability:d.recentProbability,up:v.cpd.up,down:v.cpd.down,fastChange:fast,atr:q.atr});
  }
 }
 return {base,maps,prior,counts,events,maxDiscardedMass:detector.maxDiscardedMass};
}
module.exports={RULES,Detector,fitPrior,overlay,signals,H4,DAY};
