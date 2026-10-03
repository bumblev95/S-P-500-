'use strict';
// A disposable website projection. Never an input to the shadow/paper engine.
const fs=require('node:fs'),path=require('node:path');
const S=require('./shadow_improvement.cjs'),E=require('./shadow_evidence.cjs'),G=require('./shadow_gates.cjs'),P=require('./paper_engine.cjs');
const OUTPUT='simulation/self-improvement/status.json',STALE_AFTER_MS=1800000;
const safety={automaticPromotion:false,defaultStrategyChanged:false,pinnedModelChanged:false,liveTrading:false,humanReviewRequired:true};

function readAssessment(root,candidate,chain){
 const directory=S.BASE+'/'+candidate.version+'/assessments';
 if(fs.lstatSync(path.join(root,directory)).isSymbolicLink())throw Error('Unsafe assessment directory');
 const observations=new Map(chain.records.map(r=>[r.hash,r.recordedAt]));
 const reports=fs.readdirSync(path.join(root,directory)).sort().map(name=>{
  if(!/^\d+-[a-f0-9]{12}\.json$/.test(name))throw Error('Unexpected assessment filename');
  const file=directory+'/'+name,{value:r}=E.readFile(root,file),{hash,...body}=r;
  if(!/^[a-f0-9]{64}$/.test(hash)||E.sha(body)!==hash||name!==r.asOf+'-'+hash.slice(0,12)+'.json')throw Error('Assessment content/filename hash mismatch');
  if(r.candidateHash!==candidate.hash||r.candidateVersion!==candidate.version||observations.get(r.observationHead)!==r.asOf)throw Error('Assessment does not identify its candidate/observation');
  if(Object.entries(safety).some(([key,value])=>r[key]!==value))throw Error('Assessment violates shadow-only safety policy');
  return {file,record:r};
 });
 const latest=reports.filter(r=>r.record.observationHead===chain.head).at(-1);
 if(!latest)throw Error('Missing assessment for the latest observation');
 // A valid JSON hash alone is insufficient: recompute every economic gate.
 const assessment=G.evaluate(candidate,candidate.source.closedTrades,chain.accounts,chain.records,P.config(chain.accounts.incumbent),{
  integrity:true,completeData:chain.records.every(r=>r.inputs.quality.passed===true)
 });
 for(const [key,value] of Object.entries(assessment))if(JSON.stringify(latest.record[key])!==JSON.stringify(value))throw Error('Assessment disagrees with verified evidence: '+key);
 return {assessment,path:latest.file,hash:latest.record.hash};
}

function build({root=S.ROOT,now=Date.now()}={}){
 if(!Number.isSafeInteger(now)||now<0)throw Error('Invalid status timestamp');
 let evidence=null,sourceError=null;
 try{evidence=E.loadEvidence(root);}catch(e){sourceError=e.message;}
 let versions=[],registryError=null;
 try{versions=S.listVersions(root);}catch(e){registryError=e.message;}
 const rows=versions.map(version=>{
  const blocked={version,status:'blocked',promotionCandidate:false,integrityPassed:false,...safety};
  try{
   if(sourceError)throw Error(sourceError);
   const candidate=S.readCandidate(root,version),chain=S.readObservations(root,candidate);
   E.assertAppendOnly(chain.checkpoint,evidence.files);
   if(candidate.registeredAt>now||chain.records.at(-1).recordedAt>now)throw Error('Future shadow timestamp');
   const saved=readAssessment(root,candidate,chain),last=chain.records.at(-1);
   return {...blocked,status:saved.assessment.status,promotionCandidate:saved.assessment.promotionCandidate,integrityPassed:true,
    registeredAt:candidate.registeredAt,thresholdR:candidate.thresholdR,incumbentThresholdR:evidence.pinnedModel.thresholdR,
    baseModelId:candidate.baseModelId,activity:chain.records.some(r=>!r.registration)?'collecting':'registration_only',
    observations:chain.records.length,latestObservationAt:last.recordedAt,
    initialTrainingTrades:candidate.source.closedTrades.length,
    assessment:saved.assessment,assessmentPath:saved.path,assessmentHash:saved.hash,
    candidatePath:S.BASE+'/'+version+'/candidate.json',observationPath:S.BASE+'/'+version+'/observations/'+last.recordedAt+'-'+last.hash.slice(0,12)+'.json'};
  }catch(e){return {...blocked,reason:e.message};}
 }).sort((a,b)=>(b.registeredAt||0)-(a.registeredAt||0)||a.version.localeCompare(b.version));
 return {schemaVersion:1,purpose:'display-only',mode:'shadow-only',generatedAt:now,staleAfterMs:STALE_AFTER_MS,...safety,
  sourceIntegrity:{passed:!sourceError&&!registryError,reason:sourceError||registryError},
  pinnedModel:evidence?.pinnedModel||null,
  sources:evidence?{decisionRecords:evidence.decisions.length,closedTrades:Object.fromEntries(Object.entries(evidence.accounts).map(([k,v])=>[k,v.trades.length]))}:null,
  forecastResearch:evidence?.forecastResearch||null,versions:rows};
}

function publish(root=S.ROOT,now=Date.now()){
 const snapshot=build({root,now}),dest=path.join(root,OUTPUT);
 let directory=root;
 for(const segment of ['',...path.posix.dirname(OUTPUT).split('/')]){
  directory=path.join(directory,segment);
  if(fs.existsSync(directory)){if(fs.lstatSync(directory).isSymbolicLink()||!fs.statSync(directory).isDirectory())throw Error('Unsafe status directory');}
  else fs.mkdirSync(directory);
 }
 if(fs.existsSync(dest)&&fs.lstatSync(dest).isSymbolicLink())throw Error('Unsafe status file');
 const temporary=dest+'.pending-'+process.pid;
 try{fs.writeFileSync(temporary,JSON.stringify(snapshot,null,2)+'\n',{flag:'wx'});fs.renameSync(temporary,dest);}
 finally{if(fs.existsSync(temporary))fs.unlinkSync(temporary);}
 return snapshot;
}
if(require.main===module){
 try{if(process.argv.length!==2)throw Error('Usage: node scripts/build_shadow_status.cjs');
  const result=publish();console.log(JSON.stringify({file:OUTPUT,versions:result.versions.map(v=>({version:v.version,status:v.status})),sourceIntegrity:result.sourceIntegrity}));
 }catch(e){console.error(e.message);process.exitCode=1;}
}
module.exports={OUTPUT,STALE_AFTER_MS,safety,readAssessment,build,publish};
