'use strict';
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const P=require('./paper_engine.cjs'),T=require('./trend_methods.cjs');
const VERSION='fixed-4h-trend-comparison-v1',ROOT=path.resolve(__dirname,'..');
function evaluate(market,maps,start,end,stress=false){
 const provider=(symbol,rows)=>maps[symbol]?.get(rows.at(-1).end)||{side:null};
 const a=P.run(P.create('crypto',start,stress?'trendResearchStress':'trendResearch'),market,{mode:'replay',startAt:start,now:end+1,provider});
 const cfg=P.config(a);
 // Every period is fully liquidated, including exit costs; no hidden open losses.
 for(const p of [...a.positions])P.close(a,p,a.marks[p.symbol],a.marketAsOf,'평가 기간 종료',cfg,end,'close');
 const r=P.report(a),last=r.curve.at(-1);
 r.maxDrawdown=Math.max(r.maxDrawdown,1-r.equity/r.highWater);
 if(last)last.equity=r.equity;
 const step=Math.max(1,Math.ceil(r.curve.length/240));
 return {equity:r.equity,return:r.return,maxDrawdown:r.maxDrawdown,trades:r.trades.length,winRate:r.winRate,profitFactor:r.profitFactor,
  fees:r.fees,funding:r.funding,slippage:r.slippage,estimatedFundingHours:r.estimatedFundingHours,warnings:r.warnings,
  averageHoldHours:r.trades.length?r.trades.reduce((s,t)=>s+(t.exitAt-t.entryAt)/3600000,0)/r.trades.length:null,
  longTrades:r.trades.filter(t=>t.side==='long').length,shortTrades:r.trades.filter(t=>t.side==='short').length,
  curve:r.curve.filter((v,i)=>i%step===0||i===r.curve.length-1).map(v=>({at:v.at,equity:v.equity})),
  closed:r.trades.map(t=>({symbol:t.symbol,side:t.side,entryAt:t.entryAt,exitAt:t.exitAt,entry:t.entry,exit:t.exit,qty:t.qty,net:t.net,fee:t.entryFee+t.exitFee,funding:t.funding,reason:t.exitReason}))};
}
function benchmark(market,start,end){
 const rows=market.crypto.BTC.frames['15m'].filter(r=>r.t>=start&&r.end<=end),cfg=P.TREND;
 const qty=10000/(rows[0].close*(1+cfg.slip)*(1+cfg.fee));let high=10000,dd=0;
 for(const r of rows){const value=qty*r.close;high=Math.max(high,value);dd=Math.max(dd,1-value/high);}
 const equity=qty*rows.at(-1).close*(1-cfg.slip)*(1-cfg.fee);dd=Math.max(dd,1-equity/high);
 return {equity,return:equity/10000-1,maxDrawdown:dd};
function build(){
 const cache=process.env.PAPER_LONG_CACHE||'/tmp/paper-long-cache',file=path.join(cache,'market.json'),manifest=JSON.parse(fs.readFileSync(path.join(cache,'manifest.json')));
 if(manifest.errors.length)throw Error('Incomplete archive collection');
 const market=JSON.parse(fs.readFileSync(file)),end=Math.min(...Object.values(manifest.coverage).map(v=>v.end)),folder=path.join(ROOT,'simulation/method-research');
 fs.mkdirSync(folder,{recursive:true});const latest=path.join(folder,'latest.json');
 if(fs.existsSync(latest)){const old=JSON.parse(fs.readFileSync(latest));if(old.version===VERSION&&old.dataEnd===end){console.log('Fixed methods already evaluated for this archive end');return;}}
 const now=Date.now(),report={version:VERSION,generatedAt:now,dataEnd:end,status:'과거 비교 실험 · 운용 적용 보류',deployed:false,coverage:manifest.coverage,sourceHash:crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex'),methods:T.METHODS,periods:[],
  notes:[
   '세 방법의 매개변수를 결과 계산 전에 고정했습니다. 이미 이전 연구에서 확인한 2024~2026년을 재사용한 탐색 결과이며, 독립적인 미래 검증이 아닙니다.',
   '2020년부터의 기록으로 과거 지표를 준비하고 2024년·2025년·2026년 이후 각 연도를 별도 $10,000으로 재현합니다. 연도 수익률을 합산하지 않습니다.',
   '완료된 4시간봉만 판단에 사용하고 다음 15분봉 시가에 진입합니다. 추적 손절은 다음 봉부터 적용하고 추세 이탈은 다음 시가에 종료합니다.',
   'BTC 5배·ETH/SOL 3배 격리 가정, 거래당 위험 예산 1%, 전체 위험 3%, 명목 노출 2배 한도. 낙폭 10%·20%에서 규모 축소, 일일 3% 신규 진입 중단을 유지합니다.',
   '초기·추적 손절 4시간 ATR의 2.5배, 고정 익절 없음, 최대 보유 30일. 손절선은 유리한 방향으로만 움직이며 물타기하지 않습니다.',
   '수수료 0.045%·슬리피지 0.02% 편도와 실제 펀딩을 반영합니다. 비용 2배 열은 수수료·슬리피지만 2배로 재실행한 민감도이며 펀딩은 같습니다.',
   '수량 계산에 8시간 추정 펀딩 여유를 포함하지만, 장기 보유의 실제 누적 펀딩·갭으로 거래 손실은 초기 예산보다 커질 수 있습니다.',
   'BTC 현물 보유는 배율 없는 비교이며 진입·종료 비용을 반영합니다. 전략은 연말·자료 종료 시 미결제 포지션도 비용을 내고 종료합니다.',
   '최대 낙폭은 15분봉 마감 평가액 기준. 과거 수수료 등급·정확한 마크가격 청산 엔진은 생략하며, 원자료 누락 및 펀딩 추정은 결과에 표시합니다.',
   '상장폐지 종목을 포함한 전체 시장이 아니라 현재 선택한 BTC·ETH·SOL만 사용합니다. Binance 과거 결과를 Hyperliquid 진행 계좌 성적으로 간주하지 않습니다.',
   '과거 수익만으로 기본 전략을 교체하지 않습니다. 새 자료와 발표 이후 거래에서 수익·낙폭을 다시 확인해야 합니다.'
  ],references:[{title:'Time Series Momentum — research motivation; different horizons and markets',url:'https://www.aqr.com/Insights/Research/Journal-Article/Time-Series-Momentum'},{title:'Binance public data',url:'https://github.com/binance/binance-public-data'}]};
 const maps=Object.fromEntries(T.METHODS.map(m=>[m.id,Object.fromEntries(Object.entries(market.crypto).map(([s,v])=>[s,T.signals(v.frames['15m'],m.id)]))]));
 for(let year=2024;year<=new Date(end).getUTCFullYear();year++){
  const start=Date.UTC(year,0,1),finish=Math.min(end,Date.UTC(year+1,0,1)-1),period={year,start,end:finish,benchmark:benchmark(market,start,finish),results:[]};
  for(const method of T.METHODS){
   const base=evaluate(market,maps[method.id],start,finish),stress=evaluate(market,maps[method.id],start,finish,true);
   period.results.push({method:method.id,...base,stress:{equity:stress.equity,return:stress.return,maxDrawdown:stress.maxDrawdown,trades:stress.trades}});
   console.log(JSON.stringify({year,method:method.id,equity:base.equity,return:base.return,maxDrawdown:base.maxDrawdown,trades:base.trades,fees:base.fees,estimatedFundingHours:base.estimatedFundingHours,stressReturn:stress.return}));
  }
  report.periods.push(period);
 }
 report.screening=T.METHODS.map(m=>{const rows=report.periods.map(p=>p.results.find(r=>r.method===m.id));return {method:m.id,positivePeriods:rows.filter(r=>r.return>0).length,totalPeriods:rows.length,worstDrawdown:Math.max(...rows.map(r=>r.maxDrawdown)),totalTrades:rows.reduce((s,r)=>s+r.trades,0),passesExploratoryScreen:rows.every(r=>r.return>0&&r.stress.return>0&&r.maxDrawdown<=.10)&&rows.reduce((s,r)=>s+r.trades,0)>=100};});
 report.manifestFile=now+'-manifest.json';fs.writeFileSync(path.join(folder,report.manifestFile),JSON.stringify(manifest));
 const text=JSON.stringify(report);fs.writeFileSync(path.join(folder,now+'-report.json'),text);fs.writeFileSync(latest,text);
 console.log('Fixed-method comparison complete',JSON.stringify(report.screening));
}
if(require.main===module)build();module.exports={evaluate,benchmark,build};
