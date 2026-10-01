'use strict';
// Read-only adapters for the existing pinned study. No account writer is imported.
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const B=require('./momentum_boost.cjs'),P=require('./paper_engine.cjs');
const sha=value=>crypto.createHash('sha256').update(JSON.stringify(value)).digest('hex');
const bytesHash=raw=>crypto.createHash('sha256').update(raw).digest('hex');
const fail=message=>{throw Error('Shadow evidence: '+message);};
function readFile(root,name){
 const file=path.join(root,name);
 if(fs.lstatSync(file).isSymbolicLink())fail('symlink input '+name);
 const raw=fs.readFileSync(file);return {value:JSON.parse(raw),sha256:bytesHash(raw)};
}
function readChain(root,directory,expectedHead){
 const dir=path.join(root,directory);if(fs.lstatSync(dir).isSymbolicLink())fail('symlink chain');
 const names=fs.readdirSync(dir).sort(),records=[],files={};let previous=null,lastAt=-1;
 if(!names.length)fail('missing chain '+directory);
 for(const name of names){
  if(!/^\d+-[a-f0-9]{12}\.json$/.test(name))fail('unexpected chain file '+name);
  const relative=directory+'/'+name,{value:r,sha256}=readFile(root,relative),{hash,...body}=r;
  if(!Number.isSafeInteger(r.recordedAt)||r.recordedAt<=lastAt||name!==r.recordedAt+'-'+hash?.slice(0,12)+'.json')fail('chain time/filename '+relative);
  // Existing records hash JSON.stringify in insertion order, not canonical JSON.
  if(!/^[a-f0-9]{64}$/.test(hash)||sha(body)!==hash||r.previousHash!==previous)fail('hash/link mismatch '+relative);
  records.push(r);files[relative]=sha256;previous=hash;lastAt=r.recordedAt;
 }
 if(expectedHead!==undefined&&previous!==expectedHead)fail('chain head disagrees with state '+directory);
 return {records,files,head:previous};
}
function assertAppendOnly(checkpoint,files){
 for(const [name,hash] of Object.entries(checkpoint||{}))if(files[name]!==hash)fail('previous immutable input changed or disappeared: '+name);
}
const manifestHash=files=>sha(Object.fromEntries(Object.keys(files).sort().map(k=>[k,files[k]])));
function near(a,b){return Number.isFinite(a)&&Number.isFinite(b)&&Math.abs(a-b)<=1e-8*Math.max(1,Math.abs(a),Math.abs(b));}
function forecastContext(summary){
 return {model:summary.model,generatedAt:summary.generatedAt,horizons:Object.fromEntries(Object.entries(summary.horizons||{}).map(([h,v])=>{
  const c=v.comparison||{};return [h,{status:c.status,chosen:c.chosen||null,passed:c.passed===true,checks:c.checks||{},improvementVsOriginal:c.improvementVsOriginal??null,liveForecastChanged:c.liveForecastChanged===true,reason:c.reason||null}];
 })),usedForTrading:false};
}
function loadEvidence(root,checkpoint={}){
 const study='simulation/momentum-boost',model=B.loadModel(),experiment=readFile(root,study+'/experiment.json').value;
 if(experiment.version!=='momentum-breakout-position-ml-study-v1'||experiment.modelSha256!==B.MODEL_SHA256||experiment.modelId!==model.id)fail('pinned study identity');
 const decisions=readChain(root,study+'/decisions',experiment.decisionHash),bySignal=new Map(),files={...decisions.files};
 files[study+'/model.json']=readFile(root,study+'/model.json').sha256;
 if(files[study+'/model.json']!==B.MODEL_SHA256)fail('pinned input model hash');
 for(const r of decisions.records){
  if(r.version!==experiment.version||r.modelSha256!==B.MODEL_SHA256||!Array.isArray(r.observations))fail('decision identity');
  for(const q of r.observations){
   const key=q.symbol+':'+q.indicatorAt;
   if(!['BTC','ETH','SOL'].includes(q.symbol)||![null,'long','short'].includes(q.candidateSide)||![null,'long','short'].includes(q.side)||!(q.price>0)||!Number.isFinite(q.price)||!['breakoutPassed','modelPassed','featureReady','stale'].every(k=>typeof q[k]==='boolean')||!Number.isSafeInteger(q.indicatorAt)||q.indicatorAt>=r.recordedAt||q.observedAt!==r.recordedAt||q.modelId!==model.id||bySignal.has(key))fail('invalid/duplicate observation');
   const modelPassed=Number.isFinite(q.modelScore)&&q.modelScore>=model.thresholdR;
   const accepted=!!q.candidateSide&&q.breakoutPassed===true&&modelPassed;
   if(q.modelPassed!==modelPassed||q.side!==(accepted?q.candidateSide:null))fail('decision entry gates');
   bySignal.set(key,{...q,decisionHash:r.hash,recordedAt:r.recordedAt});
  }
 }
 const accounts={},heads={decisions:decisions.head};
 for(const spec of B.PROFILES){
  const base=study+'/'+spec.directory,state=readFile(root,base+'/state.json').value;
  const cfg=P.config(P.create('crypto',experiment.createdAt,spec.id));
  if(state.createdAt!==experiment.createdAt||state.modelSha256!==B.MODEL_SHA256||state.account.profileVersion!==cfg.profileVersion||state.account.createdAt!==experiment.createdAt)fail('source account identity '+spec.id);
  const chain=readChain(root,base+'/ledger',state.ledgerHash),events=[],eventHashes=new Map();Object.assign(files,chain.files);heads[spec.directory]=chain.head;
  for(const r of chain.records){
   if(r.profileVersion!==cfg.profileVersion||r.modelSha256!==B.MODEL_SHA256||!Array.isArray(r.events))fail('ledger identity');
   for(const e of r.events){if(eventHashes.has(e.id)||e.recordedAt!==r.recordedAt||!Number.isSafeInteger(e.at)||e.at>e.recordedAt)fail('event identity/time');events.push(e);eventHashes.set(e.id,r.hash);}
  }
  if(JSON.stringify(events)!==JSON.stringify(state.account.events))fail('state events disagree with immutable ledger');
  const signals=new Map(),entries=new Map(),trades=[];
  for(const e of events){
   if(e.type==='signal'){if(signals.has(e.signalId))fail('duplicate signal');signals.set(e.signalId,e);}
   if(e.type==='entry'){if(entries.has(e.tradeId))fail('duplicate entry');entries.set(e.tradeId,e);}
   if(e.type!=='exit')continue;
   const entry=entries.get(e.tradeId),signal=signals.get(e.tradeId),q=signal&&bySignal.get(e.symbol+':'+signal.signalAt);
   if(!entry||!signal||!q||q.observedAt!==signal.recordedAt||signal.at!==signal.recordedAt||entry.at<signal.recordedAt||e.at<entry.at||q.candidateSide!==e.side||!q.breakoutPassed||spec.id==='momentumBoostOne'&&!q.modelPassed)fail('closed trade lacks causal decision/entry');
   if(entry.symbol!==e.symbol||entry.side!==e.side||!near(entry.qty,e.qty)||!near(signal.modelScore,q.modelScore)||!(entry.price>0)||!(e.price>0))fail('trade witness mismatch');
   const mutable=state.account.trades.find(t=>t.id===e.tradeId);
   if(!mutable||mutable.symbol!==e.symbol||mutable.side!==e.side||!near(mutable.entry,entry.price)||!near(mutable.exit,e.price)||!near(mutable.qty,e.qty)||!near(mutable.net,e.net)||mutable.entryAt!==entry.at||mutable.exitAt!==e.at||mutable.recordedAt!==e.recordedAt)fail('closed state disagrees with immutable events');
   const sign=e.side==='long'?1:-1,entryFee=entry.price*entry.qty*cfg.fee,exitFee=e.price*e.qty*cfg.fee;
   const stopFill=entry.stop*(1-sign*cfg.slip),riskBudget=entry.qty*(sign*(entry.price-stopFill)+cfg.fee*(entry.price+stopFill)+entry.price*.0001*cfg.fundingReserveHours);
   if(!(riskBudget>0)||!Number.isFinite(e.net)||!Number.isFinite(entry.qty)||entry.qty<=0)fail('nonfinite closed economics');
   trades.push({id:e.tradeId,symbol:e.symbol,side:e.side,signalAt:signal.signalAt,orderCreatedAt:signal.recordedAt,entryAt:entry.at,exitAt:e.at,recordedAt:e.recordedAt,
    entry:entry.price,exit:e.price,qty:entry.qty,net:e.net,riskBudget,netR:e.net/riskBudget,entryFee,exitFee,
    slippage:Math.abs(entry.price-entry.price/(1+sign*cfg.slip))*entry.qty+Math.abs(e.price-e.price/(1-sign*cfg.slip))*e.qty,
    fundingAndAdjustmentResidual:sign*entry.qty*(e.price-entry.price)-entryFee-exitFee-e.net,
    modelScore:q.modelScore,decisionHash:q.decisionHash,entryRecordHash:eventHashes.get(entry.id),exitRecordHash:eventHashes.get(e.id)});
  }
  if(trades.length!==state.account.trades.length)fail('closed trade missing from ledger');
  accounts[spec.directory]={profile:spec.id,createdAt:state.createdAt,trades,head:chain.head};
 }
 assertAppendOnly(checkpoint,files);
 const adaptive=readFile(root,'ml/adaptive-summary.json');
 return {schemaVersion:1,pinnedModel:{id:model.id,sha256:B.MODEL_SHA256,thresholdR:model.thresholdR},createdAt:experiment.createdAt,heads,files,
  decisions:decisions.records,accounts,forecastResearch:forecastContext(adaptive.value),adaptiveSummarySha256:adaptive.sha256};
}
module.exports={sha,bytesHash,readFile,readChain,assertAppendOnly,manifestHash,near,forecastContext,loadEvidence};
