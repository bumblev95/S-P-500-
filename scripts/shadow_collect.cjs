'use strict';
// Input acquisition only: keep every frozen runtime hash and account unchanged.
const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),cp=require('node:child_process');
const S=require('./shadow_improvement.cjs'),E=require('./shadow_evidence.cjs');
const STEP=900000,BOUNDARY_WINDOW=120000,RETRY_LIMIT=3,RETRY_DELAY=10000,RETRY_BUDGET=120000;
const INPUTS='simulation/self-improvement/inputs';
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));

function staleOnly(quality){
 return quality.errors.length>0&&quality.errors.every(e=>/^(BTC|ETH|SOL) stale execution prices$/.test(e));
}
function boundaryRetry(market,now){
 const generatedAt=S.inputTimestamp(market.generatedAt),boundary=Math.floor(now/STEP)*STEP;
 const quality=S.dataQuality(market,{},new Set(),now);
 // A grace window for acquiring a new input, never for accepting a stale input.
 // The original snapshot itself must have passed the unchanged gate at collection.
 return generatedAt<boundary&&generatedAt>=boundary-BOUNDARY_WINDOW&&now-boundary<BOUNDARY_WINDOW&&
  generatedAt<=now&&S.dataQuality(market,{},new Set(),generatedAt).passed&&staleOnly(quality)&&
  Object.values(quality.executionPrices).filter(p=>p.stale).every(p=>p.barEndAt===boundary-STEP-1);
}
function assertExtension(prior,next,now){
 const cutoff=S.inputTimestamp(next.generatedAt);
 if(cutoff<S.inputTimestamp(prior.generatedAt)||cutoff>now)throw Error('Refreshed snapshot has a backward/future collection timestamp');
 if(next.schemaVersion!==prior.schemaVersion||JSON.stringify(next.stocks)!==JSON.stringify(prior.stocks))throw Error('Refresh changed non-crypto inputs');
 for(const symbol of ['BTC','ETH','SOL']){
  const a=prior.crypto[symbol],b=next.crypto?.[symbol];
  if(!b)throw Error('Refresh missing '+symbol);
  for(const [frame,rows] of Object.entries(a.frames)){
   const fresh=b.frames?.[frame];
   if(!Array.isArray(fresh)||JSON.stringify(fresh.slice(0,rows.length))!==JSON.stringify(rows))throw Error('Refresh rewrote completed '+symbol+' '+frame+' candles');
   if(fresh.slice(rows.length).some(r=>!Number.isSafeInteger(r.end)||r.end>=cutoff))throw Error('Refresh included an unfinished/future candle');
  }
  const funding=a.funding||[],fresh=b.funding||[];
  if(JSON.stringify(fresh.slice(0,funding.length))!==JSON.stringify(funding))throw Error('Refresh rewrote historical funding');
  if(fresh.slice(funding.length).some(r=>!Number.isSafeInteger(r.time)||r.time>=cutoff))throw Error('Refresh included future funding');
 }
}
function archiveInput(root,raw){
 const hash=E.bytesHash(raw),relative=INPUTS+'/'+hash+'.json';let dir=root;
 if(fs.lstatSync(root).isSymbolicLink())throw Error('Unsafe shadow input root');
 for(const part of INPUTS.split('/')){
  dir=path.join(dir,part);
  if(!fs.existsSync(dir))fs.mkdirSync(dir);
  if(fs.lstatSync(dir).isSymbolicLink()||!fs.statSync(dir).isDirectory())throw Error('Unsafe shadow input directory');
 }
 const file=path.join(root,relative);
 if(fs.existsSync(file)){
  if(fs.lstatSync(file).isSymbolicLink()||!fs.readFileSync(file).equals(raw))throw Error('Immutable shadow input changed');
 }else{
  const temporary=path.join(dir,'.pending-'+require('node:crypto').randomUUID());
  try{fs.writeFileSync(temporary,raw,{flag:'wx'});fs.linkSync(temporary,file);}
  finally{if(fs.existsSync(temporary))fs.unlinkSync(temporary);}
 }
 return relative;
}
function recollect({root,timeoutMs}){
 const temp=fs.mkdtempSync(path.join(os.tmpdir(),'shadow-public-input-')),output=path.join(temp,'market.json');
 try{
  cp.execFileSync('python',['scripts/collect_simulation_data.py','--crypto-only','--output',output],{cwd:root,timeout:timeoutMs,stdio:['ignore','inherit','pipe']});
  return fs.readFileSync(output);
 }finally{fs.rmSync(temp,{recursive:true,force:true});}
}
function updateAt(root,version,now){
 if(!version)return S.updateCompatible({root,now});
 try{return [S.update({root,version,now})];}
 catch(e){return [{candidateVersion:version,status:'blocked',promotionCandidate:false,reason:e.message}];}
}
async function collect({root=S.ROOT,version,clock=Date.now,refresh=recollect,wait=sleep}={}){
 // Audit all checkpoints before any network request, including paused versions.
 const audit=S.audit(root),active=audit.versions.some(v=>v.runtimeCompatible&&(!version||v.version===version));
 if(!active)return updateAt(root,version,clock());
 const file=path.join(root,'simulation/market.json');
 const prior=E.readFile(root,'simulation/market.json').value,original=fs.readFileSync(file);
 if(!boundaryRetry(prior,clock()))return updateAt(root,version,clock());
 const deadline=clock()+RETRY_BUDGET;let quality;
 for(let attempt=0;attempt<RETRY_LIMIT;attempt++){
  const timeoutMs=deadline-clock();if(timeoutMs<=0)break;
  // Public OHLC/funding only. This never invokes an operating-account builder.
  const raw=await refresh({root,timeoutMs}),market=JSON.parse(raw),now=clock();
  assertExtension(prior,market,now);quality=S.dataQuality(market,{},new Set(),now);
  if(now>=deadline)break;
  if(quality.passed){
   // Retain exact source bytes matching observation.inputs.marketSha256. The
   // disposable local substitution is restored even if frozen execution blocks.
   archiveInput(root,raw);
   try{fs.writeFileSync(file,raw);return updateAt(root,version,clock());}
   finally{fs.writeFileSync(file,original);}
  }
  if(!staleOnly(quality))throw Error('Shadow refresh not ready: '+JSON.stringify(quality));
  if(attempt+1<RETRY_LIMIT&&clock()+RETRY_DELAY<deadline)await wait(RETRY_DELAY);
 }
 throw Error('Shadow boundary refresh exhausted; no account advanced: '+JSON.stringify(quality));
}
async function main(args=process.argv.slice(2)){
 if(args.length&&!(args.length===2&&args[0]==='--version'&&args[1]))throw Error('Usage: shadow_collect.cjs [--version ID]');
 const result=await collect({version:args[1]});console.log(JSON.stringify(result,null,2));
 if(result.some(r=>r.status==='blocked'))process.exitCode=1;
}
if(require.main===module)main().catch(e=>{console.error(e.message);process.exitCode=1;});
module.exports={STEP,BOUNDARY_WINDOW,RETRY_LIMIT,RETRY_DELAY,RETRY_BUDGET,INPUTS,boundaryRetry,assertExtension,archiveInput,collect,main};
