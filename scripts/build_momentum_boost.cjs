'use strict';
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),P=require('./paper_engine.cjs'),B=require('./momentum_boost.cjs');
const VERSION='momentum-breakout-position-ml-study-v1';
const sha=value=>crypto.createHash('sha256').update(JSON.stringify(value)).digest('hex');
function build(market,now,root){
 const dir=path.join(root,'momentum-boost'),read=(name,fallback)=>{try{return JSON.parse(fs.readFileSync(path.join(dir,name)))}catch(e){if(e.code==='ENOENT')return fallback;throw e;}};
 const write=(name,value)=>{const dest=path.join(dir,name);fs.mkdirSync(path.dirname(dest),{recursive:true});fs.writeFileSync(dest+'.tmp',JSON.stringify(value));fs.renameSync(dest+'.tmp',dest);};
 const model=B.loadModel(),maps=B.mapsFor(market,model),priorStudy=read('experiment.json',null);
 if(priorStudy&&(priorStudy.version!==VERSION||priorStudy.modelSha256!==B.MODEL_SHA256))throw Error('Existing breakout study identity changed');
 const study=priorStudy||{version:VERSION,createdAt:now,modelSha256:B.MODEL_SHA256,modelId:model.id,decisionHash:null,lastObserved:{}};
 const results={},writes=[];
 for(const spec of B.PROFILES){
  const cfg=P.config(P.create('crypto',now,spec.id)),feed=B.providers(market,spec.id,model,maps);
  let state=read(spec.directory+'/state.json',null),replay=read(spec.directory+'/replay.json',null);
  if(!!priorStudy!==!!state||!!priorStudy!==!!replay)throw Error('Incomplete existing study: restore account records, never recreate them');
  if(!state&&!(maps.BTC?.size))throw Error('Breakout study needs 30 days of contiguous completed 4h context');
  if(!replay){
   const first=[...maps.BTC.keys()][0],start=first-899999;
   if(model.training.labelEnd>=start)throw Error('Research model labels overlap replay');
   replay={generatedAt:now,profileVersion:cfg.profileVersion,modelSha256:B.MODEL_SHA256,account:P.report(P.run(P.create('crypto',now,spec.id),market,{mode:'replay',startAt:start,now,provider:feed.replay}))};
   writes.push([spec.directory+'/replay.json',replay]);
  }
  if(replay.profileVersion!==cfg.profileVersion||replay.modelSha256!==B.MODEL_SHA256)throw Error('Frozen replay identity changed');
  state=state||{createdAt:study.createdAt,modelSha256:B.MODEL_SHA256,ledgerHash:null,account:P.create('crypto',now,spec.id)};
  if(state.createdAt!==study.createdAt||state.modelSha256!==B.MODEL_SHA256||state.account.profile!==spec.id)throw Error('Study account identity mismatch');
  const previous=state.account,next=P.run(previous,market,{mode:'forward',now,provider:feed.forward});
  if(JSON.stringify(next.trades.slice(0,previous.trades.length))!==JSON.stringify(previous.trades))throw Error('Previously closed study trades changed');
  if(next.positions.length>cfg.maxPositions)throw Error('Position limit exceeded');
  const events=next.events.slice(previous.events.length);
  if(events.length||state.ledgerHash===null){
   const record={profileVersion:cfg.profileVersion,modelSha256:B.MODEL_SHA256,recordedAt:now,previousHash:state.ledgerHash,events,equity:P.equity(next),cash:next.cash},hash=sha(record);
   writes.push([spec.directory+'/ledger/'+now+'-'+hash.slice(0,12)+'.json',{...record,hash}]);state.ledgerHash=hash;
  }
  state.account=next;state.updatedAt=now;writes.push([spec.directory+'/state.json',state]);
  results[spec.id]={config:cfg,forward:{createdAt:study.createdAt,accounts:{crypto:P.report(next)}},replay:{generatedAt:replay.generatedAt,accounts:{crypto:replay.account}}};
 }
 const indicators=results.momentumBoostOne.forward.accounts.crypto.signals.map(q=>({symbol:q.symbol,indicatorAt:q.indicatorAt,observedAt:now,price:q.price,candidateSide:q.candidateSide,side:q.side,breakoutHigh:q.breakoutHigh,breakoutLow:q.breakoutLow,breakoutPassed:q.breakoutPassed,modelScore:q.modelScore,modelPassed:q.modelPassed,modelId:q.modelId,featureReady:q.featureReady,stale:q.stale||false,reason:q.reason}));
 const observations=indicators.filter(q=>Number.isFinite(q.indicatorAt)&&q.indicatorAt>(study.lastObserved[q.symbol]||0));
 if(observations.length){
  const record={version:VERSION,modelSha256:B.MODEL_SHA256,recordedAt:now,previousHash:study.decisionHash,observations},hash=sha(record);
  writes.push(['decisions/'+now+'-'+hash.slice(0,12)+'.json',{...record,hash}]);study.decisionHash=hash;
  for(const q of observations)study.lastObserved[q.symbol]=q.indicatorAt;
 }
 study.updatedAt=now;writes.push(['experiment.json',study]);for(const [name,value] of writes)write(name,value);
 const research=JSON.parse(fs.readFileSync(path.join(__dirname,'../simulation/momentum-boost/research.json')));
 return {accounts:results,study:{...study,profiles:B.PROFILES,indicators,model:{id:model.id,thresholdR:model.thresholdR,training:model.training},research}};
}
module.exports={build,VERSION};
