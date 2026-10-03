'use strict';
const fs=require('node:fs'),path=require('node:path'),cp=require('node:child_process');
const E=require('./shadow_evidence.cjs'),G=require('./shadow_gates.cjs'),B=require('./momentum_boost.cjs'),P=require('./paper_engine.cjs');
const ROOT=path.resolve(__dirname,'..'),BASE='simulation/self-improvement/versions',H4=14400000;
const RUNTIME=['scripts/shadow_evidence.cjs','scripts/shadow_gates.cjs','scripts/shadow_improvement.cjs','scripts/paper_engine.cjs','scripts/momentum_boost.cjs','scripts/trend_methods.cjs','scripts/selector_data.cjs','assets/simulation-signals.js','assets/perp-engine.js'];
const copy=x=>JSON.parse(JSON.stringify(x));
function inputTimestamp(value){
 const parsed=typeof value==='number'?value:typeof value==='string'&&/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})$/.test(value)?Date.parse(value):NaN;
 if(!Number.isSafeInteger(parsed)||parsed<0)throw Error('Invalid market generatedAt: require epoch milliseconds or timezone-qualified ISO timestamp');
 return parsed;
}
function revision(root){return cp.execFileSync('git',['rev-parse','HEAD'],{cwd:root,encoding:'utf8'}).trim();}
function runtimeHashes(root){return Object.fromEntries(RUNTIME.map(f=>[f,E.bytesHash(fs.readFileSync(path.join(root,f)))]));}
function safeVersion(version){if(!/^shadow-threshold-v1-\d+-[a-f0-9]{12}$/.test(version))throw Error('Invalid shadow version');return version;}
function safeDirectory(root,relative){
 const parts=relative.split('/');let dir=root;
 if(fs.lstatSync(root).isSymbolicLink())throw Error('Symlink repository root');
 for(const p of parts){if(!p||p==='.'||p==='..')throw Error('Invalid shadow path');dir=path.join(dir,p);if(fs.existsSync(dir)){if(fs.lstatSync(dir).isSymbolicLink()||!fs.statSync(dir).isDirectory())throw Error('Unsafe shadow directory');}else fs.mkdirSync(dir);}
 return dir;
}
function appendFile(root,relative,value){
 if(!relative.startsWith(BASE+'/')||relative.includes('..'))throw Error('Shadow writer cannot address operating files');
 const dir=safeDirectory(root,path.posix.dirname(relative)),file=path.join(dir,path.posix.basename(relative)),raw=JSON.stringify(value)+'\n';
 // Hard-link a completely written temporary file: no partial public record and
 // no overwrite, including when two processes race to create the same version.
 const temporary=path.join(dir,'.pending-'+process.pid+'-'+require('node:crypto').randomUUID());
 try{fs.writeFileSync(temporary,raw,{flag:'wx'});fs.linkSync(temporary,file);}finally{if(fs.existsSync(temporary))fs.unlinkSync(temporary);}
}
function listVersions(root=ROOT){
 const dir=path.join(root,BASE);if(!fs.existsSync(dir))return [];
 if(fs.lstatSync(dir).isSymbolicLink())throw Error('Unsafe shadow registry');
 return fs.readdirSync(dir).sort().map(safeVersion);
}
function readCandidate(root,version,{checkRuntime=true}={}){
 safeVersion(version);const {value:c}=E.readFile(root,BASE+'/'+version+'/candidate.json'),{hash,version:storedVersion,...payload}=c;
 if(storedVersion!==version||version!=='shadow-threshold-v1-'+c.registeredAt+'-'+E.sha(payload).slice(0,12)||E.sha({...payload,version})!==hash)throw Error('Candidate content/version hash mismatch');
 if(c.mode!=='shadow-only'||c.kind!=='frozen-score-threshold'||c.baseModelSha256!==B.MODEL_SHA256||c.baseModelId!==B.loadModel().id||!Number.isFinite(c.thresholdR)||c.thresholdR<=B.loadModel().thresholdR||c.thresholdR>1||c.profile!=='momentumBoostOne'||JSON.stringify(c.policy)!==JSON.stringify(G.POLICY))throw Error('Unsupported candidate identity or policy');
 const current=runtimeHashes(root);for(const [f,h] of Object.entries(c.runtimeHashes))if(checkRuntime&&current[f]!==h)throw Error('Shadow runtime changed; register a NEW version, never migrate this account: '+f);
 if(Object.keys(current).length!==Object.keys(c.runtimeHashes).length)throw Error('Runtime manifest incomplete');
 return c;
}
function register({root=ROOT,thresholdR=.15,now=Date.now()}={}){
 const evidence=E.loadEvidence(root),model=B.loadModel();
 if(!Number.isSafeInteger(now)||now<evidence.decisions.at(-1).recordedAt||!Number.isFinite(thresholdR)||thresholdR<=model.thresholdR||thresholdR>1)throw Error('Registration needs a future timestamp and a stricter finite score threshold in (0.10, 1]');
 const payload={schemaVersion:1,mode:'shadow-only',kind:'frozen-score-threshold',registeredAt:now,thresholdR,
  baseModelId:model.id,baseModelSha256:B.MODEL_SHA256,profile:'momentumBoostOne',policy:G.POLICY,runtimeHashes:runtimeHashes(root),
  source:{revision:revision(root),heads:evidence.heads,immutableFiles:evidence.files,closedTrades:evidence.accounts['boost-one'].trades,
   closedTradeCounts:Object.fromEntries(Object.entries(evidence.accounts).map(([k,v])=>[k,v.trades.length])),forecastResearch:evidence.forecastResearch,adaptiveSummarySha256:evidence.adaptiveSummarySha256},
  proposal:'Raise only the frozen model score cutoff. Preserve breakout, ranking, exits, leverage, costs and risk controls. No training or replacement of the pinned model.'};
 const version='shadow-threshold-v1-'+now+'-'+E.sha(payload).slice(0,12),body={...payload,version},candidate={...body,hash:E.sha(body)};
 const account=P.create('crypto',now,candidate.profile),genesis={schemaVersion:1,registration:true,candidateHash:candidate.hash,recordedAt:now,previousHash:null,sourceRevision:payload.source.revision,
  inputs:{marketSha256:null,marketGeneratedAt:null,heads:evidence.heads,immutableFileAdditions:{},sourceFilesSha256:E.manifestHash(evidence.files),quality:{passed:true,errors:[]}},decisionSamples:[],
  accounts:{incumbent:delta(null,account),candidate:delta(null,account)}};
 const genesisHash=E.sha(genesis),directory=safeDirectory(root,BASE),staging=path.join(directory,'.register-'+require('node:crypto').randomUUID()),dest=path.join(directory,version);
 if(fs.existsSync(dest))throw Error('Candidate version already exists; never overwrite it');
 try{
  fs.mkdirSync(staging);fs.mkdirSync(path.join(staging,'observations'));
  fs.writeFileSync(path.join(staging,'candidate.json'),JSON.stringify(candidate)+'\n',{flag:'wx'});
  fs.writeFileSync(path.join(staging,'observations',now+'-'+genesisHash.slice(0,12)+'.json'),JSON.stringify({...genesis,hash:genesisHash})+'\n',{flag:'wx'});
  fs.renameSync(staging,dest);
 }finally{if(fs.existsSync(staging))fs.rmSync(staging,{recursive:true});}
 return candidate;
}
function readObservations(root,candidate){
 const dir=BASE+'/'+candidate.version+'/observations';if(!fs.existsSync(path.join(root,dir)))throw Error('Missing shadow observations: restore immutable records, never recreate this account');
 const chain=E.readChain(root,dir),accounts={};let priorFiles=candidate.source.immutableFiles;
 if(chain.records[0].registration!==true||chain.records[0].recordedAt!==candidate.registeredAt)throw Error('Missing shadow registration record; never reset');
 for(const r of chain.records){
  if(r.candidateHash!==candidate.hash||r.recordedAt<candidate.registeredAt||r.sourceRevision?.length!==40)throw Error('Observation candidate identity/time');
  const nextFiles={...priorFiles};
  for(const [f,h] of Object.entries(r.inputs.immutableFileAdditions)){if(f in nextFiles||!/^[a-f0-9]{64}$/.test(h))throw Error('Observation rewrites an input checkpoint');nextFiles[f]=h;}
  if(E.manifestHash(nextFiles)!==r.inputs.sourceFilesSha256)throw Error('Observation source manifest hash mismatch');priorFiles=nextFiles;
  for(const key of ['incumbent','candidate']){
   const d=r.accounts[key],prior=accounts[key];
   if(!d||!Array.isArray(d.trades)||!Array.isArray(d.events)||!Array.isArray(d.curve)||d.tail.createdAt!==candidate.registeredAt||d.tail.profile!=='momentumBoostOne')throw Error('Observation account identity');
   if(!prior&&r.previousHash!==null||prior&&d.tail.lastProcessed<prior.lastProcessed)throw Error('Observation account chronology');
   accounts[key]={...d.tail,trades:[...(prior?.trades||[]),...d.trades],events:[...(prior?.events||[]),...d.events],curve:[...(prior?.curve||[]),...d.curve]};
  }
 }
 return {...chain,accounts,checkpoint:priorFiles};
}
function delta(prior,next){
 const out={};for(const key of ['trades','events','curve']){
  if(prior&&JSON.stringify(next[key].slice(0,prior[key].length))!==JSON.stringify(prior[key]))throw Error('Shadow attempted to rewrite '+key);
  out[key]=next[key].slice(prior?.[key].length||0);
 }
 const {trades,events,curve,...tail}=next;return {...out,tail};
}
function providers(evidence,market,candidate,now){
 const model=B.loadModel(),maps=B.mapsFor(market,model),latest=new Map(),mismatches=new Set();
 for(const r of evidence.decisions)if(r.recordedAt<=now)for(const q of r.observations)latest.set(q.symbol,{...q,decisionHash:r.hash});
 const make=thresholdR=>(symbol,rows)=>{
  const q=latest.get(symbol),end=rows.at(-1)?.end,base=q&&maps[symbol]?.get(q.indicatorAt);
  if(!q||q.stale||end<q.indicatorAt||end-q.indicatorAt>=H4||now-q.indicatorAt>=H4)return {side:null,at:end,reason:'shadow: no fresh recorded decision',stale:true};
  const fields=['price','candidateSide','breakoutHigh','breakoutLow','breakoutPassed','modelScore','modelPassed','featureReady'];
  if(!base||fields.some(f=>typeof q[f]==='number'?!E.near(q[f],base[f]):q[f]!==base[f])){
   mismatches.add(symbol+':'+q.indicatorAt);return {side:null,at:end,reason:'shadow: recorded decision cannot be reproduced',stale:true};
  }
  const passed=Number.isFinite(q.modelScore)&&q.modelScore>=thresholdR;
  // Exit/trailing controls survive a rejected entry; original recorded decision
  // is mandatory for both arms. There are no fabricated gap-time observations.
  return {...base,indicatorAt:q.indicatorAt,modelId:thresholdR===model.thresholdR?model.id:candidate.version,
   modelPassed:passed,side:q.candidateSide&&q.breakoutPassed&&passed?q.candidateSide:null,target:null,
   reason:'shadow frozen cutoff '+thresholdR+'; source decision '+q.decisionHash};
 };
 return {incumbent:make(model.thresholdR),candidate:make(candidate.thresholdR),latest:[...latest.values()],mismatches};
}
function dataQuality(market,accounts,mismatches,now){
 const errors=[...(market.errors||[])];
 for(const s of ['BTC','ETH','SOL']){
  const source=market.crypto?.[s],rows=source?.frames?.['15m']||[];
  if(!rows.length)errors.push('Missing '+s);
  const completed=rows.filter(r=>r.end<now),last=completed.at(-1);
  if(!last||now-last.end>900000)errors.push(s+' stale execution prices');
  if(rows.some((r,i)=>!Number.isSafeInteger(r.t)||r.end!==r.t+899999||i&&r.t!==rows[i-1].t+900000||!['open','close','high','low','volume'].every(k=>Number.isFinite(r[k]))||r.low<=0||r.high<Math.max(r.open,r.close)||r.low>Math.min(r.open,r.close)||r.volume<0))errors.push(s+' invalid or noncontiguous execution prices');
  errors.push(...(source?.errors||[]),...(source?.revisions||[]).map(()=>s+' revised history'));
 }
 for(const [k,a] of Object.entries(accounts)){if(a.incompleteExecution)errors.push(k+' incomplete execution');if(a.estimatedFundingHours>0)errors.push(k+' estimated funding');}
 errors.push(...[...mismatches].map(s=>'Decision mismatch '+s));return {passed:errors.length===0,errors};
}
function saveAssessment(root,candidate,evidence,chain){
 const accounts=chain.accounts||{incumbent:P.create('crypto',candidate.registeredAt,candidate.profile),candidate:P.create('crypto',candidate.registeredAt,candidate.profile)};
 const completeData=chain.records.every(r=>r.inputs.quality.passed===true),cfg=P.config(accounts.incumbent);
 const report={...G.evaluate(candidate,candidate.source.closedTrades,accounts,chain.records,cfg,{integrity:true,completeData}),
  candidateHash:candidate.hash,observationHead:chain.head,sourceHeads:evidence.heads,sourceRevision:revision(root),forecastResearch:evidence.forecastResearch,
  sourceClosedTradeCounts:Object.fromEntries(Object.entries(evidence.accounts).map(([k,v])=>[k,v.trades.length])),
  riskScope:'15-minute bar-close marks; no proof of intrabar maximum loss. Cost stress is a surcharge on recorded fills, not a hypothetical resimulation.',
  humanReviewRequired:true};
 const hash=E.sha(report),file=BASE+'/'+candidate.version+'/assessments/'+report.asOf+'-'+hash.slice(0,12)+'.json';
 if(fs.existsSync(path.join(root,file))){const prior=E.readFile(root,file).value;if(E.sha(prior)!==E.sha({...report,hash}))throw Error('Assessment collision');}
 else appendFile(root,file,{...report,hash});
 return {...report,hash};
}
function update({root=ROOT,version,now=Date.now()}={}){
 const candidate=readCandidate(root,version),chain=readObservations(root,candidate),last=chain.records.at(-1);
 if(!Number.isSafeInteger(now)||now<candidate.registeredAt||last&&now<last.recordedAt)throw Error('Shadow clock went backward');
 const checkpoint=chain.checkpoint,evidence=E.loadEvidence(root,checkpoint);
 const {value:market,sha256:marketSha256}=E.readFile(root,'simulation/market.json');
 const marketGeneratedAt=inputTimestamp(market.generatedAt);
 if(now<evidence.decisions.at(-1).recordedAt||marketGeneratedAt>now)throw Error('Future input timestamp');
 if(last&&now===last.recordedAt){if(last.registration)return saveAssessment(root,candidate,evidence,chain);if(last.inputs.marketSha256!==marketSha256||JSON.stringify(last.inputs.heads)!==JSON.stringify(evidence.heads))throw Error('Changed input at same observation time');return saveAssessment(root,candidate,evidence,chain);}
 const feed=providers(evidence,market,candidate,now),accounts={};
 for(const key of ['incumbent','candidate']){
  const prior=chain.accounts?.[key]||P.create('crypto',candidate.registeredAt,candidate.profile);
  accounts[key]=P.run(prior,market,{mode:'forward',now,provider:feed[key]});
 }
 const record={schemaVersion:1,candidateHash:candidate.hash,recordedAt:now,previousHash:chain.head,sourceRevision:revision(root),
  inputs:{marketSha256,marketGeneratedAt,sourceMarketGeneratedAt:market.generatedAt,heads:evidence.heads,immutableFileAdditions:Object.fromEntries(Object.entries(evidence.files).filter(([f])=>!(f in checkpoint))),sourceFilesSha256:E.manifestHash(evidence.files),quality:dataQuality(market,accounts,feed.mismatches,now)},
  decisionSamples:feed.latest,accounts:Object.fromEntries(Object.entries(accounts).map(([k,a])=>[k,delta(chain.accounts?.[k],a)]))};
 const hash=E.sha(record),stored={...record,hash};appendFile(root,BASE+'/'+version+'/observations/'+now+'-'+hash.slice(0,12)+'.json',stored);
 return saveAssessment(root,candidate,evidence,{records:[...chain.records,stored],head:hash,accounts});
}
function assess({root=ROOT,version}={}){
 const candidate=readCandidate(root,version),chain=readObservations(root,candidate),evidence=E.loadEvidence(root,chain.checkpoint);
 return saveAssessment(root,candidate,evidence,chain);
}
function audit(root=ROOT){
 const e=E.loadEvidence(root);return {pinnedModel:e.pinnedModel,heads:e.heads,decisionRecords:e.decisions.length,
  closedTrades:Object.fromEntries(Object.entries(e.accounts).map(([k,v])=>[k,v.trades.length])),forecastResearch:e.forecastResearch,
  versions:listVersions(root).map(v=>{const c=readCandidate(root,v,{checkRuntime:false}),chain=readObservations(root,c);E.assertAppendOnly(chain.checkpoint,e.files);return {version:v,observations:chain.records.length,head:chain.head,runtimeCompatible:JSON.stringify(c.runtimeHashes)===JSON.stringify(runtimeHashes(root))};})};
}
function updateCompatible({root=ROOT,now=Date.now()}={}){
 // Verify every historical checkpoint, including paused versions. A code
 // change never migrates an old account or hides a corrupted source record.
 return audit(root).versions.map(v=>{
  if(!v.runtimeCompatible)return {candidateVersion:v.version,status:'paused',promotionCandidate:false,reason:'Frozen runtime differs; retained read-only, never migrated'};
  try{return update({root,version:v.version,now});}catch(e){return {candidateVersion:v.version,status:'blocked',promotionCandidate:false,reason:e.message};}
 });
}
function main(args=process.argv.slice(2)){
 const [command,...rest]=args,options={};for(let i=0;i<rest.length;i+=2){if(!['--version','--threshold-r'].includes(rest[i])||rest[i+1]===undefined)throw Error('Usage: shadow_improvement.cjs audit | register [--threshold-r 0.15] | update [--version ID] | assess --version ID');if(options[rest[i]]!==undefined)throw Error('Duplicate option');options[rest[i]]=rest[i+1];}
 let result;if(command==='audit')result=audit();
 else if(command==='register'){if(options['--version'])throw Error('Registration generates a NEW version');result=register({thresholdR:options['--threshold-r']===undefined?.15:Number(options['--threshold-r'])});}
 else if(command==='update'){if(options['--threshold-r'])throw Error('An existing cutoff cannot change');if(options['--version']){try{result=[update({version:options['--version']})];}catch(e){result=[{candidateVersion:options['--version'],status:'blocked',promotionCandidate:false,reason:e.message}];}}else result=updateCompatible();if(result.some(r=>r.status==='blocked'))process.exitCode=1;}
 else if(command==='assess'&&options['--version']&&!options['--threshold-r'])result=assess({version:options['--version']});
 else throw Error('Unknown shadow command');
 console.log(JSON.stringify(result,null,2));
}
if(require.main===module)try{main();}catch(e){console.error(e.message);process.exitCode=1;}
module.exports={ROOT,BASE,RUNTIME,inputTimestamp,runtimeHashes,listVersions,readCandidate,register,readObservations,providers,dataQuality,update,assess,audit,updateCompatible,main};
