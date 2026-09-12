'use strict';
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),M=require('./public_bot_methods.cjs'),R=require('./research_trend_methods.cjs');
const ROOT=path.resolve(__dirname,'..'),VERSION='public-bot-ideas-common-risk-v1';
function build(){
 const cache=process.env.PAPER_LONG_CACHE||'/tmp/paper-long-cache',marketFile=path.join(cache,'market.json'),manifest=JSON.parse(fs.readFileSync(path.join(cache,'manifest.json')));
 if(manifest.errors.length)throw Error('Incomplete archive input');
 const market=JSON.parse(fs.readFileSync(marketFile)),end=Math.min(...Object.values(manifest.coverage).map(v=>v.end)),folder=path.join(ROOT,'simulation/public-bot-research');
 fs.mkdirSync(folder,{recursive:true});const latest=path.join(folder,'latest.json');
 if(fs.existsSync(latest)){const old=JSON.parse(fs.readFileSync(latest));if(old.version===VERSION&&old.dataEnd===end){console.log('Public bot comparison already preserved');return;}}
 const now=Date.now(),report={version:VERSION,generatedAt:now,dataEnd:end,status:'공개 전략 응용 · 과거 비교 실험',deployed:false,coverage:manifest.coverage,sourceHash:crypto.createHash('sha256').update(fs.readFileSync(marketFile)).digest('hex'),methods:M.METHODS,periods:[],notes:[
  '원본 봇이나 사람의 실제 성적이 아닙니다. 공개된 아이디어를 독립적으로 재구현하고 시간봉·배율·손절·보유 한도를 통일한 응용 실험입니다. 각 전략의 변경 사항과 원문 링크를 함께 공개합니다.',
  '2021년부터 각 연도를 별도 $10,000으로 평가합니다. 2020년 자료는 지표 준비에 사용합니다. 수익률을 합산하거나 연결한 하나의 실적이 아닙니다.',
  '4시간봉 마감으로 판단하고 다음 15분봉 시가로 체결합니다. 공백 후 지표를 다시 준비하며, 200일 돌파는 상장 직후 또는 자료 공백 후 200일간 신호가 없습니다.',
  'BTC 5배·ETH/SOL 3배, 거래당 위험 예산 1%, 전체 위험 3%, 명목 노출 2배 제한. 낙폭 10%·20%에서 규모 축소하고 UTC 하루 3% 손실 시 당일 신규 진입을 중단합니다.',
  '공통 초기·추적 손절 4시간 ATR 2.5배, 최대 보유 30일, 고정 익절 없음. Hummingbot 응용의 평균선 복귀와 각 추세 이탈은 다음 시가에 종료합니다. 추적 손절은 다음 봉부터 적용합니다.',
  '수수료 0.045%·슬리피지 0.02% 편도, 실제 기록된 펀딩. 비용 2배는 수수료·슬리피지만 두 배로 재실행합니다. 누락 펀딩은 시간당 0.01% 지급 가정으로 표시합니다.',
  '수량 계산에 8시간 펀딩 여유를 포함하지만 이후 펀딩·갭 손실은 예산을 넘을 수 있습니다. 평가 기간 말에는 모든 포지션을 비용을 내고 종료합니다.',
  '최대 낙폭은 15분봉 마감 기준이며 실제 장중 낙폭은 더 클 수 있습니다. 유지증거금과 청산 가격은 근사치이고 과거 거래소의 정확한 마크가격 청산 엔진을 복제하지 않습니다.',
  '현재 선택한 BTC·ETH·SOL의 선택·생존편향이 있습니다. 이미 연구에 사용했던 과거 자료를 재사용한 비교이므로 독립적인 미래 검증이나 수익 보장이 아닙니다.',
  '원본의 고수익 홍보와 우리 계산을 구분합니다. 여러 후보 중 최고 결과를 고르는 과정 자체에 선택 편향이 있으며, 결과가 좋아도 진행 계좌를 자동 교체하지 않습니다.',
  '전체 기간 양수, 두 배 비용에서도 양수, 각 연도 최대 낙폭 10% 이하, 총 종료 거래 100건 이상을 탐색 기준으로 확인합니다. 기준 통과도 실제 운용 검증을 대신하지 않습니다.'
 ],reviewedNotRun:[{name:'NostalgiaForInfinity',url:'https://github.com/iterativv/NostalgiaForInfinity',reason:'저장소와 설정 요건을 검토했으나 원본의 다중 조건·종목 선택·실행 구성을 재현하지 않았습니다. 이 봇의 성적으로 표시하지 않습니다.'}]};
 const maps=Object.fromEntries(M.METHODS.map(m=>[m.id,Object.fromEntries(Object.entries(market.crypto).map(([s,v])=>[s,M.signals(v.frames['15m'],m.id)]))]));
 for(let year=2021;year<=new Date(end).getUTCFullYear();year++){
  const start=Date.UTC(year,0,1),finish=Math.min(end,Date.UTC(year+1,0,1)-1),period={year,start,end:finish,benchmark:R.benchmark(market,start,finish),results:[]};
  for(const m of M.METHODS){
   const a=R.evaluate(market,maps[m.id],start,finish),stress=R.evaluate(market,maps[m.id],start,finish,true);
   if(Math.abs(a.equity-10000-a.closed.reduce((s,t)=>s+t.net,0))>1e-5)throw Error('Account reconciliation failed');
   period.results.push({method:m.id,...a,stress:{equity:stress.equity,return:stress.return,maxDrawdown:stress.maxDrawdown,trades:stress.trades}});
   console.log(JSON.stringify({year,method:m.id,return:a.return,maxDrawdown:a.maxDrawdown,trades:a.trades,stressReturn:stress.return,estimatedFundingHours:a.estimatedFundingHours}));
  }
  report.periods.push(period);
 }
 report.screening=M.METHODS.map(m=>{const rows=report.periods.map(p=>p.results.find(r=>r.method===m.id));return {method:m.id,positivePeriods:rows.filter(r=>r.return>0).length,totalPeriods:rows.length,stressPositivePeriods:rows.filter(r=>r.stress.return>0).length,worstDrawdown:Math.max(...rows.map(r=>r.maxDrawdown)),totalTrades:rows.reduce((s,r)=>s+r.trades,0),passesExploratoryScreen:rows.every(r=>r.return>0&&r.stress.return>0&&r.maxDrawdown<=.1)&&rows.reduce((s,r)=>s+r.trades,0)>=100};});
 report.manifestFile=now+'-manifest.json';fs.writeFileSync(path.join(folder,report.manifestFile),JSON.stringify(manifest));
 const text=JSON.stringify(report);fs.writeFileSync(path.join(folder,now+'-report.json'),text);fs.writeFileSync(latest,text);
 console.log('Public bot comparison complete',JSON.stringify(report.screening));
}
if(require.main===module)build();module.exports={build};
