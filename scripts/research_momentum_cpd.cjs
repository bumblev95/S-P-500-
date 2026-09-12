'use strict';
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const C=require('./momentum_cpd.cjs'),R=require('./research_trend_methods.cjs'),P=require('./paper_engine.cjs');
const ROOT=path.resolve(__dirname,'..'),hash=f=>crypto.createHash('sha256').update(fs.readFileSync(f)).digest('hex');
function sliceMarket(market,start,end){
 // Preserve the full published settlement schedule. Truncating it at the
 // evaluation end makes the shared engine misclassify the last non-settlement
 // hours as missing funding. Rates after a trade's timestamp are never charged.
 return {...market,crypto:Object.fromEntries(Object.entries(market.crypto).map(([s,v])=>[s,{...v,frames:{'15m':v.frames['15m'].filter(r=>r.t>=start&&r.end<=end)},funding:v.funding}]))};
}
function compare(market,spec){
 const all=Object.fromEntries(Object.entries(market.crypto).map(([s,v])=>[s,C.signals(v.frames['15m'],spec)]));
 const small=sliceMarket(market,spec.start,spec.end),results=[];
 for(const [method,key] of [['momentum14','base'],['momentum14_cpd','maps']]){
  const maps=Object.fromEntries(Object.entries(all).map(([s,v])=>[s,v[key]]));
  const a=R.evaluate(small,maps,spec.start,spec.end),stress=R.evaluate(small,maps,spec.start,spec.end,true);
  if(Math.abs(a.equity-10000-a.closed.reduce((s,t)=>s+t.net,0))>1e-5)throw Error('Account does not reconcile');
  // Annotate CPD-triggered next-open exits without changing the shared engine.
  if(method==='momentum14_cpd')for(const t of a.closed){
   const q=maps[t.symbol].get(t.exitAt-1);
   if(t.reason==='4시간 추세 이탈'&&q?.cpd?.[t.side==='long'?'blockLong':'blockShort'])t.reason='변화 감지 · 반대 흐름 청산';
  }
  results.push({method,...a,stress:{equity:stress.equity,return:stress.return,maxDrawdown:stress.maxDrawdown,trades:stress.trades},
   cpdExits:a.closed.filter(t=>t.reason==='변화 감지 · 반대 흐름 청산').length});
 }
 const [base,cpd]=results;
 const out={...spec,results,deltaReturn:cpd.return-base.return,deltaDrawdown:cpd.maxDrawdown-base.maxDrawdown,
  benchmark:R.benchmark(small,spec.start,spec.end),diagnostics:Object.fromEntries(Object.entries(all).map(([s,v])=>[s,{prior:v.prior,...v.counts,maxDiscardedMass:v.maxDiscardedMass,events:v.events}]))};
 console.log(JSON.stringify({label:spec.label,base:base.return,cpd:cpd.return,baseDD:base.maxDrawdown,cpdDD:cpd.maxDrawdown,trades:[base.trades,cpd.trades],stress:[base.stress.return,cpd.stress.return],blocked:Object.values(all).reduce((s,v)=>s+v.counts.blockedSignals,0)}));
 return out;
}
function build(){
 const folder=path.join(ROOT,'simulation/cpd-research');fs.mkdirSync(folder,{recursive:true});
 const cache=process.env.PAPER_LONG_CACHE||'/tmp/paper-long-cache',marketFile=path.join(cache,'market.json'),manifestFile=path.join(cache,'manifest.json');
 const manifest=JSON.parse(fs.readFileSync(manifestFile));if(manifest.errors.length)throw Error('Incomplete archive data');
 const now=Date.now(),end=Math.min(...Object.values(manifest.coverage).map(v=>v.end));
 const plan={version:C.RULES.version,createdAt:now,rules:C.RULES,methods:['momentum14','momentum14_cpd'],
  dataEnd:end,archiveManifestHash:hash(manifestFile),marketHash:hash(marketFile),
  recentMarketHash:hash(path.join(ROOT,'simulation/market.json')),
  sourceHashes:Object.fromEntries(['momentum_cpd.cjs','research_momentum_cpd.cjs','paper_engine.cjs','research_trend_methods.cjs','trend_methods.cjs'].map(f=>[f,hash(path.join(__dirname,f))])),
  calibration:'For each year, fit prior return variance using the previous year up to 30 days before evaluation. The final 30 days warm the online posterior. Recent replay uses its first 14 days for the prior.',
  selection:'One frozen specification; no search, no best-parameter selection. All periods are exploratory because their results were previously inspected.',
  execution:{...P.TREND},decision:'No automatic live promotion. Report return, drawdown, doubled-cost sensitivity, blocked signals and exit counts for every period.'};
 const planFile=now+'-plan.json';fs.writeFileSync(path.join(folder,planFile),JSON.stringify(plan));
 const market=JSON.parse(fs.readFileSync(marketFile));
 const report={version:C.RULES.version,generatedAt:now,status:'추세 반전 감지 · 고정 규칙 비교 실험',deployed:false,planFile,planHash:hash(path.join(folder,planFile)),rules:C.RULES,coverage:manifest.coverage,
  methods:[{id:'momentum14',name:'기존 14일 모멘텀'},{id:'momentum14_cpd',name:'14일 모멘텀 + 변화 감지'}],periods:[],notes:[
   '이번 실험은 통계적 Bayesian Online Changepoint Detection(BOCPD) 하나를 추가한 비교입니다. 딥러닝 학습 또는 논문의 Gaussian Process + LSTM 전체 재현이 아닙니다.',
   '4시간 로그수익률의 평균·분산 변화에 대한 Student-t 예측분포와 온라인 실행 길이 사후분포를 계산합니다. 최근 6봉 안의 변화 확률 50% 이상이면서 1일 가격 변화가 반대 방향으로 0.5 ATR 이상이면 해당 방향을 6봉(24시간) 보류하고 보유분을 다음 시가에 정리합니다.',
   '변화 확률은 모델 내부의 변화 감지 수치이며 다음 가격 방향의 적중 확률이 아닙니다. 변화 시점 감지는 사후 확정된 저점·고점 정보를 사용하지 않습니다.',
   '사전 평균 0, 연도별 이전 자료의 수익률 분산, 위험률 1/126, Normal-Inverse-Gamma kappa=1·alpha=3. 관측 42개 이상부터 적용하며 실행 길이 가설 128개를 유지합니다. 버린 확률 질량 최대치를 종목별 기록합니다.',
   '평가 연도 이전에 사전분포를 정하고, 마지막 30일로 온라인 상태를 준비합니다. 평가 중에는 완료된 봉만 순서대로 반영합니다. 매개변수는 결과 계산 전에 한 가지로 고정했으며 수익률에 맞춰 재조정하지 않았습니다.',
   '동일한 별도 $10,000, BTC 5배·ETH/SOL 3배, 거래당 1% 위험 예산, 기존 증거금·명목 노출·일일 손실·낙폭 축소 한도를 적용합니다. 감지 시 진입 보류와 청산만 달라지며 손절 폭과 레버리지는 그대로입니다.',
   '초기·추적 손절 4시간 ATR 2.5배, 고정 익절 없음, 최대 30일. 변화 감지를 이유로 즉시 반대 포지션을 강제로 열거나 물타기하지 않습니다.',
   '편도 수수료 0.045%·슬리피지 0.02%, 실제 펀딩 반영. 비용 2배는 수수료·슬리피지만 두 배입니다. 모든 평가 종료 시 미결제 포지션을 비용을 내고 정리합니다.',
   '기존 엔진과 동일하게 공개된 과거 펀딩 시각 사이를 비결제 시간으로 분류합니다. 정산 시각 이후의 펀딩률을 미리 손익에 적용하지 않지만 당시 거래소의 일정 공지 이력까지 재현한 것은 아닙니다.',
   '최근 Hyperliquid 비교도 마지막 보유분을 정리하므로 기존 고정 재현 화면의 미실현 평가액과 다를 수 있습니다. 그 화면의 과거 거래 기록은 변경하지 않습니다.',
   '연도별 계좌는 독립적이며 수익률을 합산하지 않습니다. Binance 장기 자료와 Hyperliquid 최근 자료를 연결한 하나의 수익곡선으로 표현하지 않습니다.',
   '이미 확인한 손실 구간과 과거 연구 연도를 재사용했습니다. 이번 비교는 새로운 미래 검증이 아니며, 개선된 과거 결과만으로 진행 계좌를 교체하지 않습니다.',
   '최대 낙폭은 15분봉 마감 기준, 청산은 격리 증거금 근사치입니다. 현재 선택한 3종목의 선택·생존편향과 원자료 공백에 따른 한계가 남습니다.'
  ],references:[{title:'Slow Momentum with Fast Reversion (motivation; not an exact reproduction)',url:'https://arxiv.org/abs/2105.13727'},{title:'Bayesian Online Changepoint Detection — Adams & MacKay',url:'https://arxiv.org/abs/0710.3742'}]};
 for(let year=2021;year<=new Date(end).getUTCFullYear();year++){
  const start=Date.UTC(year,0,1),finish=Math.min(end,Date.UTC(year+1,0,1)-1);
  report.periods.push(compare(market,{id:String(year),label:year===new Date(end).getUTCFullYear()?year+'년 1–8월':year+'년',year,start,end:finish,trainingStart:Date.UTC(year-1,0,1),trainingEnd:start-30*C.DAY}));
 }
 const recent=JSON.parse(fs.readFileSync(path.join(ROOT,'simulation/market.json'))),frozen=JSON.parse(fs.readFileSync(path.join(ROOT,'simulation/momentum/replay.json'))).account;
 const first=Math.max(...Object.values(recent.crypto).map(v=>v.frames['15m'][0].t));
 report.recent=compare(recent,{id:'recent',label:'최근 Hyperliquid 구간',start:frozen.startedAt-899999,end:frozen.marketAsOf,trainingStart:first,trainingEnd:first+14*C.DAY});
 const ps=report.periods;
 report.summary={periods:ps.length,higherReturn:ps.filter(p=>p.deltaReturn>0).length,lowerDrawdown:ps.filter(p=>p.deltaDrawdown<0).length,
  bothImproved:ps.filter(p=>p.deltaReturn>0&&p.deltaDrawdown<0).length,
  higherStressReturn:ps.filter(p=>p.results[1].stress.return>p.results[0].stress.return).length,
  baselineWorstDrawdown:Math.max(...ps.map(p=>p.results[0].maxDrawdown)),cpdWorstDrawdown:Math.max(...ps.map(p=>p.results[1].maxDrawdown)),
  recentReturnImproved:report.recent.deltaReturn>0,recentDrawdownImproved:report.recent.deltaDrawdown<0};
 report.conclusion='6개 연도 구간 중 수익 개선 '+report.summary.higherReturn+'개 · 낙폭 개선 '+report.summary.lowerDrawdown+'개. 진행 계좌 교체 보류.';
 // Match the previously published baseline to catch unintended engine/data drift.
 const old=JSON.parse(fs.readFileSync(path.join(ROOT,'simulation/public-bot-research/latest.json')));
 for(const p of ps){const original=old.periods.find(v=>v.year===p.year)?.results.find(v=>v.method==='momentum14');if(original&&Math.abs(original.equity-p.results[0].equity)>1e-5)throw Error('Baseline drift in '+p.year);}
 report.baselineReproduction='All annual baseline equities match the prior published experiment within $0.00001.';
 report.manifestFile=now+'-manifest.json';fs.writeFileSync(path.join(folder,report.manifestFile),JSON.stringify(manifest));
 const output=JSON.stringify(report);fs.writeFileSync(path.join(folder,now+'-report.json'),output);fs.writeFileSync(path.join(folder,'latest.json'),output);
 console.log('Completed',JSON.stringify(report.summary));
}
if(require.main===module)build();module.exports={compare,sliceMarket};
