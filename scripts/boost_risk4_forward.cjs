'use strict';
// Forward-only account. Frozen research code and existing paper accounts are untouched.
const B=require('./momentum_boost.cjs'),E=require('./leverage_engine.cjs');
const STEP=900000,HOUR=3600000,H4=4*HOUR;
const CONFIG=Object.freeze({profile:'momentumBoost5xRisk4',profileVersion:'boost-5x-risk4-forward-v1',risk:.04,leverage:5,maxPositions:1,maxMargin:.9,volumeParticipation:.005,maintenance:.025,fee:.00045,slip:.0002,maxBars:2880,signalTtl:H4,initial:10000,floor:100,modelSha256:B.MODEL_SHA256});
const copy=x=>JSON.parse(JSON.stringify(x)),sign=p=>p.side==='long'?1:-1;
function create(now){return {profile:CONFIG.profile,profileVersion:CONFIG.profileVersion,modelSha256:B.MODEL_SHA256,createdAt:now,startedAt:now,initial:10000,cash:10000,positions:[],pending:[],trades:[],events:[],curve:[],marks:{},signals:[],lastObserved:{},lastProcessed:null,highWater:10000,maxDrawdown:0,fees:0,funding:0,slippage:0,estimatedFundingHours:0,warnings:[]};}
const equity=a=>a.cash+a.positions.reduce((s,p)=>s+p.margin+sign(p)*p.qty*((a.marks[p.symbol]??p.entry)-p.entry),0);
const liq=p=>E.liquidation({...p,side:sign(p)},CONFIG.maintenance);
const emit=(a,type,at,details={})=>a.events.push({id:CONFIG.profile+':'+a.events.length,type,at,...details});
const warn=(a,text)=>{if(!a.warnings.includes(text))a.warnings.push(text);};
function mark(a,value){a.highWater=Math.max(a.highWater,value);a.maxDrawdown=Math.max(a.maxDrawdown,1-Math.max(0,value)/a.highWater);}
function close(a,p,raw,at,reason,now,liquidation=false){
 const exit=raw*(1-sign(p)*CONFIG.slip),gross=sign(p)*p.qty*(exit-p.entry),fee=liquidation?0:p.qty*exit*CONFIG.fee;
 a.cash+=liquidation?0:Math.max(0,p.margin+gross-fee);a.fees+=fee;a.slippage+=liquidation?0:p.qty*Math.abs(exit-raw);
 const net=a.cash-p.startEquity,t={...p,exit,exitAt:at,exitReason:reason,net,netR:net/p.riskBudget,gross,exitFee:fee,liquidation,recordedAt:now};
 delete t.pendingStop;delete t.exitPending;a.trades.push(t);a.positions=[];emit(a,'exit',at,{symbol:p.symbol,side:p.side,price:exit,net,reason,tradeId:p.id,recordedAt:now});mark(a,a.cash);
}
function enter(a,q,b,now){
 if(a.positions.length||a.cash<CONFIG.floor)return '보유 한도 또는 잔고 1% 미만';
 const s=sign(q),entry=b.open*(1+s*CONFIG.slip);
 if(s*(entry-q.stop)<=0||Math.abs(entry-q.price)>.5*Math.abs(q.price-q.stop))return '진입 가격·손절 거리 조건 미충족';
 const wanted=E.size(a.cash,entry,q.stop,CONFIG.leverage,{risk:CONFIG.risk},CONFIG.fee,CONFIG.slip),qty=Math.min(wanted,q.liquidityQty),margin=qty*entry/CONFIG.leverage;
 if(!(qty>0))return '거래량·자금 부족';
 const p={...q,entry,qty,margin};if(s*(q.stop-liq(p))<=0)return '손절선이 추정 강제청산선 너머';
 const fee=qty*entry*CONFIG.fee,riskBudget=qty*(Math.abs(entry-q.stop*(1-s*CONFIG.slip))+CONFIG.fee*(entry+q.stop));
 Object.assign(p,{startEquity:a.cash,entryAt:b.t,entryFee:fee,riskBudget,initialMargin:margin,leverage:5,funding:0,fundingThrough:b.t,bars:0,recordedAt:now,capacityCapped:qty<wanted,liquidation:liq(p)});
 a.cash-=margin+fee;a.fees+=fee;a.slippage+=qty*Math.abs(entry-b.open);a.positions=[p];
 emit(a,'entry',b.t,{symbol:q.symbol,side:q.side,price:entry,qty,margin,riskBudget,tradeId:q.id,recordedAt:now});return null;
}
function settleFunding(a,p,through,prices,rates){
 for(let at=Math.floor(p.fundingThrough/HOUR)*HOUR+HOUR;at<=through;at+=HOUR){
  const rate=rates.get(at),estimated=!Number.isFinite(rate),cost=estimated?p.qty*prices*.0001:sign(p)*p.qty*prices*rate;
  p.margin-=cost;p.funding+=cost;a.funding+=cost;
  if(estimated){a.estimatedFundingHours++;warn(a,'펀딩 일부 누락 · 누락 정시마다 명목금액 0.01% 지급 가정');}
 }
 p.fundingThrough=through;
}
function run(previous,market,now=Date.now(),testFeed){
 const a=copy(previous);if(a.profileVersion!==CONFIG.profileVersion||a.profile!==CONFIG.profile||a.modelSha256!==B.MODEL_SHA256)throw Error('Preserve existing account identity');
 const symbols=['BTC','ETH','SOL'].filter(s=>market.crypto?.[s]),sources={};
 for(const s of symbols){const v=market.crypto[s],rows=(v.frames?.['15m']||[]).filter(r=>r.end<now);sources[s]={...v,rows,byTime:new Map(rows.map(r=>[r.t,r])),rates:new Map((v.funding||[]).filter(f=>f.time<now).map(f=>[Math.round(f.time/HOUR)*HOUR,f.rate]))};}
 if(!symbols.length||symbols.some(s=>!sources[s].rows.length)||a.positions.some(p=>!sources[p.symbol])||(!testFeed&&symbols.length!==3)){warn(a,'완료 가격 자료 대기');a.updatedAt=now;a.riskStatus='가격 자료 대기 · 체결 보류';return a;}
 const end=Math.min(...symbols.map(s=>sources[s].rows.at(-1).t)),endAt=end+STEP-1;
 if(a.lastProcessed===null){a.lastProcessed=end;for(const s of symbols)a.marks[s]=sources[s].byTime.get(end)?.close??sources[s].rows.at(-1).close;a.curve.push({at:now,equity:10000});emit(a,'start',now,{initial:10000,recordedAt:now});}
 a.executionBlocked=false;
 if(symbols.some(s=>sources[s].revisions?.length)){a.executionBlocked=true;warn(a,'가격 수정 감지 · 새 계좌의 체결 보류');}
 for(let t=a.lastProcessed+STEP;t<=end&&!a.executionBlocked;t+=STEP){
  if(symbols.some(s=>!sources[s].byTime.has(t))){a.executionBlocked=true;warn(a,'운용 중 15분봉 공백 · 자료 복구까지 체결 보류');break;}
  const bars=Object.fromEntries(symbols.map(s=>[s,sources[s].byTime.get(t)]));
  for(const s of symbols)a.marks[s]=bars[s].open;
  let p=a.positions[0];
  if(p){const b=bars[p.symbol];if(p.pendingStop&&t>=p.pendingStop.notBefore){p.stop=p.pendingStop.price;delete p.pendingStop;}
   settleFunding(a,p,t,b.open,sources[p.symbol].rates);
   if(p.margin<=0||sign(p)*(b.open-liq(p))<=0)close(a,p,b.open,t,'가상 격리 강제청산 · 시가',now,true);
   else if(sign(p)*(b.open-p.stop)<=0)close(a,p,b.open,t,'손절 · 시가 갭',now);
   else if(p.exitPending&&t>=p.exitPending.notBefore)close(a,p,b.open,t,'14일 모멘텀 반전',now);
  }
  const keep=[];for(const q of a.pending){if(t>q.expires)emit(a,'cancel',t,{symbol:q.symbol,reason:'신호 만료',recordedAt:now});else if(t<q.notBefore)keep.push(q);else{const reason=enter(a,q,bars[q.symbol],now);if(reason)emit(a,'cancel',t,{symbol:q.symbol,reason,recordedAt:now});}}a.pending=keep;
  p=a.positions[0];if(p){const b=bars[p.symbol],s=sign(p),adverse=s>0?b.low:b.high,l=liq(p),stop=s*(adverse-p.stop)<=0,liquid=s*(adverse-l)<=0;p.bars++;
   if(liquid&&(!stop||s*(l-p.stop)>=0)){mark(a,a.cash);close(a,p,l,b.end,'가상 격리 강제청산',now,true);}
   else if(stop){mark(a,Math.max(a.cash,a.cash+p.margin+s*p.qty*(p.stop-p.entry)));close(a,p,p.stop,b.end,'추적 손절',now);}
   else{mark(a,a.cash+p.margin+s*p.qty*(adverse-p.entry));if(p.bars>=CONFIG.maxBars)close(a,p,b.close,b.end,'30일 보유 종료',now);}
  }
  for(const s of symbols)a.marks[s]=bars[s].close;mark(a,equity(a));a.curve.push({at:t+STEP-1,equity:equity(a)});a.lastProcessed=t;
 }
 a.marketAsOf=a.lastProcessed+STEP-1;a.updatedAt=now;
 const fresh=!a.executionBlocked&&now-endAt<=2*STEP;
 const completed={crypto:Object.fromEntries(symbols.map(s=>[s,{...sources[s],frames:{'15m':sources[s].rows.filter(r=>r.t<=end)}}]))};
 const provider=testFeed||B.providers(completed,'momentumBoostOne').forward;
 a.signals=symbols.map(symbol=>{const rows=completed.crypto[symbol].frames['15m'],q=provider(symbol,rows),stamp=q.indicatorAt??q.at;
  const signalIndex=rows.findIndex(r=>r.end===stamp),b=rows[signalIndex],window=rows.slice(Math.max(0,signalIndex-32),signalIndex),avg=window.length?window.reduce((s,r)=>s+r.volume,0)/window.length:0;
  const stale=!fresh||!Number.isFinite(stamp)||stamp>endAt||stamp>=now||now-stamp>=H4||q.stale;
  return {...q,symbol,indicatorAt:stamp,observedAt:now,side:stale?null:q.side,stale,liquidityQty:b?.volume>0?CONFIG.volumeParticipation*Math.min(b.volume,avg):0,reason:stale?'현재 완료 봉·신호 자료 대기':q.reason};
 });
 if(fresh){
  const newSignals=a.signals.filter(q=>!q.stale&&q.indicatorAt>(a.lastObserved[q.symbol]??-Infinity));
  for(const q of newSignals){a.lastObserved[q.symbol]=q.indicatorAt;emit(a,'observation',now,{symbol:q.symbol,indicatorAt:q.indicatorAt,side:q.side,modelScore:q.modelScore,reason:q.reason,recordedAt:now});}
  const p=a.positions[0],q=p&&newSignals.find(q=>q.symbol===p.symbol);
  if(q){const s=sign(p),next=s>0?q.trailLong:q.trailShort,old=p.pendingStop?.price??p.stop;
   if(Number.isFinite(next)&&s*(next-old)>0){p.pendingStop={price:next,notBefore:now};emit(a,'stopUpdate',now,{symbol:p.symbol,price:next,notBefore:now,indicatorAt:q.indicatorAt,recordedAt:now});}
   if(s>0?q.exitLong:q.exitShort){p.exitPending={notBefore:now};emit(a,'exitSignal',now,{symbol:p.symbol,notBefore:now,indicatorAt:q.indicatorAt,recordedAt:now});}
  }
  if(!p&&!a.pending.length&&a.cash>=CONFIG.floor){
   const best=newSignals.filter(q=>q.side&&q.liquidityQty>0).sort((a,b)=>b.rank-a.rank||a.symbol.localeCompare(b.symbol))[0];
   if(best){const order={...best,id:CONFIG.profileVersion+':'+best.symbol+':'+best.indicatorAt,signalAt:best.indicatorAt,createdAt:now,notBefore:now,expires:best.indicatorAt+H4};a.pending=[order];emit(a,'signal',now,{symbol:best.symbol,side:best.side,price:best.price,stop:best.stop,notBefore:now,signalId:order.id,recordedAt:now});}
  }
 }
 for(const p of a.positions)p.liquidation=liq(p);
 a.riskStatus=a.executionBlocked?'자료 확인 대기 · 체결 보류':!fresh?'가격 자료 갱신 대기':a.cash<100&&!a.positions.length?'초기 자금의 1% 미만 · 신규 진입 중단':a.positions.length?'5배 포지션 보유 · 추적 손절 관리':a.pending.length?'조건 통과 · 기록 이후 다음 봉 체결 대기':'14일 흐름·3일 돌파·ML 조건 대기';
 const realized=a.trades.reduce((s,t)=>s+t.net,0),open=a.positions[0];
 const expected=10000+realized-(open?open.entryFee+open.funding:0)+(open?sign(open)*open.qty*((a.marks[open.symbol]??open.entry)-open.entry):0);
 if(Math.abs(equity(a)-expected)>Math.max(1e-6,equity(a)*1e-9))throw Error('Forward account reconciliation failed');
 if(a.trades.some(t=>t.entryAt<t.createdAt||t.entryAt<=t.signalAt))throw Error('Retroactive forward fill');return a;
}
function report(a){const wins=a.trades.filter(t=>t.net>0),losses=a.trades.filter(t=>t.net<0),loss=-losses.reduce((s,t)=>s+t.net,0);return {...a,equity:equity(a),return:equity(a)/10000-1,winRate:a.trades.length?wins.length/a.trades.length:null,profitFactor:loss?wins.reduce((s,t)=>s+t.net,0)/loss:null,realized:a.trades.reduce((s,t)=>s+t.net,0),positions:a.positions.map(p=>({...p,mark:a.marks[p.symbol]??p.entry,unrealized:sign(p)*p.qty*((a.marks[p.symbol]??p.entry)-p.entry)}))};}
module.exports={CONFIG,create,run,report,equity,enter,close};
