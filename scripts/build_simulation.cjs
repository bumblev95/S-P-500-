'use strict';
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const P=require('./paper_engine.cjs'),S=require('../assets/simulation-signals.js');
const root=path.resolve(__dirname,'..'),folder=path.join(root,'simulation');
const read=(name,fallback)=>{try{return JSON.parse(fs.readFileSync(path.join(folder,name),'utf8'))}catch(e){if(e.code==='ENOENT')return fallback;throw e;}};
const write=(name,value)=>{const dest=path.join(folder,name);fs.mkdirSync(path.dirname(dest),{recursive:true});fs.writeFileSync(dest+'.tmp',JSON.stringify(value));fs.renameSync(dest+'.tmp',dest);};
function build(now=Date.now()){
 const market=read('market.json',null);if(!market)throw Error('Public market inputs missing');
 let live=read('state.json',{version:S.VERSION,createdAt:now,accounts:{},ledgerHash:null});
 if(!Object.keys(live.accounts).length&&((market.crypto?.BTC?.frames?.['15m']?.length||0)<70||(market.stocks?.SPY?.rows?.length||0)<210))throw Error('Initial paper accounts require complete benchmark history; no empty performance will be published');
 if(live.version!==S.VERSION)throw Error('Preserve previous experiment; a new version needs separate accounts');
 let replay=read('replay.json',null);
 if(!replay){
  replay={version:S.VERSION,generatedAt:now,sourceGeneratedAt:market.generatedAt,mode:'replay',accounts:{}};
  for(const asset of ['crypto','stocks']){
   if(!Object.keys(market[asset]||{}).length)continue;
   replay.accounts[asset]=P.report(P.run(P.create(asset,now),market,{mode:'replay',now}));
  }
  if(Object.keys(replay.accounts).length===2)write('replay.json',replay);
 }
 const delta=[];
 for(const asset of ['crypto','stocks']){
  const prior=live.accounts[asset]||P.create(asset,now),n=prior.events.length;
  const next=P.run(prior,market,{mode:'forward',now});
  if(JSON.stringify(next.trades.slice(0,prior.trades.length))!==JSON.stringify(prior.trades))throw Error('Previously closed trades changed');
  delta.push(...next.events.slice(n).map(e=>({...e,asset})));live.accounts[asset]=next;
 }
 if(delta.length||live.ledgerHash===null){
  const record={version:S.VERSION,recordedAt:now,previousHash:live.ledgerHash,events:delta,
   accounts:Object.fromEntries(Object.entries(live.accounts).map(([asset,a])=>[asset,{equity:P.equity(a),cash:a.cash,positions:a.positions.length,trades:a.trades.length}]))};
  const hash=crypto.createHash('sha256').update(JSON.stringify(record)).digest('hex');
  write('ledger/'+now+'-'+hash.slice(0,12)+'.json',{...record,hash});live.ledgerHash=hash;
 }
 live.updatedAt=now;write('state.json',live);
 const output={schemaVersion:1,version:S.VERSION,generatedAt:now,marketGeneratedAt:market.generatedAt,errors:market.errors||[],
  forward:{createdAt:live.createdAt,accounts:Object.fromEntries(Object.entries(live.accounts).map(([k,a])=>[k,P.report(a)]))},
  replay,replayFrozen:true,config:P.CONFIG,
  notes:['코인·주식 각각 $10,000 USD의 독립 가상 계좌. 실제 주문·입출금 없음.',
   '과거 재현은 고정된 초기 자료의 탐색 실험. 지금부터 모의운용과 구분합니다.',
   '코인 15분봉 세 패턴. 주식 20종목 중 상승 추세·눌림/돌파로 최대 5종목, 동일 업종 최대 2종목.',
   '모의실험 전용 신호이며 기존 AI 예측의 검증 조건을 통과했다는 뜻이 아닙니다.',
   '코인 진입 시 1배 증거금 가정. 거래소별 청산·교차 증거금 엔진은 재현하지 않습니다.',
   '주식 배당·세금·환전 제외. 현재 고른 종목 집합을 과거에 적용한 선택·생존편향이 있습니다.',
   '코인 펀딩률은 실제 과거 자료, 계산 기준 가격은 봉 가격 대용치. 누락 시 시간당 0.01% 지급 가정.',
   '예약 신호 이후의 다음 가용 봉 시가에 체결. 같은 봉 손절·목표 동시 도달은 손절 우선.',
   '자동 갱신은 약 15분 간격을 목표로 하며 GitHub Actions 지연 시 늦어집니다. 틈새 시간에 나타났다 사라진 미기록 신호를 소급 체결하지 않습니다.']};
 output.preview={crypto:{},stocks:{}};output.tradeWindows={};
 output.leveraged=require('./build_leveraged.cjs').build(market,now,folder);
 output.wide=require('./build_leveraged.cjs').build(market,now,folder,'wideRecovery');
 output.methodResearch=read('method-research/latest.json',null);
 output.publicBotResearch=read('public-bot-research/latest.json',null);
 output.longResearch=read('long-research/latest.json',null);
 output.research=read('research/latest.json',null);
 output.researchAttempt=read('research/attempt.json',null);
 for(const asset of ['crypto','stocks']){
  const sources=market[asset]||{};
  const candles=s=>asset==='crypto'?sources[s]?.frames?.['15m']||[]:sources[s]?.rows||[];
  for(const sym of Object.keys(sources))output.preview[asset][sym]=candles(sym).slice(-100);
  for(const group of asset==='crypto'?[output,output.leveraged,output.wide]:[output])for(const mode of ['forward','replay'])for(const trade of group[mode]?.accounts?.[asset]?.trades?.slice(-30)||[]){
   const rows=candles(trade.symbol),i=rows.findIndex(r=>r.t>=trade.entryAt),j=rows.findIndex(r=>r.end>=trade.exitAt);
   if(i>=0&&j>=0)output.tradeWindows[trade.id]=rows.slice(Math.max(0,i-25),j+12);
  }
 }
 // Full histories and account state remain public, but the UI only needs curves,
 // trades and recent events; avoid downloading all observed signal logs on phones.
 for(const mode of ['forward','replay'])for(const a of Object.values(output[mode]?.accounts||{}))a.events=a.events.slice(-60);
 for(const group of [output.leveraged,output.wide])for(const mode of ['forward','replay'])group[mode].accounts.crypto.events=group[mode].accounts.crypto.events.slice(-60);
 write('latest.json',output);
 console.log(JSON.stringify(Object.fromEntries(['forward','replay'].map(mode=>[mode,Object.fromEntries(Object.entries(output[mode]?.accounts||{}).map(([asset,a])=>[asset,{equity:a.equity,trades:a.trades.length,positions:a.positions.length,pending:a.pending.length,winRate:a.winRate,drawdown:a.maxDrawdown}]))])),null,2));
 return output;
}
if(require.main===module)build();module.exports={build};
