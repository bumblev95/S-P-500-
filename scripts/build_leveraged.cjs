'use strict';
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),P=require('./paper_engine.cjs');
function build(market,now,root,profile="leverage5x3x"){
 const cfg=profile==="wideRecovery"?P.WIDE:P.LEVERAGED;
 const dir=path.join(root,profile==='wideRecovery'?'wide':'leveraged');fs.mkdirSync(dir,{recursive:true});
 const read=(name,fallback)=>{try{return JSON.parse(fs.readFileSync(path.join(dir,name),'utf8'));}catch(e){if(e.code==='ENOENT')return fallback;throw e;}};
 const write=(name,value)=>{const dest=path.join(dir,name);fs.mkdirSync(path.dirname(dest),{recursive:true});fs.writeFileSync(dest+'.tmp',JSON.stringify(value));fs.renameSync(dest+'.tmp',dest);};
 let state=read('state.json',null),replay=read('replay.json',null);
 if(!state&&((market.crypto?.BTC?.frames?.['15m']?.length||0)<70))throw Error('Leveraged experiment requires BTC history');
 if(!replay){const account=P.report(P.run(P.create('crypto',now,profile),market,{mode:'replay',now}));
  const control=P.report(P.run(P.create('crypto',now),market,{mode:'replay',now}));
  replay={generatedAt:now,profileVersion:cfg.profileVersion,account,control:{equity:control.equity,return:control.return,maxDrawdown:control.maxDrawdown,trades:control.trades.length,startedAt:control.startedAt,marketAsOf:control.marketAsOf}};write('replay.json',replay);}
 if(replay.profileVersion!==cfg.profileVersion)throw Error('Preserve old leverage experiment');
 state=state||{createdAt:now,ledgerHash:null,account:P.create('crypto',now,profile)};
 const previous=state.account,next=P.run(previous,market,{mode:'forward',now});
 if(JSON.stringify(next.trades.slice(0,previous.trades.length))!==JSON.stringify(previous.trades))throw Error('Closed leveraged trades changed');
 const events=next.events.slice(previous.events.length);
 if(events.length||state.ledgerHash===null){const record={profileVersion:cfg.profileVersion,recordedAt:now,previousHash:state.ledgerHash,events,equity:P.equity(next)};
  const hash=crypto.createHash('sha256').update(JSON.stringify(record)).digest('hex');write('ledger/'+now+'-'+hash.slice(0,12)+'.json',{...record,hash});state.ledgerHash=hash;}
 state.account=next;state.updatedAt=now;write('state.json',state);
 return {config:cfg,forward:{createdAt:state.createdAt,accounts:{crypto:P.report(next)}},replay:{generatedAt:replay.generatedAt,accounts:{crypto:replay.account}},control:replay.control};
}
module.exports={build};
