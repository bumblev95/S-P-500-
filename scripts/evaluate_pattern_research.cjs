'use strict';
const fs=require('node:fs'),P=require('./paper_engine.cjs');
const input=JSON.parse(fs.readFileSync(0,'utf8')),market=JSON.parse(fs.readFileSync(input.marketPath));
const rows=new Map(input.rows.map(r=>[r.symbol+':'+r.at,r]));
function evaluate(filtered){
 const provider=(symbol,bars)=>{const row=rows.get(symbol+':'+bars.at(-1).end);return row&&(!filtered||row.score>=input.threshold)?row.signal:{side:null};};
 const a=P.report(P.run(P.create('crypto',input.start,input.profile||'leverage5x3x'),market,{mode:'replay',startAt:input.start-899999,now:input.end+1,provider}));
 return {equity:a.equity,return:a.return,maxDrawdown:a.maxDrawdown,trades:a.trades.length,winRate:a.winRate,fees:a.fees,funding:a.funding,positions:a.positions.length,estimatedFundingHours:a.estimatedFundingHours,warnings:a.warnings};
}
process.stdout.write(JSON.stringify({rules:evaluate(false),neuralFilter:evaluate(true)}));
