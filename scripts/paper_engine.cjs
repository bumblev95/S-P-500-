'use strict';
const S=require('../assets/simulation-signals.js'),E=require('../assets/perp-engine.js');
const CONFIG={crypto:{risk:.005,maxPositions:3,maxWeight:1/3,fee:.00045,slip:.0002,step:900000,warmup:65},stocks:{risk:.01,maxPositions:5,maxWeight:.2,fee:.0005,slip:.0005,step:86400000,warmup:205}};
const LEVERAGED={...CONFIG.crypto,profile:'leverage5x3x',profileVersion:'isolated-5x3x-risk-v1',leverage:{BTC:5,ETH:3,SOL:3},maxWeight:.2,maxMargin:.4,maxNotional:2,maxOpenRisk:.015,dailyLoss:.02,drawdownLimit:.10,lossStreak:3,cooldown:21600000,maintenance:.025};
const WIDE={...LEVERAGED,profile:'wideRecovery',profileVersion:'isolated-wide-recovery-v1',risk:.01,maxOpenRisk:.03,dailyLoss:.03,recovery:true,stopAtr:2,holdBars:32};
const PROFILES={leverage5x3x:LEVERAGED,wideRecovery:WIDE};
function config(a){if(a.profile&&a.profile!=='baseline'&&!PROFILES[a.profile])throw Error('Unknown account profile');const cfg=PROFILES[a.profile];if(cfg&&(a.asset!=='crypto'||a.profileVersion!==cfg.profileVersion))throw Error('Leverage profile version changed');return cfg||CONFIG[a.asset];}
const finite=Number.isFinite,side=p=>p.side==='long'?1:-1;
const copy=x=>JSON.parse(JSON.stringify(x));
function create(asset,at,profile){return {schemaVersion:1,version:S.VERSION,asset,...(profile?{profile,profileVersion:PROFILES[profile]?.profileVersion}:{}),createdAt:at,initial:10000,cash:10000,positions:[],pending:[],trades:[],events:[],curve:[],marks:{},lastProcessed:null,fees:0,funding:0,estimatedFundingHours:0,slippage:0,warnings:[],signals:[],highWater:10000,maxDrawdown:0,benchmark:null};}
function liquidation(p,cfg){return (p.entry-side(p)*p.margin/p.qty)/(1-side(p)*cfg.maintenance);}
function riskState(a,at,cfg){
 if(!cfg.profile)return;
 const day=Math.floor(at/86400000),eq=equity(a);
 if(a.riskDay!==day){a.riskDay=day;a.dayStartEquity=eq;a.dayBlocked=false;}
 if(eq<=a.dayStartEquity*(1-cfg.dailyLoss))a.dayBlocked=true;
 a.riskHighWater=Math.max(a.riskHighWater||10000,eq);
 const dd=1-eq/a.riskHighWater;
 if(cfg.recovery)a.riskMultiplier=dd>=.20?.25:dd>=.10?.5:1;
 else if(eq<=a.riskHighWater*(1-cfg.drawdownLimit))a.drawdownHalted=true;
 a.riskStatus=a.drawdownHalted?'고점 대비 10% 하락 · 신규 진입 중단':a.dayBlocked?'UTC 하루 손실 '+Math.round(cfg.dailyLoss*100)+'% · 다음 날까지 진입 중단':at<(a.cooldownUntil||0)?'3연속 손실 · 6시간 휴식':cfg.recovery&&a.riskMultiplier<1?'낙폭 회복 모드 · 거래 위험 '+(cfg.risk*a.riskMultiplier*100)+'%':'위험 한도 내 · 신호 대기';
}
function equity(a){return a.cash+a.positions.reduce((s,p)=>s+p.margin+side(p)*p.qty*((a.marks[p.symbol]??p.entry)-p.entry),0);}
function event(a,type,at,data){const e={id:a.asset+':'+a.events.length,type,at,...data};a.events.push(e);return e;}
function warn(a,message){if(!a.warnings.includes(message))a.warnings.push(message);}
function close(a,p,raw,at,reason,cfg,recordedAt,precision='bar'){
 const exit=raw*(1-side(p)*cfg.slip),gross=side(p)*p.qty*(exit-p.entry),fee=p.qty*exit*cfg.fee;
 const adjustment=cfg.profile?Math.max(0,-(p.margin+gross-fee)):0;
 a.cash+=p.margin+gross-fee+adjustment;a.fees+=fee;a.slippage+=Math.abs(exit-raw)*p.qty;
 if(adjustment){a.isolatedLossAdjustment=(a.isolatedLossAdjustment||0)+adjustment;warn(a,'격리 증거금 초과 손실은 가상 한도로 제한: 실제 청산·보험기금과 다를 수 있음');}
 const t={...p,exit,exitAt:at,exitReason:reason,gross,exitFee:fee,net:gross-p.entryFee-fee-p.funding+adjustment,...(cfg.profile?{isolatedLossAdjustment:adjustment}:{}),recordedAt,timePrecision:precision};
 a.trades.push(t);a.positions=a.positions.filter(x=>x.id!==p.id);
 event(a,'exit',at,{symbol:p.symbol,side:p.side,price:exit,qty:p.qty,reason,net:t.net,tradeId:p.id,recordedAt,timePrecision:precision});
 if(cfg.profile){a.consecutiveLosses=t.net<0?(a.consecutiveLosses||0)+1:0;if(a.consecutiveLosses>=cfg.lossStreak){a.cooldownUntil=at+cfg.cooldown;a.consecutiveLosses=0;}riskState(a,at,cfg);}
}
function funding(a,p,through,source,mark,uncertain=false){
 if(a.asset!=='crypto')return;
 let hour=Math.floor(Math.max(p.entryAt,p.fundingThrough)/3600000)*3600000;
 const rates=source._funding||(source._funding=new Map((source.funding||[]).map(r=>[Math.floor(r.time/3600000)*3600000,r])));
 if(source.fundingSchedule==='published'&&!source._nonFundingHours){source._nonFundingHours=new Set();const rows=source.funding||[];for(let i=1;i<rows.length;i++){const p=rows[i-1],n=rows[i],ph=Math.floor(p.time/3600000)*3600000,nh=Math.floor(n.time/3600000)*3600000,interval=n.intervalHours*3600000;if(nh-ph===interval&&Math.abs(n.time-p.time-interval)<=60000)for(let h=ph+3600000;h<nh;h+=3600000)source._nonFundingHours.add(h);}}
 for(;hour<=through;hour+=3600000){
  const observed=rates.get(hour),t=observed?.time??hour;
  if(t<=p.entryAt||t<=p.fundingThrough||t>through)continue;
  if(!observed&&source._nonFundingHours?.has(hour))continue;
  let rate=observed?.rate,estimated=!finite(rate);
  // Missing rates are charged conservatively, never silently replaced by zero.
  let cost=estimated?p.qty*mark*.0001:side(p)*p.qty*mark*rate;
  if(uncertain&&cost<0)cost=0;
  if(PROFILES[a.profile])p.margin-=cost;else a.cash-=cost;a.funding+=cost;p.funding+=cost;
  if(estimated){a.estimatedFundingHours++;warn(a,'일부 펀딩 누락: 시간당 0.01% 지급 가정 포함');}
 }
 p.fundingThrough=through;
}
function enter(a,order,bar,cfg,recordedAt){
 if(cfg.profile){riskState(a,bar.t,cfg);if(a.drawdownHalted||a.dayBlocked||bar.t<(a.cooldownUntil||0))return a.riskStatus;}
 if(a.positions.length>=cfg.maxPositions||a.positions.some(p=>p.symbol===order.symbol))return '포지션 한도';
 if(a.asset==='stocks'&&a.positions.filter(p=>p.sector===order.sector).length>=2)return '동일 업종 2종목 한도';
 const sign=side(order),entry=bar.open*(1+sign*cfg.slip);
 if(Math.abs(bar.open-order.price)>.5*order.atr)return '신호 가격에서 0.5 ATR 이상 이탈';
 const stopFill=order.stop*(1-sign*cfg.slip),targetFill=order.target*(1-sign*cfg.slip);
 const risk=sign*(entry-stopFill)+cfg.fee*(entry+stopFill)+(a.asset==='crypto'?entry*.0001*(cfg.recovery?order.holdBars/4:2):0),reward=sign*(targetFill-entry)-cfg.fee*(entry+targetFill);
 if(!(risk>0)||reward/risk<1.3||sign*(entry-order.stop)<=0||sign*(order.target-entry)<=0)return '비용 반영 손익비 또는 가격 조건 미충족';
 const eq=equity(a);if(eq<=0||a.cash<=0)return '가상 자본 부족';
 const leverage=cfg.profile?cfg.leverage[order.symbol]:1;if(!leverage)return '지원하지 않는 배율 종목';
 let qty=Math.min(eq*cfg.risk*(a.riskMultiplier||1)/risk,eq*cfg.maxWeight*leverage/entry,a.cash/(entry*(1/leverage+cfg.fee)));
 if(cfg.profile){
  const margins=a.positions.reduce((s,p)=>s+Math.max(0,p.margin),0),notional=a.positions.reduce((s,p)=>s+p.qty*(a.marks[p.symbol]??p.entry),0),openRisk=a.positions.reduce((s,p)=>s+(p.riskBudget||0),0);
  qty=Math.min(qty,Math.max(0,eq*cfg.maxMargin-margins)*leverage/entry,Math.max(0,eq*cfg.maxNotional-notional)/entry,Math.max(0,eq*cfg.maxOpenRisk*(a.riskMultiplier||1)-openRisk)/risk);
  const liq=liquidation({entry,side:order.side,margin:entry/leverage,qty:1},cfg);
  if(sign*(order.stop-liq)<Math.max(2*order.atr,entry*.01))return '손절과 가상 청산 기준 사이 여유 부족';
 }
 qty=a.asset==='stocks'?Math.floor(qty):Math.floor(qty*1e8)/1e8;
 if(!(qty>0))return '가상 자본 또는 최소 수량 부족';
 const margin=qty*entry/leverage,fee=qty*entry*cfg.fee;
 a.cash-=margin+fee;a.fees+=fee;a.slippage+=Math.abs(entry-bar.open)*qty;
 const p={id:order.id,symbol:order.symbol,sector:order.sector,side:order.side,pattern:order.pattern,reason:order.reason,signalAt:order.at,orderCreatedAt:order.createdAt,entryAt:bar.t,entry,qty,margin,stop:order.stop,target:order.target,entryFee:fee,funding:0,fundingThrough:bar.t,bars:0,holdBars:order.holdBars,recordedAt};
 if(cfg.profile){Object.assign(p,{leverage,initialMargin:margin,riskBudget:qty*risk,maintenance:cfg.maintenance});p.liquidation=liquidation(p,cfg);}
 a.positions.push(p);event(a,'entry',bar.t,{symbol:p.symbol,side:p.side,price:entry,qty,reason:p.reason,pattern:p.pattern,tradeId:p.id,stop:p.stop,target:p.target,recordedAt});return null;
}
function indexMarkets(market,asset){
 const raw=market[asset]||{},out={};
 for(const [symbol,source] of Object.entries(raw)){
  const rows=(asset==='crypto'?source.frames?.['15m']:source.rows)||[];
  if(!rows.length)continue;
  out[symbol]={source,rows,byTime:new Map(rows.map((r,i)=>[r.t,i]))};
 }
 return out;
}
function signalAt(m,symbol,index,asset,all,provider){
 const rows=m.rows.slice(Math.max(0,index-260),index+1),last=rows.at(-1);
 if(provider)return provider(symbol,rows,asset);
 if(asset==='crypto')return S.crypto(rows,m.source.frames?.['1h']||[]);
 if(symbol==='SPY')return {side:null,reason:'시장 비교 기준',at:last.end};
 return S.stock(rows,(all.SPY?.rows||[]).filter(r=>r.end<=last.end).slice(-260));
}
function queue(a,candidates,at,mode,cfg,now){
 const ordered=candidates.filter(q=>q.side&&!a.positions.some(p=>p.symbol===q.symbol)&&!a.pending.some(p=>p.symbol===q.symbol)).sort((x,y)=>y.rank-x.rank||x.symbol.localeCompare(y.symbol));
 for(const q of ordered){
  const id=[S.VERSION,...(cfg.profile?[cfg.profileVersion]:[]),a.asset,q.symbol,q.at,q.side].join(':');
  if(a.events.some(e=>e.type==='signal'&&e.signalId===id))continue;
  const createdAt=mode==='forward'?now:at;
  const expires=q.at+(a.asset==='crypto'?cfg.step*2:5*86400000);
  if(createdAt>=expires)continue;
  const order={...q,id,createdAt,notBefore:Math.max(createdAt,q.at+1),expires};a.pending.push(order);
  event(a,'signal',createdAt,{signalId:id,symbol:q.symbol,side:q.side,pattern:q.pattern,reason:q.reason,price:q.price,stop:q.stop,target:q.target,signalAt:q.at,recordedAt:now});
 }
}
function signalList(a,markets,asset,at,now,mode,provider){
 const candidates=[];
 for(const [symbol,m] of Object.entries(markets)){
  let i=m.byTime.get(at);if(i===undefined)continue;
  const r=m.rows[i];let q=signalAt(m,symbol,i,asset,markets,provider);
  if(a.profile==='wideRecovery')q=S.wide(q);
  if(mode==='forward'){
   const age=now-r.end,limit=asset==='crypto'?900000:5*86400000;
   if(age<0||age>limit)q={side:null,at:r.end,reason:'자료가 오래되어 신규 신호 보류'};
   if(m.source.revisions?.length)q={side:null,at:r.end,reason:'과거 가격 수정·분할 확인 필요'};
   if(m.source.errors?.length)q={side:null,at:r.end,reason:'시장 자료 수집 오류 · 신규 신호 보류'};
  }
  candidates.push({...q,symbol,sector:m.source.sector||'코인'});
 }
 return candidates;
}
function run(state,market,{mode='forward',now=Date.now(),provider,startAt}={}){
 const a=copy(state),cfg=config(a);if(a.version!==S.VERSION)throw Error('Strategy version changed: create a separate experiment, never reset an existing account');
 const markets=indexMarkets(market,a.asset),reference=markets[a.asset==='stocks'?'SPY':'BTC'];
 if(!reference){warn(a,'시장 기준 데이터 없음 · 운용 보류');return a;}
 const times=reference.rows.filter(r=>r.end<now).map(r=>r.t),end=times.at(-1);
 if(end===undefined)return a;
 const endBar=reference.rows[reference.byTime.get(end)];
 if(a.lastProcessed===null){
  const start=mode==='forward'?end:startAt?times.find(t=>t>=startAt):times[Math.min(cfg.warmup,times.length-1)];
  if(start===undefined)return a;
  a.lastProcessed=start;a.startedAt=mode==='forward'?now:reference.rows[reference.byTime.get(start)].end;
  const rb=reference.rows[reference.byTime.get(start)];a.benchmark={symbol:a.asset==='stocks'?'SPY':'BTC',price:rb.close,qty:10000/(rb.close*(1+cfg.slip)*(1+cfg.fee)),at:a.startedAt};
  a.curve.push({at:a.startedAt,equity:10000,benchmark:a.benchmark.qty*rb.close,cash:10000,exposure:0});
  riskState(a,a.startedAt,cfg);
  for(const [sym,m] of Object.entries(markets)){const i=m.byTime.get(start);if(i!==undefined)a.marks[sym]=m.rows[i].close;}
  const initial=signalList(a,markets,a.asset,start,now,mode,provider);a.signals=initial;queue(a,initial,a.startedAt,mode,cfg,now);
 }
 const newTimes=times.filter(t=>t>a.lastProcessed);
 for(const t of newTimes){
  if(a.asset==='crypto'&&t-a.lastProcessed>cfg.step){a.incompleteExecution=true;warn(a,'운용 중 15분봉 공백 · 해당 구간 체결 성적은 불확실');}
  const bars={};for(const [symbol,m] of Object.entries(markets)){
   if(mode==='forward'&&m.source.revisions?.length){warn(a,symbol+' 가격 수정·분할 감지: 보유 평가와 체결 동결, 확인 필요');a.incompleteExecution=true;continue;}
   const i=m.byTime.get(t);if(i!==undefined&&m.rows[i].end<now)bars[symbol]=m.rows[i];
  }
  const barEnd=reference.rows[reference.byTime.get(t)].end;
  // Establish UTC day's opening equity from the previous completed valuation.
  riskState(a,t,cfg);
  // Opening prices only: do not finance an opening purchase with a later stop/target sale.
  for(const [symbol,r] of Object.entries(bars))a.marks[symbol]=r.open;
  for(const p of [...a.positions]){
   const r=bars[p.symbol];if(!r){warn(a,p.symbol+' 보유 중 봉 누락 · 평가에 제한');continue;}
   const m=markets[p.symbol];funding(a,p,r.t,m.source,r.open);
   const stopGap=side(p)*(r.open-p.stop)<=0,targetGap=side(p)*(r.open-p.target)>=0;
   if(cfg.profile&&side(p)*(r.open-liquidation(p,cfg))<=0)close(a,p,r.open,r.t,'가상 격리 청산 · 시가 갭',cfg,now,'open');
   else if(stopGap)close(a,p,r.open,r.t,'손절 · 시가 갭',cfg,now,'open');
   else if(targetGap)close(a,p,p.target,r.t,'익절 · 시가 목표 통과',cfg,now,'open');
   else if(p.exitPending)close(a,p,r.open,r.t,p.exitPending,cfg,now,'open');
  }
  const keep=[];
  for(const order of a.pending){
   if(t>order.expires){event(a,'cancel',t,{symbol:order.symbol,reason:'신호 유효기간 만료',signalId:order.id,recordedAt:now});continue;}
   const r=bars[order.symbol];if(t<order.notBefore||!r){keep.push(order);continue;}
   const reason=enter(a,order,r,cfg,now);
   if(reason)event(a,'cancel',t,{symbol:order.symbol,reason,signalId:order.id,recordedAt:now});
  }
  a.pending=keep;
  for(const p of [...a.positions]){
   const r=bars[p.symbol];if(!r)continue;p.bars++;
   const stop=p.side==='long'?r.low<=p.stop:r.high>=p.stop,target=p.side==='long'?r.high>=p.target:r.low<=p.target;
   const closing=stop||target||p.bars>=p.holdBars;
   funding(a,p,r.end,markets[p.symbol].source,r.open,stop||target);
   if(cfg.profile){p.liquidation=liquidation(p,cfg);const liquid=p.side==='long'?r.low<=p.liquidation:r.high>=p.liquidation;
    if(liquid&&(!stop||side(p)*(p.stop-p.liquidation)<=0)){close(a,p,p.liquidation,r.end,'가상 격리 청산 · 봉 가격 기준',cfg,now);continue;}}
   if(closing){close(a,p,stop?p.stop:target?p.target:r.close,r.end,stop?(target?'손절 · 같은 봉 목표 동시 도달':'손절'):target?'익절 · 2R 목표':'보유 시간 종료',cfg,now,stop||target?'bar':'close');continue;}
   if(a.asset==='stocks'){
    const m=markets[p.symbol],i=m.byTime.get(t),ind=E.indicators(m.rows.slice(Math.max(0,i-239),i+1),'1d');
    if(ind&&r.close<ind.ema50)p.exitPending='추세 이탈 · 50일 EMA';
   }
  }
  for(const [symbol,r] of Object.entries(bars))a.marks[symbol]=r.close;
  const eq=equity(a);a.highWater=Math.max(a.highWater,eq);a.maxDrawdown=Math.max(a.maxDrawdown,1-eq/a.highWater);
  riskState(a,barEnd,cfg);
  if(eq<=0)warn(a,'가상 계좌 자본 소진 · 신규 주문 중단');
  const benchmark=a.benchmark.qty*reference.rows[reference.byTime.get(t)].close;
  a.curve.push({at:barEnd,equity:eq,benchmark,cash:a.cash,exposure:a.positions.reduce((s,p)=>s+p.qty*(a.marks[p.symbol]??p.entry),0)});
  a.lastProcessed=t;
  if(mode==='replay'&&eq>0){const candidates=signalList(a,markets,a.asset,t,now,mode,provider);a.signals=candidates;queue(a,candidates,barEnd,mode,cfg,now);}
 }
 // Only the latest actually observed signal can create a new forward order.
 // Catch-up candles may settle already-posted orders, never invent old signals.
 if(mode==='forward'){
  a.signals=signalList(a,markets,a.asset,end,now,mode,provider);
  if(equity(a)>0)queue(a,a.signals,now,mode,cfg,now);
 }
 a.updatedAt=now;a.marketAsOf=endBar.end;a.equity=equity(a);
 if(mode==='forward'&&now-endBar.end>(a.asset==='crypto'?1800000:5*86400000))warn(a,'현재 가격 데이터 지연 · 과거 평가액 표시');
 return a;
}
function report(a){
 const net=a.trades.map(t=>t.net),wins=net.filter(x=>x>0),losses=net.filter(x=>x<0),grossProfit=wins.reduce((s,x)=>s+x,0),grossLoss=-losses.reduce((s,x)=>s+x,0);
 const groups={};for(const p of ['retest','candle','falseBreak','portfolioTrend']){
  const rows=a.trades.filter(t=>t.pattern===p);if(rows.length)groups[p]={trades:rows.length,wins:rows.filter(t=>t.net>0).length,net:rows.reduce((s,t)=>s+t.net,0)};
 }
 return {...a,equity:equity(a),return:equity(a)/a.initial-1,realized:net.reduce((s,x)=>s+x,0),unrealized:a.positions.reduce((s,p)=>s+side(p)*p.qty*((a.marks[p.symbol]??p.entry)-p.entry),0),winRate:net.length?wins.length/net.length:null,profitFactor:grossLoss?grossProfit/grossLoss:null,averageTrade:net.length?net.reduce((s,x)=>s+x,0)/net.length:null,patternResults:groups,positions:a.positions.map(p=>({...p,mark:a.marks[p.symbol]??p.entry,unrealized:side(p)*p.qty*((a.marks[p.symbol]??p.entry)-p.entry)}))};
}
module.exports={create,run,report,equity,enter,close,funding,CONFIG,LEVERAGED,WIDE,config,liquidation,riskState};
