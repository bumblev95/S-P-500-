'use strict';
// Isolated-margin, one-position research engine. Does not touch live/paper account code.
const {STEP,DAY}=require('./leverage_methods.cjs');
const BASE_FEE=.00045,BASE_SLIP=.0002,INITIAL=10000;
function liquidation(p,maintenance=.025,markBuffer=0){
 const actual=(p.entry-p.side*p.margin/p.qty)/(1-p.side*maintenance);
 return actual/(1-p.side*markBuffer);
}
function size(equity,entry,stop,leverage,policy,fee,slip){
 const unitRisk=Math.abs(entry-stop*(1-(entry>stop?1:-1)*slip))+fee*(entry+stop);
 const marginFraction=policy.margin??.9;
 const byMargin=equity*marginFraction*leverage/entry;
 return Math.max(0,Math.min(policy.risk?equity*policy.risk/unitRisk:Infinity,byMargin,equity/(entry/leverage+entry*fee)));
}
function fundingGrid(rows,funding){
 const map=new Map(),first=rows[0].t,last=rows.at(-1).end,normalized=funding.map(f=>({...f,time:Math.round(f.time/3600000)*3600000})).sort((a,b)=>a.time-b.time);
 const put=(t,rate,estimated=false)=>{if(t<first||t>last)return;const i=Math.floor((t-first)/STEP),a=map.get(i)||{rate:0,estimated:0};a.rate+=rate;a.estimated+=estimated?1:0;map.set(i,a);};
 for(let j=0;j<normalized.length;j++){
  const f=normalized[j];put(f.time,f.rate);
  const next=normalized[j+1];if(next){const step=(next.intervalHours||8)*3600000;for(let t=f.time+step;t<next.time-60000;t+=step)put(t,.0001,true);}
 }
 // An unknown boundary is charged conservatively every eight hours.
 if(normalized.length){for(let t=Math.ceil(first/(8*3600000))*8*3600000;t<normalized[0].time;t+=8*3600000)put(t,.0001,true);for(let t=normalized.at(-1).time+8*3600000;t<=last;t+=8*3600000)put(t,.0001,true);}
 else for(let t=Math.ceil(first/(8*3600000))*8*3600000;t<=last;t+=8*3600000)put(t,.0001,true);
 return map;
}
function metrics(curve,trades,start,end,maxDrawdown,extras={},initialEquity=INITIAL){
 const equity=curve.at(-1)?.equity??initialEquity,returns=[];let previous=initialEquity;
 for(const p of curve){returns.push(p.equity/previous-1);previous=p.equity;}
 const avg=returns.reduce((s,v)=>s+v,0)/Math.max(1,returns.length),sd=Math.sqrt(returns.reduce((s,v)=>s+(v-avg)**2,0)/Math.max(1,returns.length-1));
 const wins=trades.filter(t=>t.net>0),losses=trades.filter(t=>t.net<0),gain=wins.reduce((s,t)=>s+t.net,0),loss=-losses.reduce((s,t)=>s+t.net,0);
 const mean=key=>trades.length?trades.reduce((s,t)=>s+t[key],0)/trades.length:0;
 return {equity,return:equity/initialEquity-1,cagr:Math.pow(equity/initialEquity,365.25*DAY/(end-start+1))-1,maxDrawdown,sharpe:sd?avg/sd*Math.sqrt(365.25):null,trades:trades.length,winRate:trades.length?wins.length/trades.length:null,profitFactor:loss?gain/loss:null,expectancyR:mean('netR'),averageHoldHours:mean('holdHours'),averageEntryMargin:mean('marginFraction'),averageEntryExposure:mean('exposure'),averageEntryRisk:mean('riskFraction'),liquidations:trades.filter(t=>t.reason==='liquidation').length,partialTrades:trades.filter(t=>t.partial).length,...extras};
}
function evaluate(data,method,policy,leverage,start,end,options={}){
 const fee=options.fee??BASE_FEE*(options.costStress?2:1),slip=options.slip??BASE_SLIP*(options.costStress?2:1),maintenance=options.maintenance??.025,buffer=options.markBuffer??0;
 const initialEquity=options.initialEquity??INITIAL;
 let cash=initialEquity,p=null,pending=null,high=initialEquity,minEquity=initialEquity,dd=0,fees=0,funding=0,slippage=0,estimatedFundingPayments=0,heldBars=0,maxExposure=0,skipped=0,capacityCapped=0,floor=initialEquity<100,streak=0,maxLossStreak=0;
 const trades=[],curve=[],base=data.start,startIndex=Math.ceil((start-base)/STEP),endIndex=Math.floor((end-base)/STEP);
 const row=(s,index)=>data.symbols[s].rows[index-data.symbols[s].offset];
 const signal=(s,index)=>data.symbols[s].prepared.events[method.id].get(index-data.symbols[s].offset);
 const feature=(s,k,index)=>data.symbols[s].prepared.features[k][index-data.symbols[s].offset];
 const equity=price=>cash+(p?p.margin+p.side*p.qty*(price-p.entry):0);
 function mark(value){if(!Number.isFinite(value))throw Error('Non-finite equity');high=Math.max(high,value);minEquity=Math.min(minEquity,value);dd=Math.max(dd,1-Math.max(0,value)/high);}
 function exit(raw,fraction,at,reason,isLiquidation=false){
  const qty=p.qty*fraction,margin=p.margin*fraction,fill=raw*(1-p.side*slip),gross=p.side*qty*(fill-p.entry),exitFee=isLiquidation?0:qty*fill*fee;
  let credit=isLiquidation?0:Math.max(0,margin+gross-exitFee);
  cash+=credit;fees+=exitFee;p.fees+=exitFee;slippage+=isLiquidation?0:qty*Math.abs(raw-fill);p.qty-=qty;p.margin-=margin;
  if(fraction<1){p.partial=true;p.stop=p.side>0?Math.max(p.stop,p.entry):Math.min(p.stop,p.entry);return;}
  const net=cash-p.startEquity;trades.push({symbol:p.symbol,side:p.side,signalAt:p.signalAt,entryAt:p.entryAt,exitAt:at,net,netR:net/p.riskBudget,reason,holdHours:(at-p.entryAt)/3600000,marginFraction:p.initialMargin/p.startEquity,exposure:p.initialNotional/p.startEquity,riskFraction:p.riskBudget/p.startEquity,partial:p.partial,fees:p.fees,funding:p.funding});
  streak=net<0?streak+1:0;maxLossStreak=Math.max(maxLossStreak,streak);p=null;
 }
 for(let index=startIndex;index<=endIndex;index++){
  const at=base+index*STEP,endAt=at+STEP-1;
  if(p){
   const b=row(p.symbol,index);if(!b)throw Error('Missing execution bar');
   const f=data.symbols[p.symbol].funding.get(index-data.symbols[p.symbol].offset);
   if(f){const cost=f.estimated?Math.abs(p.qty*b.open*f.rate):p.side*p.qty*b.open*f.rate;p.margin-=cost;p.funding+=cost;funding+=cost;estimatedFundingPayments+=f.estimated;}
   let liq=liquidation(p,maintenance,buffer);
   if(p.margin<=0||p.side*(b.open-liq)<=0)exit(b.open,1,at,'liquidation',true);
   else if(p.side*(b.open-p.stop)<=0)exit(b.open,1,at,'stop');
   else if(p.exitPending)exit(b.open,1,at,p.exitPending);
   else if(p.partialPending){exit(b.open,.5,at,'partial');if(p)p.partialPending=false;}
  }
  if(pending&&!p&&!floor){
   const q=pending,b=row(q.symbol,index);pending=null;
   if(b){const entry=b.open*(1+q.side*slip),wanted=size(cash,entry,q.stop,leverage,policy,fee,slip),qty=Math.min(wanted,q.liquidityQty??Infinity),margin=qty*entry/leverage;if(qty<wanted)capacityCapped++;
    const candidate={...q,entry,qty,margin};
    if(q.side*(entry-q.stop)>0&&Math.abs(entry-q.price)<=.5*Math.abs(q.price-q.stop)&&qty>0&&q.side*(q.stop-liquidation(candidate,maintenance,buffer))>0){
     const startEquity=cash,entryFee=qty*entry*fee,riskBudget=qty*(Math.abs(entry-q.stop*(1-q.side*slip))+fee*(entry+q.stop));
     cash-=margin+entryFee;fees+=entryFee;slippage+=qty*Math.abs(entry-b.open);
     p={...candidate,startEquity,initialMargin:margin,initialNotional:qty*entry,entryAt:at,signalAt:q.at,initialQty:qty,riskBudget,partial:false,funding:0,fees:entryFee,maxBars:method.kind==='단타'?32:q.exit==='q15'?15*96:30*96,target:q.target??(q.exit==='partial2r'?entry+q.side*2*Math.abs(entry-q.stop):null)};
    }else skipped++;
   }
  }else pending=null;
  if(p){
   heldBars++;const b=row(p.symbol,index),liq=liquidation(p,maintenance,buffer),adverse=p.side>0?b.low:b.high,favorable=p.side>0?b.high:b.low;
   const hitStop=p.side*(adverse-p.stop)<=0,hitLiq=p.side*(adverse-liq)<=0;
   // Stops and liquidation thresholds are ordered by price. No favorable intrabar trail is backdated.
   if(hitLiq&&(!hitStop||p.side*(liq-p.stop)>=0)){mark(cash);exit(liq,1,endAt,'liquidation',true);}
   else if(hitStop){mark(Math.max(cash,equity(p.stop)));exit(p.stop,1,endAt,'stop');}
   else{
    mark(equity(adverse));
    if(p.target&&p.side*(favorable-p.target)>=0){if(p.exit==='vwap')exit(p.target,1,endAt,'vwap');else if(!p.partial)exit(p.target,.5,endAt,'partial');}
    // A newly raised break-even stop is active next bar; intrabar sequence is unknown.
    if(p&&index-Math.floor((p.entryAt-base)/STEP)+1>=p.maxBars)exit(b.close,1,endAt,'timeout');
   }
   if(p){
    if(p.exit==='swing'){const s=signal(p.symbol,index);if(s){if(p.side>0?s.exitLong:s.exitShort)p.exitPending='trend';const trail=p.side>0?s.trailLong:s.trailShort;p.stop=p.side>0?Math.max(p.stop,trail):Math.min(p.stop,trail);}}
    if(p.exit==='q15'||p.exit==='q30'){
     if(!p.partial&&endAt-p.entryAt>=3*DAY-1)p.partialPending=true;
     if(endAt%DAY===DAY-1&&feature(p.symbol,'daily10',index)>0&&b.close<feature(p.symbol,'daily10',index))p.exitPending='daily_ma';
    }
    if(p.exit==='partial2r'&&p.partial){const trail=b.close-p.side*2*feature(p.symbol,'atr',index);p.stop=p.side>0?Math.max(p.stop,trail):Math.min(p.stop,trail);}
    maxExposure=Math.max(maxExposure,p.qty*b.close/Math.max(1,equity(b.close)));
   }
  }
  const close=p?row(p.symbol,index).close:0;let eq=equity(close);mark(eq);
  if(eq<INITIAL*.01&&!p)floor=true;
  if(!p&&!floor){let best=null;for(const s of Object.keys(data.symbols)){const q=signal(s,index);if(q?.side&&(!best||q.rank>best.rank||q.rank===best.rank&&s<best.symbol))best={...q,symbol:s};}pending=best;}
  if(endAt%DAY===DAY-1||index===endIndex){if(index===endIndex&&p){exit(close,1,endAt,'evaluation_end');eq=cash;mark(eq);}curve.push({at:endAt,equity:eq});}
 }
 if(Math.abs(cash-initialEquity-trades.reduce((s,t)=>s+t.net,0))>Math.max(1e-6,cash*1e-9))throw Error('Cash reconciliation failed');
 if(trades.some(t=>t.entryAt<=t.signalAt))throw Error('Future information / chronology failure');
 return {method:method.id,policy:policy.id,leverage,start,end,initialEquity,...metrics(curve,trades,start,end,dd,{fees,funding,slippage,estimatedFundingPayments,maxExposure,timeInMarket:heldBars/(endIndex-startIndex+1),skipped,capacityCapped,capitalFloorReached:floor,maxLossStreak,minEquity,peakEquity:high},initialEquity),curve,closed:trades};
}
module.exports={evaluate,metrics,liquidation,size,fundingGrid,INITIAL};
