'use strict';
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),P=require('./paper_engine.cjs'),T=require('./trend_methods.cjs');
function providers(market){
 const maps=Object.fromEntries(Object.entries(market.crypto||{}).map(([s,v])=>[s,T.signals(v.frames?.['15m']||[],'momentum14')]));
 const times=Object.fromEntries(Object.entries(maps).map(([s,m])=>[s,[...m.keys()]]));
 const replay=(s,rows)=>maps[s]?.get(rows.at(-1).end)||{side:null};
 const forward=(s,rows)=>{
  const end=rows.at(-1).end,at=times[s]||[];let lo=0,hi=at.length;
  while(lo<hi){const mid=(lo+hi)>>1;if(at[mid]<=end)lo=mid+1;else hi=mid;}
  const q=maps[s]?.get(at[lo-1]);
  if(!q||end-q.at>=14400000)return {side:null,at:end,reason:'연속된 4시간봉 준비 또는 최신 자료 대기'};
  return {...q,indicatorAt:q.at,reason:q.side?'14일 '+(q.side==='long'?'상승':'하락')+' 모멘텀 · 4시간봉 확인':'14일 변화가 변동폭 기준 미달 · 관망'};
 };
 return {replay,forward,maps};
}
function build(market,now,root){
 const dir=path.join(root,'momentum');fs.mkdirSync(dir,{recursive:true});
 const read=(n,f)=>{try{return JSON.parse(fs.readFileSync(path.join(dir,n)))}catch(e){if(e.code==='ENOENT')return f;throw e}};
 const write=(n,v)=>{const dest=path.join(dir,n);fs.mkdirSync(path.dirname(dest),{recursive:true});fs.writeFileSync(dest+'.tmp',JSON.stringify(v));fs.renameSync(dest+'.tmp',dest)};
 const feed=providers(market),cfg=P.MOMENTUM;let state=read('state.json',null),replay=read('replay.json',null);
 if(!state&&!feed.maps.BTC?.size)throw Error('Momentum account requires at least 30 days of contiguous completed 4h context');
 if(!replay){
  const first=[...feed.maps.BTC.keys()][0],start=first-899999;
  const account=P.report(P.run(P.create('crypto',now,'momentum14'),market,{mode:'replay',startAt:start,now,provider:feed.replay}));
  replay={generatedAt:now,profileVersion:cfg.profileVersion,account,notes:['Hyperliquid 최초 자료로 고정한 짧은 과거 재현. Binance 연도별 연구와 다른 기간·거래소입니다.']};write('replay.json',replay);
 }
 if(replay.profileVersion!==cfg.profileVersion)throw Error('Momentum replay version changed');
 state=state||{createdAt:now,ledgerHash:null,account:P.create('crypto',now,'momentum14')};
 const previous=state.account,next=P.run(previous,market,{mode:'forward',now,provider:feed.forward});
 if(JSON.stringify(next.trades.slice(0,previous.trades.length))!==JSON.stringify(previous.trades))throw Error('Previously closed momentum trades changed');
 const events=next.events.slice(previous.events.length);
 if(events.length||state.ledgerHash===null){const record={profileVersion:cfg.profileVersion,recordedAt:now,previousHash:state.ledgerHash,events,equity:P.equity(next),cash:next.cash};
  const hash=crypto.createHash('sha256').update(JSON.stringify(record)).digest('hex');write('ledger/'+now+'-'+hash.slice(0,12)+'.json',{...record,hash});state.ledgerHash=hash;}
 state.account=next;state.updatedAt=now;write('state.json',state);
 return {config:cfg,forward:{createdAt:state.createdAt,accounts:{crypto:P.report(next)}},replay:{generatedAt:replay.generatedAt,accounts:{crypto:replay.account}}};
}
module.exports={build,providers};
