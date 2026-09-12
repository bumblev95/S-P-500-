'use strict';
// Independent implementations of published ideas, not third-party bot execution.
const T=require('./trend_methods.cjs');
const METHODS=[
 {...T.METHODS.find(m=>m.id==='momentum14'),sourceTitle:'기존 대시보드 기준 전략',url:'https://www.aqr.com/Insights/Research/Journal-Article/Time-Series-Momentum',adaptation:'이전 14일 모멘텀 구현을 그대로 비교 기준으로 사용. 논문의 전략·수익률 복제가 아님.'},
 {id:'humming_macdbb',name:'Hummingbot MACD·BB 응용',description:'볼린저 밴드 위치와 MACD 반전이 함께 나타날 때 평균 회귀 진입. 중앙선 복귀 시 종료.',sourceTitle:'Hummingbot · Federico Cardoso 공개 코드',url:'https://gist.github.com/cardosofede/54d31cae1d9bb0e6d70ead6191ca05d6',adaptation:'BB 100·2, MACD 21·42·9, 0.2/0.8 진입 조건은 공개 코드 기준. 원본 APE 3분봉·20배·55분 제한을 BTC/ETH/SOL 4시간봉·공통 위험 관리로 변경. 중앙선 종료를 추가.'},
 {id:'triple_supertrend',name:'Triple Supertrend 응용',description:'세 Supertrend 방향이 일치하면 진입하고 모두 반대로 바뀌면 종료.',sourceTitle:'Freqtrade 전략 저장소 · Supertrend',url:'https://github.com/freqtrade/freqtrade-strategies/blob/main/user_data/strategies/Supertrend.py',adaptation:'세 지표 합의 아이디어만 적용. ATR 기간 7·10·14와 배수 3을 사전 고정하고 숏을 대칭 추가. 원본의 최적화된 1시간봉 매개변수·ROI·손절을 복제하지 않음.'},
 {id:'turtle55',name:'터틀 55일 돌파 응용',description:'직전 55일 고점·저점을 돌파하면 진입하고 반대 20일 채널을 벗어나면 종료.',sourceTitle:'Michael Covel · TurtleTrader 시스템 설명',url:'https://www.turtletrader.com/turtle-trading/',adaptation:'4시간봉 330개를 55일 범위로 사용. 종가 확인 후 다음 시가 체결, 추가 매수 생략, 공통 ATR 손절·30일 보유 제한 적용. 원본 터틀 시스템 전체 재현이 아님.'},
 {id:'rayner200',name:'Rayner 200일 돌파 응용',description:'직전 200일 고점·저점을 돌파하면 진입하고 반대 10일 채널을 벗어나면 종료.',sourceTitle:'Rayner Teo · Modified turtle rules',url:'https://www.tradingwithrayner.com/turtle-trading-rules/',adaptation:'4시간봉 1,200개로 200일 범위를 계산. 원문의 다수 전통 선물·2 ATR 손절을 세 코인과 공통 위험 관리로 변경. 원문 연 수익률 32.12%·최대 낙폭 41.51%는 저자의 다른 시장 백테스트 주장으로, 우리 성적에 사용하지 않음.'}
];
function supertrendStep(state,r,previous,n,multiplier){
 const tr=previous?Math.max(r.high-r.low,Math.abs(r.high-previous.close),Math.abs(r.low-previous.close)):r.high-r.low;
 const atr=state?state.atr+(tr-state.atr)/n:tr,mid=(r.high+r.low)/2,upper=mid+multiplier*atr,lower=mid-multiplier*atr;
 if(!state)return {atr,upper,lower,direction:1};
 const finalUpper=upper<state.upper||previous.close>state.upper?upper:state.upper;
 const finalLower=lower>state.lower||previous.close<state.lower?lower:state.lower;
 const direction=state.direction===1?(r.close<finalLower?-1:1):(r.close>finalUpper?1:-1);
 return {atr,upper:finalUpper,lower:finalLower,direction};
}
function signals(rows,id){
 if(id==='momentum14')return T.signals(rows,id);
 const method=METHODS.find(m=>m.id===id);if(!method)throw Error('Unknown public method');
 const bars=T.aggregate(rows),out=new Map(),lookback=id==='rayner200'?1200:id==='turtle55'?330:180;
 let atr,fast,slow,macdSignal,segment=0,st=[null,null,null];
 for(let i=0;i<bars.length;i++){
  const r=bars[i],p=bars[i-1],reset=!p||r.t-p.t!==14400000;
  if(reset){segment=i;atr=r.high-r.low;fast=slow=r.close;macdSignal=0;st=[null,null,null];}
  else{atr+=(Math.max(r.high-r.low,Math.abs(r.high-p.close),Math.abs(r.low-p.close))-atr)/14;fast+=2/22*(r.close-fast);slow+=2/43*(r.close-slow);macdSignal+=2/10*((fast-slow)-macdSignal);}
  st=st.map((state,j)=>supertrendStep(state,r,reset?null:p,[7,10,14][j],3));
  if(i-segment<lookback||!(atr>0))continue;
  let direction=0,exitLong=false,exitShort=false,rank=0;
  if(id==='humming_macdbb'){
   const values=bars.slice(i-99,i+1).map(r=>r.close),mean=values.reduce((s,v)=>s+v,0)/100,sd=Math.sqrt(values.reduce((s,v)=>s+(v-mean)**2,0)/100);
   if(!(sd>0))continue;
   const bbp=(r.close-mean+2*sd)/(4*sd),macd=fast-slow,hist=macd-macdSignal;
   direction=bbp<.2&&hist>0&&macd<0?1:bbp>.8&&hist<0&&macd>0?-1:0;
   exitLong=r.close>=mean;exitShort=r.close<=mean;rank=Math.abs(bbp-.5);
  }else if(id==='triple_supertrend'){
   const up=st.every(s=>s.direction===1),down=st.every(s=>s.direction===-1);
   direction=up?1:down?-1:0;exitLong=down;exitShort=up;rank=Math.abs(fast-slow)/atr;
  }else{
   const prior=bars.slice(i-lookback,i),high=Math.max(...prior.map(r=>r.high)),low=Math.min(...prior.map(r=>r.low));
   const exit=prior.slice(id==='turtle55'?-120:-60);
   direction=r.close>high?1:r.close<low?-1:0;exitLong=r.close<Math.min(...exit.map(r=>r.low));exitShort=r.close>Math.max(...exit.map(r=>r.high));
   rank=direction===1?(r.close-high)/atr:direction===-1?(low-r.close)/atr:0;
  }
  const distance=2.5*atr;
  out.set(r.end,{at:r.end,side:direction===1?'long':direction===-1?'short':null,price:r.close,atr,stop:r.close-direction*distance,target:null,holdBars:2880,pattern:id,rank,
   reason:method.name+' · 완료된 4시간봉',exitLong,exitShort,trailLong:r.close-distance,trailShort:r.close+distance});
 }
 return out;
}
module.exports={METHODS,signals,supertrendStep};
