'use strict';
const fs=require('node:fs'),P=require('./paper_engine.cjs'),T=require('./trend_methods.cjs');
const DAY=86400000,STEP=900000;
const FEATURES=['side','atr_fraction','momentum14_atr','trend_strength','return1_side','return7_side','return30_side','body_side','lower_wick','upper_wick','relative_volume','efficiency','last_funding_side','funding_age_days','BTC','ETH','SOL'];
function features(source,symbol,maps){
 const rows=source.frames['15m'],bars=T.aggregate(rows),byTime=new Map(rows.map((r,i)=>[r.end,i])),out=[];let f=0;
 const funding=source.funding||[];
 for(let j=180;j<bars.length;j++){
  const b=bars[j],q=maps.get(b.end);if(!q?.side)continue;
  const i=byTime.get(b.end),window=rows.slice(i-95,i+1),vol=window.reduce((a,r)=>a+r.volume,0)/window.length;
  if(b.t-bars[j-180].t!==180*14400000)continue;
  while(f+1<funding.length&&funding[f+1].time<=b.end)f++;
  const fr=funding[f]?.time<=b.end?funding[f]:null,sg=q.side==='long'?1:-1,span=Math.max(b.high-b.low,1e-12);
  const change=bars.slice(j-6,j+1).reduce((a,r,k,arr)=>a+(k?Math.abs(r.close-arr[k-1].close):0),0);
  const x=[sg,q.atr/b.close,sg*(b.close-bars[j-84].close)/q.atr,q.rank,...[6,42,180].map(n=>sg*(b.close/bars[j-n].close-1)),sg*(b.close-b.open)/span,(Math.min(b.close,b.open)-b.low)/span,(b.high-Math.max(b.close,b.open))/span,vol?rows[i].volume/vol:0,change?Math.abs(b.close-bars[j-6].close)/change:0,fr?sg*fr.rate:0,fr?(b.end-fr.time)/DAY:30,...['BTC','ETH','SOL'].map(s=>Number(s===symbol))];
  if(x.every(Number.isFinite))out.push({symbol,at:b.end,index:i,x,trainingSample:(b.t%DAY===0||b.t%DAY===12*3600000)});
 }
 return out;
}
// Independent candidate outcome. Uses shared entry, funding, liquidation and close
// primitives. It has no simultaneous positions: not a realizable portfolio return.
function label(source,symbol,maps,i){
 const rows=source.frames['15m'],q=maps.get(rows[i].end),cfg=P.TREND,sg=q.side==='long'?1:-1;
 if(!rows[i+1]||rows[i+1].t!==q.at+1)return null;
 const a=P.create('crypto',q.at,'trendResearch');a.marks[symbol]=rows[i].close;
 const reason=P.enter(a,{...q,symbol,id:'label',createdAt:q.at},rows[i+1],cfg,q.at);
 if(reason)return null;
 const p=a.positions[0];
 for(let k=i+1;k<rows.length&&k<=i+q.holdBars;k++){
  const r=rows[k];if(r.t!==rows[k-1].t+STEP)return null;
  a.marks[symbol]=r.open;
  if(k>i+1){
   P.funding(a,p,r.t,source,r.open);
   if(sg*(r.open-P.liquidation(p,cfg))<=0)P.close(a,p,r.open,r.t,'가상 격리 청산 · 시가 갭',cfg,r.t,'open');
   else if(sg*(r.open-p.stop)<=0)P.close(a,p,r.open,r.t,'손절 · 시가 갭',cfg,r.t,'open');
   else if(p.exitPending)P.close(a,p,r.open,r.t,'4시간 추세 이탈',cfg,r.t,'open');
  }
  if(!a.positions.length)break;
  p.bars++;
  const stop=sg===1?r.low<=p.stop:r.high>=p.stop;
  P.funding(a,p,r.end,source,r.open,stop);
  const liq=P.liquidation(p,cfg),liquid=sg===1?r.low<=liq:r.high>=liq;
  if(liquid&&(!stop||sg*(p.stop-liq)<=0))P.close(a,p,liq,r.end,'가상 격리 청산 · 봉 가격 기준',cfg,r.end);
  else if(stop||p.bars>=p.holdBars)P.close(a,p,stop?p.stop:r.close,r.end,stop?'손절':'보유 시간 종료',cfg,r.end,stop?'bar':'close');
  if(!a.positions.length)break;
  const c=maps.get(r.end);
  if(c){if(c.exitLong&&sg===1||c.exitShort&&sg===-1)p.exitPending=true;const s=sg===1?c.trailLong:c.trailShort;if(Number.isFinite(s)&&sg*(s-p.stop)>0)p.stop=s;}
 }
 const t=a.trades[0];if(!t)return null;
 return {netR:t.net/t.riskBudget,labelEnd:t.exitAt,net:t.net,qty:t.qty,entry:t.entry,exit:t.exit,reason:t.exitReason,estimatedFundingHours:a.estimatedFundingHours};
}
function build(){
 const market=JSON.parse(fs.readFileSync('/tmp/paper-long-cache/market.json')),out=[];
 for(const [s,source] of Object.entries(market.crypto)){
  const maps=T.signals(source.frames['15m'],'momentum14'),all=features(source,s,maps);
  for(const r of all){if(r.trainingSample)Object.assign(r,label(source,s,maps,r.index)||{});delete r.index;}
  out.push(...all);console.log(s,all.length,all.filter(r=>Number.isFinite(r.netR)).length);
 }
 fs.writeFileSync('/tmp/selector-samples.json',JSON.stringify({features:FEATURES,rows:out.sort((a,b)=>a.at-b.at||a.symbol.localeCompare(b.symbol))}));
}
if(require.main===module)build();module.exports={features,label,FEATURES};
