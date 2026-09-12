'use strict';
// Independent research adaptations. These are not executions of the original Pine/Freqtrade bots.
const T=require('./trend_methods.cjs'),B=require('./public_bot_methods.cjs');
const H4=14400000;
const names={momentum:'14일 모멘텀',ut:'UT ATR 반전',supertrend:'Supertrend 10·3',squeeze:'Squeeze 해제',channel:'20일 Donchian 돌파',macdbb:'MACD·BB 회귀'};
const filters={none:'단독',ema:'EMA 200 방향',adx:'ADX ≥ 20'};
const METHODS=[];
for(const family of Object.keys(names))for(const filter of Object.keys(filters))METHODS.push({id:family+'_'+filter,name:names[family]+' · '+filters[filter],family,filter});
METHODS.push(
 {id:'rsi_none',name:'RSI 2 눌림목',family:'rsi',filter:'none'},
 {id:'rsi_range',name:'RSI 2 + ADX < 18',family:'rsi',filter:'range'},
 {id:'momentum_breakout',name:'14일 + 3일 돌파',family:'momentum',filter:'breakout'},
 {id:'momentum_target6',name:'14일 + 6 ATR 익절',family:'momentum',filter:'none',target:6},
 {id:'momentum_boost',name:'14일 + 3일 돌파 + 부스팅',family:'momentum',filter:'boost'},
 {id:'knn_none',name:'Lorentzian 거리 kNN 응용',family:'knn',filter:'none'},
 {id:'momentum_knn',name:'14일 + Lorentzian 거리 kNN',family:'momentum',filter:'knn'},
 {id:'ut_knn',name:'UT + Lorentzian 거리 kNN',family:'ut',filter:'knn'},
 {id:'ut2_none',name:'UT ATR 10·2',family:'ut2',filter:'none'},
 {id:'ut3_none',name:'UT ATR 10·3',family:'ut3',filter:'none'},
 {id:'supertrend_target6',name:'Supertrend + 6 ATR 익절',family:'supertrend',filter:'none',target:6},
 {id:'momentum_adx_target6',name:'14일 + ADX + 6 ATR 익절',family:'momentum',filter:'adx',target:6},
 {id:'regime_none',name:'국면 분리 · 돌파 / 평균회귀',family:'regime',filter:'none'},
 {id:'consensus_none',name:'14일·Supertrend·kNN 2표 합의',family:'consensus',filter:'none'}
);
const mean=a=>a.reduce((s,x)=>s+x,0)/a.length;
const rsi=(up,down)=>up+down===0?50:100*up/(up+down);
function utStep(close,previous,stop,loss){
 if(close>stop&&previous>stop)return Math.max(stop,close-loss);
 if(close<stop&&previous<stop)return Math.min(stop,close+loss);
 return close>stop?close-loss:close+loss;
}
function regressionLast(y){const n=y.length,x=(n-1)/2,avg=mean(y);let top=0,bottom=0;for(let i=0;i<n;i++){top+=(i-x)*(y[i]-avg);bottom+=(i-x)**2;}return avg+top/bottom*x;}
function knnAt(features,bars,i,segment){
 // Each target ends at least one completed 4h bar before the decision.
 const pool=[];let maxLabelAt=null;
 for(let j=Math.max(segment+200,i-2000);j<=i-5;j+=4){
  if(!features[j])continue;
  const distance=features[i].reduce((s,v,k)=>s+Math.log1p(Math.abs(v-features[j][k])),0);
  const change=bars[j+4].close/bars[j].close-1;
  pool.push({distance,label:change>.0013?1:change<-.0013?-1:0});maxLabelAt=bars[j+4].end;
 }
 if(pool.length<100)return {vote:0,labelEnd:maxLabelAt,samples:pool.length};
 pool.sort((a,b)=>a.distance-b.distance);return {vote:pool.slice(0,8).reduce((s,r)=>s+r.label,0)/8,labelEnd:maxLabelAt,samples:pool.length};
}
function prepare(rows){
 const bars=T.aggregate(rows),momentum=T.signals(rows,'momentum14'),channel=T.signals(rows,'channel20'),macdbb=B.signals(rows,'humming_macdbb'),out=new Map(),features=[];
 let segment=0,atr=0,atr10=0,ema=0,ema20=0,up2=0,dn2=0,up9=0,dn9=0,up14=0,dn14=0,dmPlus=0,dmMinus=0,adx=0,st=null,stops=[0,0,0],squeeze=null,lin=[],lastRegime=null;
 for(let i=0;i<bars.length;i++){
  const b=bars[i],p=bars[i-1],reset=!p||b.t-p.t!==H4;
  const tr=reset?b.high-b.low:Math.max(b.high-b.low,Math.abs(b.high-p.close),Math.abs(b.low-p.close));
  if(reset){segment=i;atr=atr10=tr;ema=ema20=b.close;up2=dn2=up9=dn9=up14=dn14=dmPlus=dmMinus=adx=0;st=null;stops=[b.close,b.close,b.close];squeeze=null;lin=[];lastRegime=null;}
  else{
   atr+=(tr-atr)/14;atr10+=(tr-atr10)/10;ema+=2/201*(b.close-ema);ema20+=2/21*(b.close-ema20);
   const up=Math.max(0,b.close-p.close),down=Math.max(0,p.close-b.close),hp=b.high-p.high,lm=p.low-b.low;
   up2+=(up-up2)/2;dn2+=(down-dn2)/2;up9+=(up-up9)/9;dn9+=(down-dn9)/9;up14+=(up-up14)/14;dn14+=(down-dn14)/14;
   dmPlus+=((hp>lm&&hp>0?hp:0)-dmPlus)/14;dmMinus+=((lm>hp&&lm>0?lm:0)-dmMinus)/14;
   const dx=dmPlus+dmMinus>0?100*Math.abs(dmPlus-dmMinus)/(dmPlus+dmMinus):0;adx+=(dx-adx)/14;
  }
  const oldSt=st;st=B.supertrendStep(st,b,reset?null:p,10,3);
  const utDirections=[],utFlips=[];
  for(let k=0;k<3;k++){
   const old=stops[k];stops[k]=utStep(b.close,reset?b.close:p.close,old,(k+1)*atr10);
   const direction=b.close>stops[k]?1:b.close<stops[k]?-1:0;
   utDirections.push(direction);utFlips.push(!reset&&p.close<=old&&b.close>stops[k]?1:!reset&&p.close>=old&&b.close<stops[k]?-1:0);
  }
  if(i-segment<20||!(atr>0))continue;
  const window=bars.slice(i-19,i+1),prices=window.map(v=>v.close),average=mean(prices),sd=Math.sqrt(mean(prices.map(v=>(v-average)**2)));
  const trs=window.map((v,j)=>{const prev=bars[i-20+j];return Math.max(v.high-v.low,Math.abs(v.high-prev.close),Math.abs(v.low-prev.close));});
  const width=1.5*mean(trs),inside=2*sd<width,release=squeeze===true&&!inside;squeeze=inside;
  const midpoint=(Math.max(...window.map(v=>v.high))+Math.min(...window.map(v=>v.low)))/2;
  lin.push(b.close-(midpoint+average)/2);if(lin.length>21)lin.shift();
  const value=lin.length>=20?regressionLast(lin.slice(-20)):0,previousValue=lin.length===21?regressionLast(lin.slice(0,20)):0;
  const tp=window.map(v=>(v.high+v.low+v.close)/3),tpMean=mean(tp),deviation=mean(tp.map(v=>Math.abs(v-tpMean)));
  const cci=deviation>0?(tp.at(-1)-tpMean)/(.015*deviation):0;
  features[i]=[rsi(up14,dn14)/100,rsi(up9,dn9)/100,Math.tanh(cci/100),adx/100,Math.tanh((b.close-ema20)/atr/4)];
  if(i-segment<200)continue;
  const m=momentum.get(b.end);if(!m)continue;
  const prior=bars.slice(i-18,i),breakHigh=Math.max(...prior.map(v=>v.high)),breakLow=Math.min(...prior.map(v=>v.low));
  const knn=knnAt(features,bars,i,segment),knnDir=knn.vote>=.25?1:knn.vote<=-.25?-1:0;
  const momentumDir=m.side==='long'?1:m.side==='short'?-1:0;
  const votes=[momentumDir,st.direction,knnDir],consensus=votes.filter(v=>v===1).length>=2?1:votes.filter(v=>v===-1).length>=2?-1:0;
  const rsi2=rsi(up2,dn2),rsiDir=b.close>ema&&rsi2<10?1:b.close<ema&&rsi2>90?-1:0;
  const common={...m,at:b.end,price:b.close,atr,rank:m.rank,stop:null,target:null,holdBars:2880,trailLong:b.close-2.5*atr,trailShort:b.close+2.5*atr};
  const signal=(dir,exitLong,exitShort)=>({...common,side:dir===1?'long':dir===-1?'short':null,stop:b.close-dir*2.5*atr,exitLong,exitShort});
  const families={momentum:{...m},channel:channel.get(b.end),macdbb:macdbb.get(b.end),
   ut:signal(utFlips[0],utDirections[0]<0,utDirections[0]>0),ut2:signal(utFlips[1],utDirections[1]<0,utDirections[1]>0),ut3:signal(utFlips[2],utDirections[2]<0,utDirections[2]>0),
   supertrend:signal(oldSt&&oldSt.direction!==st.direction?st.direction:0,st.direction<0,st.direction>0),
   squeeze:signal(release?Math.sign(value):0,value<previousValue,value>previousValue),
   rsi:signal(rsiDir,rsi2>70||b.close<ema,rsi2<30||b.close>ema),
   knn:signal(knnDir,knnDir<0,knnDir>0),consensus:signal(consensus,consensus<0,consensus>0)};
  // Exit when leaving the entry family's regime; no retroactive switching of exit rules.
  const regimeId=adx>=25?'trend':adx<18?'range':'neutral';
  const regime=regimeId==='trend'?{...families.channel}:regimeId==='range'?{...families.macdbb}:signal(0,true,true);
  if(lastRegime!==null&&lastRegime!==regimeId){regime.exitLong=true;regime.exitShort=true;}lastRegime=regimeId;
  families.regime=regime;
  out.set(b.end,{families,ema,adx,knn,breakHigh,breakLow,price:b.close});
 }
 return out;
}
function apply(method,row,boostScore){
 if(!row)return {side:null};const q={...row.families[method.family]};
 if(!q.at)return {side:null};
 const dir=q.side==='long'?1:q.side==='short'?-1:0,breakout=dir===1?q.price>row.breakHigh:dir===-1?q.price<row.breakLow:false;
 let allowed=true;
 if(method.filter==='ema')allowed=dir*(q.price-row.ema)>0;
 if(method.filter==='adx')allowed=row.adx>=20;
 if(method.filter==='range')allowed=row.adx<18;
 if(method.filter==='breakout')allowed=breakout;
 if(method.filter==='boost')allowed=breakout&&Number.isFinite(boostScore)&&boostScore>=.1;
 if(method.filter==='knn')allowed=dir*row.knn.vote>=.25;
 if(!allowed)q.side=null;
 if(method.target&&q.side)q.target=q.price+dir*method.target*q.atr;
 return {...q,pattern:method.id,reason:method.name+' · 완료 4시간봉'};
}
module.exports={METHODS,prepare,apply,knnAt,utStep,regressionLast};
