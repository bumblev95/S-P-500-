(function(root){
'use strict';
const E=typeof module!=='undefined'?require('./perp-engine.js'):root.PerpEngine;
const VERSION='paper-pattern-portfolio-v1',STEP=900000;
const mean=a=>a.reduce((s,x)=>s+x,0)/a.length;
function completed(rows,end,limit=240){let lo=0,hi=rows.length;while(lo<hi){const mid=(lo+hi)>>1;if(rows[mid].end<=end)lo=mid+1;else hi=mid;}return rows.slice(Math.max(0,lo-limit),lo);}
function wide(q){if(!q.side||q.wide)return q;const sign=q.side==='long'?1:-1,risk=Math.max(Math.abs(q.price-q.stop),2*q.atr);return {...q,wide:true,stop:q.price-sign*risk,target:q.price+sign*2*risk,holdBars:32,reason:q.reason+' · 넓은 손절·8시간 실험'};}
function crypto(rows,higher){
 const last=rows.at(-1),wait=reason=>({side:null,reason,at:last?.end});
 if(rows.length<65||!last)return wait('완료된 15분봉 65개 필요');
 const recent=rows.slice(-65);if(recent.some((r,i)=>i&&r.t-recent[i-1].t!==STEP))return wait('15분봉 누락');
 higher=completed(higher,last.end);
 if(higher.length<60||last.end-higher.at(-1).end>=3600000)return wait('완료된 1시간봉 자료 확인 필요');
 const a=E.indicators(rows.slice(-240),'15m'),hi=E.indicators(higher,'1h');
 if(!a||!hi||!(a.atr>0)||a.atr/last.close>.035)return wait('변동성 조건 미충족');
 const prior=rows.slice(-21,-1),high=Math.max(...prior.map(r=>r.high)),low=Math.min(...prior.map(r=>r.low));
 const box=rows.slice(-26,-6),top=Math.max(...box.map(r=>r.high)),bottom=Math.min(...box.map(r=>r.low));
 const prev=rows.at(-2),body=Math.abs(last.close-last.open),range=last.high-last.low;
 const lower=Math.min(last.close,last.open)-last.low,upper=last.high-Math.max(last.close,last.open);
 const bull=last.close>last.open,bear=last.close<last.open;
 const engulfUp=bull&&prev.close<prev.open&&last.open<=prev.close&&last.close>=prev.open;
 const engulfDown=bear&&prev.close>prev.open&&last.open>=prev.close&&last.close<=prev.open;
 const pinUp=range>0&&lower/range>=.55&&body/range<=.35&&last.close>last.low+range*.65;
 const pinDown=range>0&&upper/range>=.55&&body/range<=.35&&last.close<last.high-range*.65;
 let side=null,pattern=null,reason=null;
 const breakout=rows.slice(-6,-1);
 if(hi.bias==='long'&&breakout.some(r=>r.close>top)&&last.low<=top+.2*a.atr&&last.close>top&&bull&&a.relativeVolume>=.8){side='long';pattern='retest';reason='상단 돌파 가격대 재확인 · 1시간 상승';}
 else if(hi.bias==='short'&&breakout.some(r=>r.close<bottom)&&last.high>=bottom-.2*a.atr&&last.close<bottom&&bear&&a.relativeVolume>=.8){side='short';pattern='retest';reason='하단 이탈 가격대 재확인 · 1시간 하락';}
 else if(hi.bias==='long'&&last.low<=low+.35*a.atr&&last.close>low&&(engulfUp||pinUp)&&a.relativeVolume>=.8){side='long';pattern='candle';reason='지지 부근 '+(engulfUp?'상승 장악형':'아래꼬리 핀바');}
 else if(hi.bias==='short'&&last.high>=high-.35*a.atr&&last.close<high&&(engulfDown||pinDown)&&a.relativeVolume>=.8){side='short';pattern='candle';reason='저항 부근 '+(engulfDown?'하락 장악형':'위꼬리 핀바');}
 else if(a.efficiency<.35&&last.low<low&&last.close>low&&bull&&lower/range>.4&&hi.bias!=='short'&&a.relativeVolume>=.8){side='long';pattern='falseBreak';reason='횡보 하단 이탈 후 범위 복귀';}
 else if(a.efficiency<.35&&last.high>high&&last.close<high&&bear&&upper/range>.4&&hi.bias!=='long'&&a.relativeVolume>=.8){side='short';pattern='falseBreak';reason='횡보 상단 돌파 후 범위 복귀';}
 if(!side)return wait('세 가지 실험 패턴의 확인 조건 대기');
 if(side==='long'&&a.rsi>75||side==='short'&&a.rsi<25)return wait('단기 과열로 추격 보류');
 const raw=side==='long'?last.close-(Math.min(last.low,prev.low)-.2*a.atr):(Math.max(last.high,prev.high)+.2*a.atr)-last.close;
 const risk=Math.max(raw,.7*a.atr);if(risk>3*a.atr)return wait('손절 폭이 3 ATR 초과');
 const sign=side==='long'?1:-1,stop=last.close-sign*risk,target=last.close+sign*2*risk;
 if(stop<=0||target<=0)return wait('가격 범위 오류');
 return {side,pattern,reason,at:last.end,price:last.close,stop,target,atr:a.atr,rank:a.relativeVolume,holdBars:8};
}
function stock(rows,market){
 const last=rows.at(-1),wait=reason=>({side:null,reason,at:last?.end});
 if(rows.length<205||!last)return wait('200일선 계산 이력 부족');
 market=market.filter(r=>r.end<=last.end);
 if(market.length<200||market.at(-1).date!==last.date)return wait('같은 거래일 SPY 자료 부족');
 if(market.at(-1).close<=mean(market.slice(-200).map(r=>r.close)))return wait('SPY 200일선 아래 · 신규 진입 대기');
 const a=E.indicators(rows.slice(-240),'1d'),ma=mean(rows.slice(-200).map(r=>r.close)),momentum=last.close/rows.at(-64).close-1;
 if(!a||!(a.atr>0)||last.close<=ma||a.ema20<=a.ema50||last.close<=a.ema50||momentum<=0)return wait('상승 추세 조건 대기');
 if(a.rsi<45||a.rsi>72)return wait('RSI 45–72 범위 대기');
 const previous=Math.max(...rows.slice(-21,-1).map(r=>r.close));
 const pullback=last.low<=a.ema20+a.atr*.35&&last.close>a.ema20&&last.close>last.open;
 if(!pullback&&last.close<=previous)return wait('눌림 반등 또는 20일 종가 돌파 대기');
 const risk=2*a.atr;if(risk/last.close>.12)return wait('종목 손절 폭 12% 초과');
 return {side:'long',pattern:'portfolioTrend',reason:pullback?'상승 추세 · 20일선 눌림 반등':'상승 추세 · 20일 종가 돌파',at:last.end,price:last.close,stop:last.close-risk,target:last.close+2*risk,atr:a.atr,rank:momentum/(a.atr/last.close),holdBars:84};
}
const api={VERSION,STEP,crypto,stock,completed,wide};if(typeof module!=='undefined')module.exports=api;else root.SimulationSignals=api;
})(typeof window!=='undefined'?window:globalThis);
