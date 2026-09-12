'use strict';
// Candidate labels use the same execution engine, independently per signal.
// They are training observations, not a portfolio's realizable trade returns.
const fs=require('node:fs'),P=require('./paper_engine.cjs'),S=require('../assets/simulation-signals.js'),E=require('../assets/perp-engine.js');
function features(rows,higher,symbol,q){
 const r=rows.at(-1),a=E.indicators(rows.slice(-240),'15m'),hi=E.indicators(higher.filter(x=>x.end<=r.end).slice(-240),'1h');
 if(!a||!hi)return null;
 const span=Math.max(r.high-r.low,1e-12);
 return [a.rsi/100,a.atr/r.close,(r.close-a.ema20)/a.atr,(r.close-a.ema50)/a.atr,a.relativeVolume,a.efficiency,
 (r.close-r.open)/span,(Math.min(r.close,r.open)-r.low)/span,(r.high-Math.max(r.close,r.open))/span,
 ...[4,16,64].map(n=>r.close/rows.at(-n).close-1),hi.bias==='long'?1:hi.bias==='short'?-1:0,q.side==='long'?1:-1,
 ...['retest','candle','falseBreak'].map(k=>Number(q.pattern===k)),...['BTC','ETH','SOL'].map(k=>Number(symbol===k))];
}
function dataset(market){const out=[];
 for(const [symbol,source] of Object.entries(market.crypto||{})){
  const rows=source.frames['15m'],higher=source.frames['1h'];
  for(let i=65;i<rows.length-8;i++){
   const prefix=rows.slice(Math.max(0,i-260),i+1),q=S.crypto(prefix,higher);if(!q.side)continue;
   const window=rows.slice(i,i+9);if(window.some((r,k)=>k&&r.t-window[k-1].t!==900000))continue;
   const x=features(prefix,higher,symbol,q);if(!x||!x.every(Number.isFinite))continue;
   const input={...source,frames:{'15m':window,'1h':higher}},markets={crypto:{BTC:input,[symbol]:input}};
   const provider=(sym,rs)=>sym===symbol&&rs.at(-1).end===q.at?q:{side:null};
   const account=P.run(P.create('crypto',window[0].end,'leverage5x3x'),markets,{mode:'replay',now:window.at(-1).end+1,startAt:window[0].t,provider});
   const trade=account.trades[0];if(!trade)continue;
   out.push({symbol,at:q.at,labelEnd:trade.exitAt,x,y:Number(trade.net>0),netR:trade.net/trade.riskBudget,signal:{...q,symbol},fundingEstimated:account.estimatedFundingHours});
  }
 }
 return out.sort((a,b)=>a.at-b.at||a.symbol.localeCompare(b.symbol));
}
if(require.main===module){const market=JSON.parse(fs.readFileSync(process.argv[2]||'simulation/market.json'));process.stdout.write(JSON.stringify(dataset(market)));}
module.exports={features,dataset};
