const assert=require('node:assert/strict'),fs=require('node:fs');
const A=require('../assets/stock-assessment.js'),T=require('../assets/technical-guide.js'),D=require('../assets/decision-support.js');
const now=Date.parse('2026-10-02T23:12:22Z'),day='2026-10-02';
const history=Array.from({length:80},(_,i)=>({date:new Date(Date.parse(day)-(79-i)*86400000).toISOString().slice(0,10),close:i===79?100:[100,110,100,90,100][i%5]}));
const e={symbol:'TEST',status:'ready',fresh:true,asOf:day,price:100,history,inputs:{ma20:100,ma50:95,ma200:90,return1m:.04,return3m:.12,volatility4m:.2}};
const market={generatedAt:day+'T22:00:00Z',credit:{status:'stable'},indicators:['NFCI','STLFSI4','DRTSCILM','FUNDING'].map(id=>({id,status:'ready',asOf:day,maxAgeDays:5,value:0}))};
const forecast={horizon:126,anchor:100,base:110,bear:90,bull:120,learned:true,direction:'up',return:.1,logReturn:Math.log(1.1),lowLogReturn:Math.log(.9),highLogReturn:Math.log(1.2)};
const ml={status:'trained',generatedAt:day+'T22:00:00Z',validation:{126:{passed:true},252:{passed:true}},stocks:{TEST:{asOf:day,price:100,predictions:{126:{status:'eligible',forecast,validation:{dates:20}}}}}};
const pass=A.evaluate(e,market,ml,126,now);
assert(pass.score>=60,'Control must have a strong observed trend');
assert.equal(pass.score,T.plan(e,null,market,now).ts);
assert.equal(pass.decision,'진입 검토','Control must satisfy the existing entry checks');
const withheld=structuredClone(ml);withheld.stocks.TEST.predictions[126].status='withheld';
const wait=A.evaluate(e,market,withheld,126,now);
assert.equal(wait.score,pass.score);assert.equal(wait.decision,'진입 검토');assert.equal(wait.plan.code,'buy');
assert(!wait.plan.blocks.includes('AI 예측 검증 조건 미충족'));
assert.deepEqual(wait.plan,pass.plan,'AI failure must not change the technical entry plan');
assert.equal(wait.ai.eligible,false);assert.equal(wait.ai.forecast,null,'Withheld research stays withheld');
assert(A.panel(wait).includes('검증 미통과'));
assert(A.panel(wait).includes('단기 추세 점수'));
const failedGlobal=structuredClone(ml);failedGlobal.validation={126:{passed:false},252:{passed:true}};
const globalWait=A.evaluate(e,market,failedGlobal,126,now);
assert.equal(globalWait.score,pass.score);assert.equal(globalWait.decision,'진입 검토');assert.equal(globalWait.modelStatus,'AI 성능 기준 미통과');
assert.equal(globalWait.ai.eligible,false,'An eligible record must not override an explicit failed overall performance gate');
assert.deepEqual(globalWait.plan,pass.plan,'Failed overall AI performance stays separate from technical entry');
assert.equal(globalWait.ai.forecast,null);
const missingGrade=structuredClone(ml);delete missingGrade.validation;
const ungraded=A.evaluate(e,market,missingGrade,126,now);assert.equal(ungraded.score,pass.score);assert.equal(ungraded.decision,'진입 검토');assert.equal(ungraded.modelStatus,'AI 성능 검증 자료 확인 필요');
assert.deepEqual(ungraded.plan,pass.plan);assert.equal(ungraded.ai.eligible,false);assert.equal(ungraded.ai.forecast,null);
// Technical conditions and withheld AI research are separate first-screen states.
const before=JSON.stringify(wait),checks=A.entryChecks(wait),html=A.panel(wait);
assert.equal(checks.find(c=>c.key==='trend').tone,'good');
assert(!checks.some(c=>c.key==='ai'));
assert.equal(A.aiReference(wait).state,'검증 미통과');
assert(html.includes('data-decision-basis="technical-rules"'));
assert(html.includes('data-ai-reference="unavailable"'));
assert(html.indexOf('sa-reason')<html.indexOf('sa-entry-layout'));
assert(html.includes('class="sa-trend-details"><summary>'));
assert(!html.includes('class="sa-trend-details" open'));
assert.equal(JSON.stringify(wait),before,'Presentation must not mutate an assessment');
const risk=A.evaluate(e,{...market,credit:{status:'risk'}},ml,126,now);
assert.equal(risk.score,pass.score);assert.equal(risk.decision,'진입 보류');assert.match(risk.reason,/시장/);
const unknown=A.evaluate(e,null,ml,126,now);
assert.equal(unknown.score,pass.score);assert.notEqual(unknown.decision,'진입 검토');
const bearish=structuredClone(ml);bearish.stocks.TEST.predictions[252]={status:'eligible',forecast:{...forecast,horizon:252,base:90,bear:80,bull:110,direction:'down',return:-.1,logReturn:Math.log(.9),lowLogReturn:Math.log(.8),highLogReturn:Math.log(1.1)}};
const long=A.evaluate(e,market,bearish,252,now);
assert.equal(long.score,pass.score);assert.equal(long.trend,pass.trend);assert.equal(long.color,pass.color);assert.equal(long.decision,'진입 검토');
assert.deepEqual(long.plan,pass.plan,'Long-horizon AI direction is separate research evidence');
assert.equal(A.aiReference(long).state,'하락 전망');
for(const input of [null,{...ml,generatedAt:'2026-09-01T00:00:00Z'},
  {...ml,stocks:{TEST:{...ml.stocks.TEST,price:90}}},
  {...ml,stocks:{TEST:{...ml.stocks.TEST,predictions:{126:{status:'eligible',forecast:{...forecast,base:Infinity}}}}}}]){
  const a=A.evaluate(e,market,input,126,now);
  assert.deepEqual(a.plan,pass.plan,'Absent, stale, misaligned and invalid AI must not veto price conditions');
  assert.equal(a.ai.eligible,false,'Invalid AI must never become eligible research');
}
const extreme=structuredClone(withheld);extreme.stocks.TEST.predictions[126].forecast={...forecast,base:10000,bull:20000,logReturn:Math.log(100),highLogReturn:Math.log(200)};
assert.equal(A.evaluate({...e,longTermScenario:{value:99999},predictions:{126:{return:9999}}},market,extreme,126,now).score,pass.score);
for(const bad of [null,{...e,symbol:''},{...e,fresh:false},{...e,asOf:'2027-01-01'},{...e,history:history.slice(-30)},{...e,price:90},{...e,status:'insufficient'}]){
  const a=A.evaluate(bad,market,ml,126,now);assert.equal(a.score,null);assert.equal(a.decision,'판단 보류');
  assert(!A.rank({BAD:a}).length);assert(!/NaN|undefined|Infinity/.test(A.panel(a)));assert(A.panel(a).includes('산출 보류'));
  assert(A.entryChecks(a).filter(c=>['trend','price','balance','heat'].includes(c.key)).every(c=>c.tone==='muted'));
}
const ranked=A.rank({Z:{...wait,symbol:'Z'},A:{...risk,symbol:'A'},missing:{...pass,symbol:'MISSING',score:null}});
assert.deepEqual(ranked.map(a=>a.symbol),['A','Z'],'Rank only by the displayed score, with a stable symbol tie break');
assert.equal(A.normalize('BRK.B'),'BRK-B');
assert.equal(A.entry({stocks:{'BRK.B':e}},'BRK-B'),e);assert.equal(A.entry({stocks:{'BRK-B':e}},'BRK.B'),e);
const mismatched=A.all({stocks:{WRONG:e,EMPTY:null}},market,ml,126,now);
assert.equal(mismatched.WRONG.score,null);assert.equal(mismatched.WRONG.symbol,'WRONG');assert.equal(mismatched.EMPTY.score,null);
const ordered=[{symbol:'MISSING',score:null},{symbol:'Z',score:0},{symbol:'A',score:0},{symbol:'BRK.B',score:50},{symbol:'BF.B',score:50}].sort(A.compare);
assert.deepEqual(ordered.map(a=>a.symbol),['BF.B','BRK.B','A','Z','MISSING'],'Zero is a valid score; missing is always last; ties use canonical ticker order');
assert.deepEqual([...ordered].sort((a,b)=>A.compare(a,b,1)).map(a=>a.symbol),['A','Z','BF.B','BRK.B','MISSING']);
assert(!D.confidence({dates:25,n:1000,mae:.2,noChangeMae:.1}).includes('검증 수준'));
assert(D.confidence({dates:25,n:1000,mae:.2,noChangeMae:.1}).includes('성능 기준 통과와 별개'));
assert(!D.confidence({dates:25,n:1000,mae:.2,noChangeMae:.1}).includes('충분'));

// Explanations keep issuer risks visible even when shared data/model gates fail.
const stressed={...e,symbol:'<TEST>',inputs:{...e.inputs,ma50:105,ma200:110,
  return1m:-.07,return3m:-.12,volatility4m:.75}};
const stressedA=A.evaluate(stressed,null,withheld,126,now),stressedBefore=JSON.stringify(stressedA);
const stressedSignals=A.signals(stressed,stressedA,null,now);
assert(stressedSignals.negative.length>=5,'Distinct issuer conditions must not be clipped by shared warnings');
assert(stressedSignals.negative.some(x=>x.id==='volatility'&&x.detail.includes('75.0%')));
assert(stressedSignals.negative.some(x=>x.id==='return1m'&&x.title.includes('-7.0%')));
assert(!stressedSignals.negative.some(x=>/시장 상태|AI 예측 활용/.test(x.title)));
assert(stressedSignals.limitations.some(x=>x.id==='market-data'));
assert(stressedSignals.limitations.some(x=>x.id==='ai-validation'));
assert(stressedSignals.limitations.some(x=>x.id==='weak-trend'));
assert(!stressedSignals.negative.some(x=>x.id==='weak-trend'||x.id==='model-down'));
assert.equal(JSON.stringify(stressedA),stressedBefore,'Display explanations must not mutate the assessment');
const explanationHtml=A.signalPanels(stressed,stressedA,null,now);
assert(explanationHtml.includes('꼭 확인할 위험 · &lt;TEST&gt;'));
assert(!explanationHtml.includes('<TEST>'));
assert(!/NaN|undefined|Infinity/.test(explanationHtml));
const absent=A.evaluate({...e,history:[]},null,withheld,126,now);
assert(!A.signals({...e,history:[]},absent,null,now).available);
assert.equal(A.signals({...e,history:[]},absent,null,now).negative.length,0);
assert(A.signalPanels({...e,history:[]},absent,null,now).includes('위험 판단에 필요한 가격 자료가 부족'));
const noTarget={...pass,plan:{...pass.plan,target1:null,rr:null}};
assert(A.signals(e,noTarget,market,now).negative.some(x=>x.id==='resistance-missing'));
const modelMetrics=structuredClone(wait);modelMetrics.ai.record.validation={mae:.2,noChangeMae:.15,directionAccuracy:.4,alwaysUpAccuracy:.6,dates:12};
assert(A.signals(e,modelMetrics,market,now).limitations.some(x=>x.id==='ai-validation'&&x.detail.includes('20.0%')&&x.detail.includes('12개 시점')));

function assertVisibleBlockers(a,s){
  const displayed=[...s.negative,...s.limitations].flatMap(x=>x.blocks||[]);
  assert.deepEqual(displayed.slice().sort(),[...new Set(a.plan.blocks)].sort(),
    'Every entry blocker must have exactly one visible risk or status explanation');
}
// Different technical states with the same unavailable market/model gates.
// Compare risk IDs/titles, so different ticker labels cannot satisfy the test.
const hot={...e,symbol:'HOT',history:history.map((q,i)=>({...q,close:60+40*i/(history.length-1)})),
  inputs:{ma20:97,ma50:90,ma200:80,return1m:.25,return3m:.35,volatility4m:.75}};
const hotA=A.evaluate(hot,null,null,126,now),hotSignals=A.signals(hot,hotA,null,now);
const riskIds=s=>s.negative.map(x=>x.id);
assert.notDeepEqual(riskIds(stressedSignals),riskIds(hotSignals));
for(const id of ['ma50','ma-order','return1m','return3m','volatility'])assert(riskIds(stressedSignals).includes(id));
assert(riskIds(hotSignals).includes('overheated'));
assert(!riskIds(stressedSignals).includes('overheated'));
assert(!riskIds(hotSignals).includes('ma50'));
for(const [entry,a,s] of [[stressed,stressedA,stressedSignals],[hot,hotA,hotSignals]]){
  assertVisibleBlockers(a,s);
  assert(s.limitations.some(x=>x.id==='ai-validation'));
  assert(s.limitations.some(x=>x.id==='market-data'));
  const html=A.signalPanels(entry,a,null,now);
  for(const id of riskIds(s))assert(html.includes('data-signal="'+id+'"'));
  assert(html.includes('진입 조건·공통 상태'));
}
const downSignals=A.signals(e,long,market,now);
assert(downSignals.limitations.some(x=>x.id==='model-down'&&x.title.includes('1년')));
assert(!riskIds(downSignals).includes('model-down'));
assertVisibleBlockers(long,downSignals);
// New blockers and gates whose price inputs cannot be displayed stay visible.
const extra='추가 진입 조건 <확인 필요>';
const extraA={...wait,plan:{...wait.plan,blocks:[...wait.plan.blocks,extra,extra]}};
assertVisibleBlockers(extraA,A.signals(e,extraA,market,now));
const extraHtml=A.signalPanels(e,extraA,market,now);
assert.equal(extraHtml.split('추가 진입 조건 &lt;확인 필요&gt;').length-1,1);
for(const entry of [{...e,fresh:false},{...e,history:history.slice(-30)},
  {...e,inputs:{...e.inputs,volatility4m:null}}]){
  const a=A.evaluate(entry,null,null,126,now);
  assertVisibleBlockers(a,A.signals(entry,a,null,now));
}

// Real snapshot checks: both horizons share the exact observed-price score.
const data=JSON.parse(fs.readFileSync('forecasts/latest.json')),actualMarket=JSON.parse(fs.readFileSync('market/latest.json')),actualML=JSON.parse(fs.readFileSync('ml/latest.json'));
const actualNow=Date.parse(actualMarket.generatedAt),six=A.all(data,actualMarket,actualML,126,actualNow),year=A.all(data,actualMarket,actualML,252,actualNow);
const amdSignals=A.signals(data.stocks.AMD,six.AMD,actualMarket,actualNow);
const nvdaSignals=A.signals(data.stocks.NVDA,six.NVDA,actualMarket,actualNow);
const jnjSignals=A.signals(data.stocks.JNJ,six.JNJ,actualMarket,actualNow);
if(six.AMD.score!==null&&six.JNJ.score!==null&&
  (data.stocks.AMD.inputs.return1m<0)!==(data.stocks.JNJ.inputs.return1m<0))
  assert.notDeepEqual(riskIds(amdSignals),riskIds(jnjSignals),'Opposite real monthly returns must produce distinct technical risks');
if(six.AMD.score!==null&&!six.AMD.plan.target1)assert(amdSignals.negative.some(x=>x.id==='resistance-missing'));
if(Number.isFinite(six.NVDA.plan.rr)&&six.NVDA.plan.rr<1.5)assert(nvdaSignals.negative.some(x=>x.id==='reward-risk'&&x.title.includes(six.NVDA.plan.rr.toFixed(2))));
let checked=0,scored=0;
for(const [symbol,a] of Object.entries(six)){
  assert.equal(a.score,year[symbol].score,symbol);assert.equal(a.trend,year[symbol].trend,symbol);
  if(a.score!==null){scored++;assert.equal(a.score,T.plan(data.stocks[a.symbol],null,actualMarket,actualNow).ts);}
  assert.deepEqual(a.plan,A.evaluate(data.stocks[a.symbol],actualMarket,null,126,actualNow).plan,
    'Technical entry plans do not depend on AI availability');
  assert.deepEqual(a.plan,year[symbol].plan,'Changing the AI horizon cannot change technical entry conditions');
  if(a.plan.code==='buy')assert(!a.plan.blocks.length&&a.score>=60&&a.plan.rr>=(a.plan.market==='watch'?2:1.5));
  checked++;
  for(const assessment of [a,year[symbol]])assertVisibleBlockers(assessment,
    A.signals(data.stocks[assessment.symbol],assessment,actualMarket,actualNow));
}
assert(checked>=400&&scored>0);assert(A.rank(six).every((a,i,arr)=>!i||a.score<=arr[i-1].score));

(async()=>{
  const result=await A.load(async url=>{if(url.startsWith('forecasts'))throw Error('offline');return {ok:true,json:async()=>url.startsWith('market')?market:ml};},null);
  assert.equal(result.data,null);assert.equal(result.errors.length,1);assert.deepEqual(A.all(result.data,result.market,result.learned),{});
  console.log(`Stock assessment: independent technical entry and AI research, market/freshness gates, horizon-independent scores, withheld research, deterministic ranking and ${checked} real records (${scored} scored) passed.`);
})().catch(e=>{console.error(e);process.exitCode=1});
