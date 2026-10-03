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
assert.equal(wait.score,pass.score);assert.equal(wait.decision,'관망');assert.equal(wait.plan.code,'watch');
assert(wait.plan.blocks.includes('AI 예측 검증 조건 미충족'));
assert(A.panel(wait).includes('AI 성능 기준 미통과'));
assert(A.panel(wait).includes('단기 추세 점수'));
const failedGlobal=structuredClone(ml);failedGlobal.validation={126:{passed:false},252:{passed:true}};
const globalWait=A.evaluate(e,market,failedGlobal,126,now);
assert.equal(globalWait.score,pass.score);assert.equal(globalWait.decision,'관망');assert.equal(globalWait.modelStatus,'AI 성능 기준 미통과');
assert.equal(globalWait.ai.eligible,false,'An eligible record must not override an explicit failed overall performance gate');
const missingGrade=structuredClone(ml);delete missingGrade.validation;
const ungraded=A.evaluate(e,market,missingGrade,126,now);assert.equal(ungraded.score,pass.score);assert.equal(ungraded.decision,'관망');assert.equal(ungraded.modelStatus,'AI 성능 검증 자료 확인 필요');
// The first screen must explain high-trend / withheld-entry combinations.
const before=JSON.stringify(wait),checks=A.entryChecks(wait),html=A.panel(wait);
assert.equal(checks.find(c=>c.key==='trend').tone,'good');
assert.equal(checks.find(c=>c.key==='ai').state,'미통과');
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
assert.equal(long.score,pass.score);assert.equal(long.trend,pass.trend);assert.equal(long.color,pass.color);assert.equal(long.decision,'진입 보류');
assert.equal(A.entryChecks(long).find(c=>c.key==='ai').state,'하락 우세');
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

// Real snapshot checks: both horizons share the exact observed-price score.
const data=JSON.parse(fs.readFileSync('forecasts/latest.json')),actualMarket=JSON.parse(fs.readFileSync('market/latest.json')),actualML=JSON.parse(fs.readFileSync('ml/latest.json'));
const actualNow=Date.parse(actualMarket.generatedAt),six=A.all(data,actualMarket,actualML,126,actualNow),year=A.all(data,actualMarket,actualML,252,actualNow);
let checked=0,scored=0;
for(const [symbol,a] of Object.entries(six)){
  assert.equal(a.score,year[symbol].score,symbol);assert.equal(a.trend,year[symbol].trend,symbol);
  if(a.score!==null){scored++;assert.equal(a.score,T.plan(data.stocks[a.symbol],null,actualMarket,actualNow).ts);}
  if(!a.ai.eligible)assert.notEqual(a.plan.code,'buy');checked++;
}
assert(checked>=400&&scored>0);assert(A.rank(six).every((a,i,arr)=>!i||a.score<=arr[i-1].score));

(async()=>{
  const result=await A.load(async url=>{if(url.startsWith('forecasts'))throw Error('offline');return {ok:true,json:async()=>url.startsWith('market')?market:ml};},null);
  assert.equal(result.data,null);assert.equal(result.errors.length,1);assert.deepEqual(A.all(result.data,result.market,result.learned),{});
  console.log(`Stock assessment: entry control, withheld/risk gates, horizon-independent scores, missing/stale guards, forecast independence, deterministic ranking and ${checked} real records (${scored} scored) passed.`);
})().catch(e=>{console.error(e);process.exitCode=1});
