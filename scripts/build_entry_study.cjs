'use strict';
const fs=require('node:fs'),path=require('node:path');
const Study=require('./entry_study.cjs');
const read=p=>JSON.parse(fs.readFileSync(p,'utf8'));
const optional=p=>{try{return read(p)}catch(e){if(e.code==='ENOENT')return null;throw e;}};
function exclusive(p,value){
 fs.mkdirSync(path.dirname(p),{recursive:true});
 fs.writeFileSync(p,Study.canonical(value)+'\n',{flag:'wx'});
}
function publish(p,value){
 fs.writeFileSync(p+'.tmp',Study.canonical(value)+'\n');fs.renameSync(p+'.tmp',p);
}
function load(dir,{checkCode=true}={}){
 const manifestPath=path.join(dir,'manifest.json');
 if(!fs.existsSync(manifestPath)){
  if(fs.existsSync(path.join(dir,'ledger'))&&fs.readdirSync(path.join(dir,'ledger')).length)throw Error('Study manifest missing');
  return null;
 }
 const manifest=read(manifestPath),manifestHash=Study.hash(manifest);
 if(checkCode)Study.checkManifest(manifest);
 const ledger=path.join(dir,'ledger'),files=fs.existsSync(ledger)?fs.readdirSync(ledger).sort():[];
 if(!files.length)throw Error('Study initialization incomplete; preserve manifest and investigate');
 let previousHash=null,previousState=null,tail=null;
 for(let i=0;i<files.length;i++){
  const record=read(path.join(ledger,files[i])),{hash,...payload}=record;
  if(record.sequence!==i||record.previousHash!==previousHash||record.manifestHash!==manifestHash||record.version!==manifest.version||
   Study.hash(payload)!==hash||files[i]!==String(i).padStart(8,'0')+'-'+hash.slice(0,16)+'.json')throw Error('Immutable study chain invalid: '+files[i]);
  const state=JSON.parse(JSON.stringify(record.state));
  if(state.version!==manifest.version||state.createdAt!==manifest.createdAt)throw Error('Study checkpoint version/start mismatch');
  if(previousState&&record.recordedAt<tail.recordedAt)throw Error('Study record clock went backwards');
  state.history=JSON.parse(JSON.stringify(previousState?.history||Object.fromEntries([...manifest.universe,{symbol:'SPY'}].map(q=>[q.symbol,[]]))));
  for(const [symbol,bars] of Object.entries(record.bars))for(const bar of bars){
   if(!state.history[symbol]||bar.t<=(state.history[symbol].at(-1)?.t??-Infinity))throw Error('Previously observed study price changed');
   state.history[symbol].push(bar);
  }
  state.existingObservations=[...(previousState?.existingObservations||[]),...record.existingObservations];
  for(const key of ['indicator','control']){
   const a=state.accounts[key],before=previousState?.accounts[key];
   a.events=[...(before?.events||[]),...record.events[key]];
   a.trades=[...(before?.trades||[]),...record.trades[key]];
   a.curve=[...(before?.curve||[]),...record.curves[key]];
   if(Study.hash({events:a.events,trades:a.trades,curve:a.curve})!==record.accountHistoryHashes[key])throw Error('Study history prefix/hash changed');
  }
  for(const observation of record.inputs?.observations||[]){
   const e=Study.entry(state.history[observation.entry.symbol].filter(r=>r.date<=observation.entry.asOf),observation.entry.symbol,record.recordedAt);
   if(Study.hash(e.history)!==observation.historyHash)throw Error('Causal study history hash changed');
   const {history,...entryInputs}=e;
   if(Study.canonical(entryInputs)!==Study.canonical(observation.entry))throw Error('Recorded indicator inputs changed');
   if(checkCode){
    const plan=Study.assess(state.history[e.symbol].filter(r=>r.date<=e.asOf),e.symbol,record.inputs.credit,record.recordedAt).plan;
    const sourceUnavailable=e.asOf!==state.history.SPY.at(-1).date||(record.inputs.quality||[]).some(q=>q.startsWith(e.symbol+':'));
    if(observation.summary.code!==(sourceUnavailable?'unavailable':plan.code)||
     observation.summary.holding.code!==(sourceUnavailable?'unavailable':plan.holding.code))throw Error('Frozen entry/holding decision changed');
    for(const [field,value] of Object.entries({score:plan.ts,levelBasis:plan.levelBasis,rangeBasis:plan.range.basis,range:plan.range.value,
     breakoutLevel:plan.breakoutLevel,exitLevel:plan.exitLevel,stop:plan.stop,target:plan.target1,rr:plan.rr,riskPct:plan.riskPct,
     strategy:plan.strategy,relativeVolume:plan.indicators.relativeVolume}))
     if(Study.canonical(observation.summary[field])!==Study.canonical(value))throw Error('Frozen rule assessment changed: '+field);
   }
  }
  previousHash=hash;previousState=state;tail=record;
 }
 const cachePath=path.join(dir,'latest.json');
 if(fs.existsSync(cachePath)){
  const cache=read(cachePath);
  // A stale cache can be rebuilt after a crash; a shortened chain cannot.
  if(cache.sequence>tail.sequence||cache.sequence===tail.sequence&&cache.ledgerHash!==tail.hash)throw Error('Study ledger truncated or replaced');
 }
 return {manifest,manifestHash,tail,state:previousState,files};
}
function append(dir,manifest,prior,result,now){
 const state=JSON.parse(JSON.stringify(result.state)),bars={},trades={},curves={},accountHistoryHashes={};
 for(const [s,rows] of Object.entries(state.history))bars[s]=rows.slice(prior?.state.history[s].length??0);
 delete state.history;
 const existingObservations=state.existingObservations.slice(prior?.state.existingObservations.length??0);
 delete state.existingObservations;
 for(const [key,a] of Object.entries(state.accounts)){
  trades[key]=a.trades.slice(prior?.state.accounts[key].trades.length??0);
  curves[key]=a.curve.slice(prior?.state.accounts[key].curve.length??0);
  accountHistoryHashes[key]=Study.hash({events:a.events,trades:a.trades,curve:a.curve});
  delete a.events;delete a.trades;delete a.curve;
 }
 const payload={schemaVersion:1,version:manifest.version,sequence:prior?prior.tail.sequence+1:0,
  manifestHash:Study.hash(manifest),previousHash:prior?.tail.hash??null,recordedAt:now,
  events:result.events,inputs:result.inputs,state,bars,trades,curves,existingObservations,accountHistoryHashes};
 const hash=Study.hash(payload),record={...payload,hash};
 const filename=String(payload.sequence).padStart(8,'0')+'-'+hash.slice(0,16)+'.json';
 exclusive(path.join(dir,'ledger',filename),record);return record;
}
function build(market,now=Date.now(),simulationFolder=path.resolve(__dirname,'../simulation'),options={}){
 const dir=path.join(simulationFolder,'entry-study',Study.VERSION);
 const credit=options.credit!==undefined?options.credit:optional(path.join(simulationFolder,'../market/latest.json'));
 const existing=options.existing!==undefined?options.existing:optional(path.join(simulationFolder,'state.json'))?.accounts?.stocks??null;
 const existingCostRisk=options.existingCostRisk!==undefined?options.existingCostRisk:require('./paper_engine.cjs').CONFIG.stocks;
 let prior=load(dir),manifest=prior?.manifest,record,state;
 if(!prior){
  manifest=Study.manifest(market,now);
  state=Study.create(manifest,market,existing,existingCostRisk);
  // Genesis is cash-only. Warmup history cannot create old signals or fills.
  state.qualityKey=Study.hash([]);
  exclusive(path.join(dir,'manifest.json'),manifest);
  record=append(dir,manifest,null,{state,events:{indicator:[],control:[]},
   inputs:{kind:'initialization',credit,marketGeneratedAt:market.generatedAt,existing:Study.snapshotExisting(existing,existingCostRisk)}},now);
 }else{
  const result=Study.advance(prior.state,manifest,market,credit,existing,now,existingCostRisk);
  record=result.changed?append(dir,manifest,prior,result,now):prior.tail;
  state=result.state;
 }
 const comparison=Study.comparison(state),summary={schemaVersion:1,version:manifest.version,
  createdAt:manifest.createdAt,generatedAt:record.recordedAt,sequence:record.sequence,ledgerHash:record.hash,
  manifestHash:Study.hash(manifest),universe:manifest.universe,costRisk:manifest.costRisk,comparison,
  accounts:Object.fromEntries(Object.entries(state.accounts).map(([k,a])=>[k,
   {cash:a.cash,positions:a.positions,pending:a.pending,trades:a.trades,curve:a.curve,events:a.events.slice(-60),signals:a.signals}])),
  warnings:state.warnings,forwardOnly:true,performanceValidated:false,autoPromotion:false,
  notes:['PR #19 threshold는 미검증 design hypothesis. 첫 실행 후 새로 관측된 일별 종가만 신호를 만듭니다.',
   '기존 stock 계정·ledger·replay는 이 study에서 읽기만 합니다. 같은 시작 시점의 기존 규칙 대조군도 별도 현금 계정입니다.',
   '신호와 보유 대응은 관측 후 시작하는 봉에만 적용합니다. OHLC 없는 봉은 체결을 만들지 않습니다.',
   '동일 비용·계좌 위험 가정, 서로 다른 진입·청산 규칙. 배당·세금·환전·분할 자동 보정 제외.',
   '고정된 현재 종목 universe의 forward 관측. S&P 500 전체 또는 과거 구성종목 수익성을 대표하지 않습니다.']};
 publish(path.join(dir,'latest.json'),summary);
 return summary;
}
if(require.main===module){
 const folder=path.resolve(__dirname,'../simulation');
 const result=build(read(path.join(folder,'market.json')),Date.now(),folder);
 console.log(JSON.stringify({version:result.version,createdAt:result.createdAt,sequence:result.sequence,comparison:result.comparison},null,2));
}
module.exports={build,load,append};
