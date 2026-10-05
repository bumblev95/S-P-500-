'use strict';
// Research only: compare display rankings without changing entry/holding rules.
const fs=require('node:fs'),path=require('node:path'),zlib=require('node:zlib'),crypto=require('node:crypto'),assert=require('node:assert/strict');
const T=require('../assets/technical-guide.js');
const FastT=require('./top3_cached_rule.cjs').loadCachedRule(require.resolve('../assets/technical-guide.js'));
const Home=require('./build_home_rankings.cjs');
const Study=require('./entry_study.cjs');
const P=require('./entry-study-v1/paper-engine.cjs');
const ROOT=path.resolve(__dirname,'..'),DAY=86400000,finite=Number.isFinite;
const VERSION='daily-top3-ranking-research-v1',METHODS=['baseline','tie_price_risk','price_risk','volume','sector','combined'];
const EXPECTED='0307d3266187abea5e008fbaefd71a447d78298365ff41d2f7939516a12cf92a';
const EP={buy:0,breakout:1,pullback:1,riskwait:2,overextended:3,confirm:4,watch:5,unavailable:6,avoid:7};
const HP={reduce:0,protect:1,hold:2};
const sha=b=>crypto.createHash('sha256').update(b).digest('hex');
const mean=v=>v.length?v.reduce((a,b)=>a+b,0)/v.length:null;
const cmp=(a,b)=>finite(a)&&finite(b)?a-b:finite(a)?-1:finite(b)?1:0;
const desc=(a,b)=>finite(a)&&finite(b)?b-a:finite(a)?-1:finite(b)?1:0,symbol=(a,b)=>a.symbol.localeCompare(b.symbol);
function scenarioFeed(status,date){
 return {generatedAt:date+'T23:59:59Z',credit:{status},
 indicators:['NFCI','STLFSI4','DRTSCILM','FUNDING'].map(id=>({id,status:'ready',asOf:date,maxAgeDays:id==='DRTSCILM'?150:id==='FUNDING'?5:16}))};
}
function makeEntry(source,symbol,i){
 const r=source.rows[i],e=Study.entry(source.rows.slice(Math.max(0,i-252),i+1),symbol,Date.parse(r.date+'T23:59:59Z'));
 e.price=r.signalPrice;
 const v=e.history.slice(-63).map(q=>q.volume).filter(x=>finite(x)&&x>=0);
 e.inputs.avgVolume3m=v.length?Math.trunc(mean(v)):null;
 return e;
}
function feature(e,p,sector,relative){
 const last=e.history.at(-1),prior=e.history.at(-2),unit=p.range.value;
 const zone=finite(p.buyLow)&&finite(p.buyHigh)&&unit>0?
  (e.price<p.buyLow?(p.buyLow-e.price)/unit:e.price>p.buyHigh?(e.price-p.buyHigh)/unit:0):null;
 const volume=finite(p.indicators.relativeVolume)&&p.indicators.relativeVolume>=1.2;
 return {symbol:e.symbol,asOf:e.asOf,price:e.price,score:p.ts,plan:p,sector,
  distance:zone,risk:finite(p.riskPct)?p.riskPct:null,
  breach:unit>0&&finite(p.exitLevel)?Math.max(0,(p.exitLevel-e.price)/unit):null,
  relativeVolume:p.indicators.relativeVolume,volume,pressure:volume&&!!prior&&last.close<prior.close,
  sectorRelative:relative,sectorUp:finite(relative)&&relative>0,sectorDown:finite(relative)&&relative<0};
}
function eligible(q){return finite(q.score)&&q.score>=0&&q.score<=100&&finite(q.price)&&q.price>0&&
 Object.hasOwn(EP,q.plan.code)&&Object.hasOwn(HP,q.plan.holding.code);}
function tier(q,type){return type==='buy'?(q.plan.holding.code==='reduce'?8:EP[q.plan.code]):HP[q.plan.holding.code];}
function compare(a,b,type,method){
 const state=tier(a,type)-tier(b,type);if(state)return state;
 const score=type==='buy'?desc(a.score,b.score):cmp(a.score,b.score);
 const priceRisk=type==='buy'?cmp(a.distance,b.distance)||cmp(a.risk,b.risk):desc(a.breach,b.breach);
 if(method==='baseline')return score||symbol(a,b);
 if(method==='tie_price_risk')return score||priceRisk||symbol(a,b);
 if(method==='price_risk')return priceRisk||score||symbol(a,b);
 const volume=q=>Number(type==='buy'?q.volume:q.pressure);
 const sector=q=>Number(type==='buy'?q.sectorUp:q.sectorDown);
 const confirmation=method==='volume'?volume:method==='sector'?sector:q=>volume(q)+sector(q);
 return confirmation(b)-confirmation(a)||priceRisk||score||symbol(a,b);
}
function select(all,method='baseline'){
 if(!METHODS.includes(method))throw Error('Unknown method');
 const rows=all.filter(eligible),buy=[...rows].sort((a,b)=>compare(a,b,'buy',method)).slice(0,3);
 const taken=new Set(buy.map(q=>q.symbol));
 const sell=rows.filter(q=>!taken.has(q.symbol)).sort((a,b)=>compare(a,b,'sell',method)).slice(0,3);
 return {buy,sell};
}
function indexData(data){
 assert.equal(data.cutoff,'2026-10-02');assert.equal(Object.keys(data.stocks).length,505);
 const out={};for(const [s,source] of Object.entries(data.stocks)){
  let prior='';const byDate=new Map();for(let i=0;i<source.rows.length;i++){
   const r=source.rows[i];assert(Study.validOHLC(r)&&r.date>prior&&r.date<=data.cutoff);assert(finite(r.signalPrice));
   prior=r.date;byDate.set(r.date,i);
  }out[s]={...source,byDate};
 }return out;
}
function sectorReturns(indexed,date,anchor){
 const stocks={},sums={},spy=indexed.SPY,bi=spy.byDate.get(date),bj=spy.byDate.get(anchor);
 const benchmark=bi!==undefined&&bj!==undefined?spy.rows[bi].close/spy.rows[bj].close-1:null;
 if(!finite(benchmark))return {};
 for(const [s,v] of Object.entries(indexed)){
  if(['SPY','SOXX'].includes(s)||!v.sector||v.sector==='unknown'||v.sector==='ETF / index')continue;
  const i=v.byDate.get(date),j=v.byDate.get(anchor);if(i===undefined||j===undefined)continue;
  const r=v.rows[i].close/v.rows[j].close-1;stocks[s]=r;
  if(!sums[v.sector])sums[v.sector]={sum:0,count:0};
  sums[v.sector].sum+=r;sums[v.sector].count++;
 }
 return Object.fromEntries(Object.entries(stocks).map(([s,r])=>{
  const q=sums[indexed[s].sector];return [s,q.count>1?(q.sum-r)/(q.count-1)-benchmark:null];
 }));
}
function outcome(indexed,s,date,h,type,cost=1){
 const v=indexed[s],spy=indexed.SPY,i=v.byDate.get(date),bi=spy.byDate.get(date);
 if(i===undefined||bi===undefined)return {excluded:'missingSignal'};
 if(i+h>=v.rows.length||bi+h>=spy.rows.length)return {excluded:'immature'};
 const bars=v.rows.slice(i+1,i+h+1),ref=spy.rows.slice(bi+1,bi+h+1);
 if(bars.some((r,j)=>r.date!==ref[j].date))return {excluded:'missingSession'};
 const fee=P.CONFIG.stocks.fee*cost,slip=P.CONFIG.stocks.slip*cost;
 const sellFactor=(1-fee)*(1-slip),roundtrip=sellFactor/((1+fee)*(1+slip));
 const gross=bars.at(-1).close/bars[0].open-1,benchmarkGross=ref.at(-1).close/ref[0].open-1;
 const net=(1+gross)*roundtrip-1,benchmark=(1+benchmarkGross)*roundtrip-1;
 return {date,symbol:s,horizon:h,type,entryDate:bars[0].date,endDate:bars.at(-1).date,
  net,benchmark,excess:net-benchmark,gross,avoidance:-gross*sellFactor,
  down:Number(gross<0),adverse:Math.min(...bars.map(r=>r.low))/bars[0].open-1};
}
function newAccount(first,status,method,cost){
 const a=P.create('stocks',first.t);a.status=status;a.method=method;a.cost=cost;a.rejections={};a.missingHeldSessions=0;
 a.curve=[{date:first.date,at:first.t,equity:a.initial,cash:a.initial,exposure:0,phase:'beforeFirstOpen'}];return a;
}
function execute(a,bars,r){
 const cfg={...P.CONFIG.stocks,fee:P.CONFIG.stocks.fee*a.cost,slip:P.CONFIG.stocks.slip*a.cost};
 for(const p of a.positions)if(!bars[p.symbol])a.missingHeldSessions++;
 for(const [s,b] of Object.entries(bars))a.marks[s]=b.open;
 for(const p of [...a.positions]){
  const b=bars[p.symbol];if(!b)continue;
  if(p.pendingStop&&b.t>=p.pendingStop.notBefore){p.stop=p.pendingStop.price;delete p.pendingStop;}
  if(b.open<=p.stop)P.close(a,p,b.open,b.t,'stop gap',cfg,b.end,'open');
  else if(finite(p.target)&&b.open>=p.target)P.close(a,p,p.target,b.t,'target gap',cfg,b.end,'open');
  else if(p.exitPending&&b.t>=p.exitNotBefore)P.close(a,p,b.open,b.t,'holding reduce',cfg,b.end,'open');
 }
 const keep=[];for(const q of a.pending){
  let why;
  if(r.t>q.expires)why='expired';else if(r.t<q.notBefore){keep.push(q);continue;}
  else if(!bars[q.symbol])why='missing next open';else why=P.enter(a,q,bars[q.symbol],{...cfg,trend:q.pattern==='breakout'},r.end);
  if(why)a.rejections[why]=(a.rejections[why]||0)+1;
 }a.pending=keep;
 for(const p of [...a.positions]){
  const b=bars[p.symbol];if(!b)continue;p.bars++;
  const stop=b.low<=p.stop,target=finite(p.target)&&b.high>=p.target;
  if(stop||target)P.close(a,p,stop?p.stop:p.target,b.end,stop?(target?'stop before same-bar target':'stop'):'pullback target',cfg,b.end,'bar');
 }
 for(const [s,b] of Object.entries(bars))a.marks[s]=b.close;
 const eq=P.equity(a);assert(eq>=0&&a.cash>=-1e-7);assert(a.positions.length<=cfg.maxPositions);
 for(const p of a.positions)assert(a.positions.filter(q=>q.sector===p.sector).length<=2);
 a.highWater=Math.max(a.highWater,eq);a.maxDrawdown=Math.max(a.maxDrawdown,1-eq/a.highWater);
 a.curve.push({date:r.date,at:r.end,equity:eq,cash:a.cash,exposure:a.positions.reduce((n,p)=>n+p.qty*(a.marks[p.symbol]??p.entry),0)});
}
function observe(a,all,picks,date){
 const at=Date.parse(date+'T23:59:59Z'),bySymbol=new Map(all.map(q=>[q.symbol,q]));
 for(const p of a.positions){
  const q=bySymbol.get(p.symbol);if(!q)continue;const plan=q.plan;
  if(plan.holding.code==='reduce'&&!p.exitPending){p.exitPending='reduce';p.exitNotBefore=at+1;}
  else if(['hold','protect'].includes(plan.holding.code)&&finite(plan.exitLevel)&&plan.exitLevel<q.price&&plan.exitLevel>(p.pendingStop?.price??p.stop))
   p.pendingStop={price:plan.exitLevel,notBefore:at+1};
 }
 // Selected waiting/avoid states remain display candidates, never trades.
 a.pending=[];for(let rank=0;rank<picks.length;rank++){
  const q=picks[rank],p=q.plan;if(p.code!=='buy'||a.positions.some(x=>x.symbol===q.symbol))continue;
  a.pending.push({id:VERSION+':'+q.symbol+':'+date,symbol:q.symbol,sector:q.sector,side:'long',
   pattern:p.strategy,reason:p.reason,at,createdAt:at,notBefore:at+1,expires:at+5*DAY,
   price:q.price,stop:p.stop,target:p.target1,atr:p.range.value,rank,holdBars:Number.MAX_SAFE_INTEGER});
 }
}
function accountReport(a,reference){
 const rows=a.curve.filter(r=>!r.phase),last=reference.at(-1),fee=P.CONFIG.stocks.fee*a.cost,slip=P.CONFIG.stocks.slip*a.cost;
 const mark=P.equity(a),liquidation=mark-a.positions.reduce((n,p)=>n+p.qty*a.marks[p.symbol]*(1-(1-fee)*(1-slip)),0);
 const years=(last.end-reference[0].t)/(365.25*DAY),symbolNet={};
 for(const t of a.trades)symbolNet[t.symbol]=(symbolNet[t.symbol]||0)+t.net;
 for(const p of a.positions)symbolNet[p.symbol]=(symbolNet[p.symbol]||0)+p.qty*(a.marks[p.symbol]*(1-fee)*(1-slip)-p.entry)-p.entryFee;
 const issuer=Object.entries(symbolNet).map(([symbol,net])=>({symbol,net})).sort((a,b)=>b.net-a.net||a.symbol.localeCompare(b.symbol));
 assert(Math.abs(a.initial+Object.values(symbolNet).reduce((a,b)=>a+b,0)-liquidation)<1e-6);
 const positive=a.trades.filter(t=>t.net>0).reduce((n,t)=>n+t.net,0),negative=-a.trades.filter(t=>t.net<0).reduce((n,t)=>n+t.net,0);
 const annual={};let previous=a.initial;for(const r of rows){
  const year=r.date.slice(0,4);if(!annual[year])annual[year]={start:previous,end:previous,high:previous,maxDrawdown:0,sessions:0};
  const y=annual[year];y.end=r.equity;y.high=Math.max(y.high,r.equity);y.maxDrawdown=Math.max(y.maxDrawdown,1-r.equity/y.high);y.sessions++;previous=r.equity;
 }
 for(const y of Object.values(annual)){y.return=y.end/y.start-1;delete y.high;}
 return {initial:a.initial,liquidationEquity:liquidation,cagr:(liquidation/a.initial)**(1/years)-1,maxDrawdown:a.maxDrawdown,
  meanExposure:mean(rows.map(r=>r.exposure/r.equity)),entries:a.trades.length+a.positions.length,closedTrades:a.trades.length,
  winRate:a.trades.length?a.trades.filter(t=>t.net>0).length/a.trades.length:null,profitFactor:negative?positive/negative:null,
  fees:a.fees,slippage:a.slippage,openPositions:a.positions.length,missingHeldSessions:a.missingHeldSessions,
  topIssuer:issuer[0]||null,topIssuerProfitShare:liquidation>a.initial?issuer[0]?.net/(liquidation-a.initial):null,
  rejections:a.rejections,annual};
}
function summary(rows){
 const byDate=new Map();for(const r of rows){if(!byDate.has(r.date))byDate.set(r.date,[]);byDate.get(r.date).push(r);}
 const keys=['net','excess','gross','avoidance','down','adverse'];
 const daily=[...byDate].map(([date,v])=>Object.fromEntries([['date',date],...keys.map(k=>[k,mean(v.map(q=>q[k]))])]));
 const quantile=(v,q)=>{if(!v.length)return null;const a=[...v].sort((a,b)=>a-b),j=(a.length-1)*q;return a[Math.floor(j)]+(a[Math.ceil(j)]-a[Math.floor(j)])*(j-Math.floor(j));};
 return {observations:rows.length,signalDates:daily.length,meanNet:mean(rows.map(r=>r.net)),medianNet:quantile(rows.map(r=>r.net),.5),
  p10Net:quantile(rows.map(r=>r.net),.1),meanExcess:mean(rows.map(r=>r.excess)),dateBalancedNet:mean(daily.map(r=>r.net)),
  dateBalancedExcess:mean(daily.map(r=>r.excess)),dateBalancedAvoidance:mean(daily.map(r=>r.avoidance)),
  downsidePrecision:mean(daily.map(r=>r.down)),meanAdverse:mean(daily.map(r=>r.adverse)),daily};
}
function compact(q){return {symbol:q.symbol,score:q.score,code:q.plan.code,holding:q.plan.holding.code,strategy:q.plan.strategy,
 distance:q.distance,risk:q.risk,relativeVolume:q.relativeVolume,sectorRelative:q.sectorRelative,breach:q.breach,price:q.price};}
function csv(rows,columns){
 const quote=x=>{const s=x===undefined||x===null?'':String(x);return /[,"\n]/.test(s)?'"'+s.replaceAll('"','""')+'"':s;};
 return columns.join(',')+'\n'+rows.map(r=>columns.map(k=>quote(r[k])).join(',')).join('\n')+'\n';
}
async function run(input,output){
 const raw=zlib.gunzipSync(fs.readFileSync(input));assert.equal(sha(raw),EXPECTED,'Frozen prices differ');
 const indexed=indexData(JSON.parse(raw)),allReference=indexed.SPY.rows,reference=allReference.filter(r=>r.date>='2017-10-02');
 const symbols=Object.keys(indexed).sort(),states={},picksRows=[],labels=[],curves=[],trades=[];
 for(const status of ['stable','watch'])states[status]=Object.fromEntries(METHODS.map(m=>[m,{daily:[],accounts:[1,2].map(c=>newAccount(reference[0],status,m,c))}]));
 let audits=0;const started=Date.now();
 for(let day=0;day<reference.length;day++){
  const r=reference[day],bi=indexed.SPY.byDate.get(r.date),anchor=allReference[bi-63]?.date;
  const sector=anchor?sectorReturns(indexed,r.date,anchor):{},bars={},entries={};
  for(const s of symbols){const v=indexed[s],i=v.byDate.get(r.date);if(i===undefined)continue;bars[s]=v.rows[i];entries[s]=makeEntry(v,s,i);}
  for(const [status,methods] of Object.entries(states)){
   const market=scenarioFeed(status,r.date),now=Date.parse(r.date+'T23:59:59Z');
   const all=Object.entries(entries).map(([s,e])=>feature(e,FastT.plan(e,null,market,now),indexed[s].sector,sector[s]));
   if(day%100===0||day===reference.length-1)for(const q of all)
    assert.equal(JSON.stringify(q.plan),JSON.stringify(T.plan(entries[q.symbol],null,market,now)),'Cached predicate changed original result');
   for(const [method,state] of Object.entries(methods)){
    for(const a of state.accounts)execute(a,bars,r);
    const selected=select(all,method),base=method==='baseline'?selected:null;
    if(base&&(day%100===0||day===reference.length-1)){
     const actual=Home.select(Object.fromEntries(all.map(q=>[q.symbol,q])),now);
     assert.deepEqual(base.buy.map(q=>q.symbol),actual.buy.map(q=>q.symbol));
     assert.deepEqual(base.sell.map(q=>q.symbol),actual.sell.map(q=>q.symbol));audits++;
    }
    const row={date:r.date,buy:selected.buy.map(q=>q.symbol),sell:selected.sell.map(q=>q.symbol),
     actualBuy:selected.buy.filter(q=>q.plan.code==='buy').length,eligible:all.filter(eligible).length};
    state.daily.push(row);
    for(const a of state.accounts)observe(a,all,selected.buy,r.date);
    for(const type of ['buy','sell'])for(const q of selected[type]){
     picksRows.push({status,method,date:r.date,type,...compact(q)});
     for(const h of [20,63]){const o=outcome(indexed,q.symbol,r.date,h,type);
      labels.push({status,method,...o,horizon:h,type,symbol:q.symbol,date:r.date,code:q.plan.code,holding:q.plan.holding.code});
     }
    }
   }
  }
  if(day%100===0||day===reference.length-1)console.log(JSON.stringify({phase:'rankings',day:day+1,total:reference.length,date:r.date,elapsedSeconds:Math.round((Date.now()-started)/1000)}));
 }
 fs.mkdirSync(output,{recursive:true});
 const result={version:VERSION,generatedAt:new Date().toISOString(),period:{start:reference[0].date,end:reference.at(-1).date,sessions:reference.length},
  datasetSHA256:EXPECTED,methods:METHODS,audits,universe:505,sourceHashes:{},scenarios:{}};
 const sources=['assets/technical-guide.js','assets/stock-assessment.js','scripts/build_home_rankings.cjs','scripts/entry_study.cjs',
  'scripts/entry-study-v1/paper-engine.cjs','scripts/backtest_top3_rankings.cjs','scripts/top3_cached_rule.cjs','research/top3-ranking/2026-10-05/PROTOCOL.md'];
 for(const p of sources)result.sourceHashes[p]=sha(fs.readFileSync(path.join(ROOT,p)));
 for(const [status,methods] of Object.entries(states)){
  result.scenarios[status]={};
  for(const [method,state] of Object.entries(methods)){
   const groups={};for(const type of ['buy','sell']){groups[type]={};for(const h of [20,63]){
    const all=labels.filter(r=>r.status===status&&r.method===method&&r.type===type&&r.horizon===h);
    const rows=all.filter(r=>!r.excluded),excluded={};for(const r of all.filter(r=>r.excluded))excluded[r.excluded]=(excluded[r.excluded]||0)+1;
    const s=summary(rows);delete s.daily;groups[type][h]={...s,excluded};
   }}
   const reports=state.accounts.map(a=>({cost:a.cost,...accountReport(a,reference)}));
   result.scenarios[status][method]={frequency:{sessions:state.daily.length,
    selectedBuy:state.daily.reduce((n,r)=>n+r.buy.length,0),selectedSell:state.daily.reduce((n,r)=>n+r.sell.length,0),
    zeroActualBuyDays:state.daily.filter(r=>r.actualBuy===0).length,meanActualBuy:mean(state.daily.map(r=>r.actualBuy))},
    outcomes:groups,accounts:reports};
   for(const a of state.accounts){
    curves.push(...a.curve.filter(r=>!r.phase).map(r=>({status,method,cost:a.cost,...r})));
    trades.push(...a.trades.map(t=>({status,method,cost:a.cost,symbol:t.symbol,sector:t.sector,signalAt:t.signalAt,entryAt:t.entryAt,exitAt:t.exitAt,
     qty:t.qty,entry:t.entry,exit:t.exit,net:t.net,entryFee:t.entryFee,exitFee:t.exitFee,reason:t.exitReason})));
   }
  }
 }
 const files={
  'picks.csv.gz':zlib.gzipSync(csv(picksRows,['status','method','date','type','symbol','score','code','holding','strategy','distance','risk','relativeVolume','sectorRelative','breach','price'])),
  'outcomes.csv.gz':zlib.gzipSync(csv(labels,['status','method','date','type','symbol','horizon','entryDate','endDate','net','benchmark','excess','gross','avoidance','down','adverse','excluded','code','holding'])),
  'curves.csv.gz':zlib.gzipSync(csv(curves,['status','method','cost','date','at','equity','cash','exposure'])),
  'trades.csv.gz':zlib.gzipSync(csv(trades,['status','method','cost','symbol','sector','signalAt','entryAt','exitAt','qty','entry','exit','net','entryFee','exitFee','reason']))
 };
 result.outputHashes={};for(const [name,bytes] of Object.entries(files)){fs.writeFileSync(path.join(output,name),bytes);result.outputHashes[name]={sha256:sha(bytes),bytes:bytes.length};}
 fs.writeFileSync(path.join(output,'raw-results.json'),JSON.stringify(result,null,2)+'\n');
 console.log(JSON.stringify({phase:'done',elapsedSeconds:Math.round((Date.now()-started)/1000),audits,files:result.outputHashes}));
 return result;
}
module.exports={VERSION,METHODS,scenarioFeed,makeEntry,feature,eligible,compare,select,indexData,sectorReturns,outcome,
 newAccount,execute,observe,accountReport,summary,csv,run};
if(require.main===module){
 const args=process.argv.slice(2),arg=(k,d)=>args.includes(k)?args[args.indexOf(k)+1]:d;
 run(arg('--input',path.join(ROOT,'research/history/entry-backtest-2026-10-04/prices.json.gz')),
  arg('--output',path.join(ROOT,'research/top3-ranking/2026-10-05'))).catch(e=>{console.error(e.stack);process.exitCode=1;});
}
