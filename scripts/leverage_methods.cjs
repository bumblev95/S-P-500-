'use strict';
// Research-only recipes. Daily equity setups are explicitly adapted to 24/7 crypto.
const T=require('./trend_methods.cjs');
const STEP=900000,DAY=86400000;
const METHODS=[
 {id:'boost_swing',name:'14일 돌파 + 기존 부스팅',kind:'스윙',rule:'완료 4시간봉 14일 모멘텀·3일 돌파·연도별 과거 학습 부스팅 ≥0.1R. 2.5 ATR 손절·추적, 모멘텀 반전 또는 30일 종료.'},
 {id:'channel_swing',name:'20일 채널 추세',kind:'스윙',rule:'완료 4시간봉 20일 채널 돌파, 2.5 ATR 초기 손절·추적, 반대 10일 채널 이탈 또는 30일 종료.'},
 {id:'q_daily',name:'쿨라마기 응용 · 일봉 돌파',kind:'스윙',rule:'20일 상승 ≥15%, 10일선>20일선, 직전 5일 범위가 이전 10일 범위의 75% 이하, 5일 고점 돌파·거래량 20일 평균 1.5배. 당일 저점 손절. 3일 뒤 절반 매도·잔량 본전 손절, 10일선 종가 이탈 또는 30일 종료. 롱만.'},
 {id:'q_flag',name:'쿨라마기 응용 · 15분 깃발',kind:'스윙',rule:'전일 기준 20일 상승 ≥15%·10일선>20일선. 직전 16개 15분봉 범위가 이전 32봉 범위의 75% 이하, 그 고점 돌파·거래량 32봉 평균 1.5배. 깃발 저점 손절. 3일 뒤 절반·본전, 10일선 이탈 또는 15일 종료. 롱만.'},
 {id:'breakout_day',name:'15분 돌파 + EMA 방향',kind:'단타',rule:'직전 32봉 고점·저점 돌파, EMA50·200 방향 일치. 2 ATR 손절, 2R 절반 익절 후 본전·2 ATR 추적. 8시간 종료.'},
 {id:'pullback_day',name:'15분 EMA 눌림목',kind:'단타',rule:'EMA20·50·200 정렬 방향으로 종가가 EMA20을 재돌파. 1.5 ATR 손절, 2R 절반 익절 후 본전·2 ATR 추적. 8시간 종료.'},
 {id:'vwap_day',name:'24시간 VWAP 회귀',kind:'단타',rule:'EMA50·200 간격 <1 ATR인 구간에서 종가가 직전 24시간 거래량 가중 평균 ±2σ 밖에서 안으로 복귀. 1.5 ATR 손절, 진입 신호 VWAP 전량 익절. 8시간 종료.'},
 {id:'orb_day',name:'UTC 첫 1시간 범위 돌파',kind:'단타',rule:'UTC 00–01시 범위를 01–04시 종가가 돌파하고 EMA200 방향 일치. 반대 범위 끝 손절, 2R 절반·본전·2 ATR 추적. 하루·종목당 첫 신호만, 8시간 종료.'},
 {id:'regime_day',name:'단타 국면 조합',kind:'단타',rule:'EMA50·200 간격 ≥2 ATR이면 15분 돌파, <1 ATR이면 VWAP 회귀. 중간은 대기. 진입 때 선택한 청산 규칙 유지.'}
];
const POLICIES=[{id:'risk1',name:'손절 예산 1%',risk:.01},{id:'risk2',name:'손절 예산 2%',risk:.02},{id:'risk4',name:'손절 예산 4%',risk:.04},{id:'margin25',name:'증거금 25%',margin:.25},{id:'margin50',name:'증거금 50%',margin:.50},{id:'margin90',name:'증거금 90%',margin:.90}];
const mean=a=>a.reduce((s,x)=>s+x,0)/a.length;
function prepare(rows,scores=new Map(),symbol='TEST'){
 const n=rows.length,features=Object.fromEntries(['atr','ema20','ema50','ema200','daily10','daily20'].map(k=>[k,new Float64Array(n)])),events=Object.fromEntries(METHODS.map(m=>[m.id,new Map()]));
 const h4=T.aggregate(rows),momentum=T.signals(rows,'momentum14'),channel=T.signals(rows,'channel20'),breaks=new Map();
 for(let j=18;j<h4.length;j++){const p=h4.slice(j-18,j);breaks.set(h4[j].end,{high:Math.max(...p.map(x=>x.high)),low:Math.min(...p.map(x=>x.low))});}
 let atr=0,e20=0,e50=0,e200=0,day=null,daily=[],orb=null,orbUsed=false;
 const capacity=i=>.005*Math.min(rows[i].volume,mean(rows.slice(Math.max(0,i-32),i).map(r=>r.volume)));
 const emit=(id,i,side,stop,exit,rank=0,target=null)=>{const b=rows[i];if(side&&side*(b.close-stop)>0&&Number.isFinite(stop))events[id].set(i,{at:b.end,side,price:b.close,stop,exit,rank,target,liquidityQty:capacity(i)});};
 for(let i=0;i<n;i++){
  const b=rows[i],p=rows[i-1],tr=p?Math.max(b.high-b.low,Math.abs(b.high-p.close),Math.abs(b.low-p.close)):b.high-b.low;
  if(!i){atr=tr;e20=e50=e200=b.close;}else{atr+=(tr-atr)/14;e20+=2/21*(b.close-e20);e50+=2/51*(b.close-e50);e200+=2/201*(b.close-e200);}
  features.atr[i]=atr;features.ema20[i]=e20;features.ema50[i]=e50;features.ema200[i]=e200;
  if(!day||day.t!==Math.floor(b.t/DAY)*DAY){day={t:Math.floor(b.t/DAY)*DAY,open:b.open,high:b.high,low:b.low,close:b.close,volume:0,count:0};orb={high:-Infinity,low:Infinity,count:0};orbUsed=false;}
  day.high=Math.max(day.high,b.high);day.low=Math.min(day.low,b.low);day.close=b.close;day.volume+=b.volume;day.count++;
  const hour=(b.t%DAY)/3600000;if(hour<1){orb.high=Math.max(orb.high,b.high);orb.low=Math.min(orb.low,b.low);orb.count++;}
  let d10=daily.length>=10?mean(daily.slice(-10).map(d=>d.close)):0,d20=daily.length>=20?mean(daily.slice(-20).map(d=>d.close)):0;
  const strong=daily.length>=21&&daily.at(-1).close/daily.at(-21).close-1>=.15&&d10>d20;
  features.daily10[i]=d10;features.daily20[i]=d20;
  if(i>=200&&atr>0){
   const prior=rows.slice(i-32,i),hi=Math.max(...prior.map(x=>x.high)),lo=Math.min(...prior.map(x=>x.low));
   const dir=b.close>hi&&e50>e200?1:b.close<lo&&e50<e200?-1:0;
   const rank=Math.abs(e50-e200)/atr;
   emit('breakout_day',i,dir,b.close-dir*2*atr,'partial2r',rank);
   const pull=e20>e50&&e50>e200&&p.close<=features.ema20[i-1]&&b.close>e20?1:e20<e50&&e50<e200&&p.close>=features.ema20[i-1]&&b.close<e20?-1:0;
   emit('pullback_day',i,pull,b.close-pull*1.5*atr,'partial2r',rank);
   const window=rows.slice(i-96,i),vol=window.reduce((s,r)=>s+r.volume,0),vw=window.reduce((s,r)=>s+r.close*r.volume,0)/vol,sd=Math.sqrt(window.reduce((s,r)=>s+(r.close-vw)**2*r.volume,0)/vol);
   const revert=rank<1?(p.close<vw-2*sd&&b.close>=vw-2*sd&&b.close<vw?1:p.close>vw+2*sd&&b.close<=vw+2*sd&&b.close>vw?-1:0):0;
   emit('vwap_day',i,revert,b.close-revert*1.5*atr,'vwap',1-rank,vw);
   if(rank>=2)emit('regime_day',i,dir,b.close-dir*2*atr,'partial2r',rank);
   if(rank<1)emit('regime_day',i,revert,b.close-revert*1.5*atr,'vwap',1-rank,vw);
   if(hour>=1&&hour<4&&orb.count===4&&!orbUsed){const o=b.close>orb.high&&b.close>e200?1:b.close<orb.low&&b.close<e200?-1:0;if(o){emit('orb_day',i,o,o>0?orb.low:orb.high,'partial2r',rank);orbUsed=true;}}
   if(strong){const flag=rows.slice(i-16,i),before=rows.slice(i-48,i-16),fh=Math.max(...flag.map(r=>r.high)),fl=Math.min(...flag.map(r=>r.low)),bh=Math.max(...before.map(r=>r.high)),bl=Math.min(...before.map(r=>r.low));if(fh-fl<=.75*(bh-bl)&&b.close>fh&&b.volume>=1.5*mean(prior.map(r=>r.volume)))emit('q_flag',i,1,fl,'q15',daily.at(-1).close/daily.at(-21).close-1);}
  }
  for(const [id,map] of [['boost_swing',momentum],['channel_swing',channel]]){
   const q=map.get(b.end);if(!q)continue;const side=q.side==='long'?1:q.side==='short'?-1:0,br=breaks.get(b.end);
   const ok=id!=='boost_swing'||(br&&(side>0?q.price>br.high:q.price<br.low)&&scores.get(symbol+':'+b.end)>=.1);
   // Exit metadata exists even when the entry filter rejects the bar.
   events[id].set(i,{at:b.end,side:ok?side:0,price:q.price,stop:q.stop,exit:'swing',rank:q.rank,exitLong:q.exitLong,exitShort:q.exitShort,trailLong:q.trailLong,trailShort:q.trailShort,liquidityQty:capacity(i)});
  }
  if(b.end%DAY===DAY-1&&day.count===96){
   if(daily.length>=21){
    const prev5=daily.slice(-5),prev10=daily.slice(-15,-5),hi=Math.max(...prev5.map(d=>d.high)),lo=Math.min(...prev5.map(d=>d.low));
    const oldRange=Math.max(...prev10.map(d=>d.high))-Math.min(...prev10.map(d=>d.low));
    if(strong&&hi-lo<=.75*oldRange&&b.close>hi&&day.volume>=1.5*mean(daily.slice(-20).map(d=>d.volume)))emit('q_daily',i,1,day.low,'q30',b.close/daily.at(-21).close-1);
   }
   daily.push({...day});d10=daily.length>=10?mean(daily.slice(-10).map(d=>d.close)):0;d20=daily.length>=20?mean(daily.slice(-20).map(d=>d.close)):0;
   features.daily10[i]=d10;features.daily20[i]=d20;
  }
 }
 return {features,events};
}
module.exports={METHODS,POLICIES,prepare,STEP,DAY};
