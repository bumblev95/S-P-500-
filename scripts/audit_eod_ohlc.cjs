// Audit the actual published bars using the production indicator and panel.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const T = require('../assets/technical-guide.js');
const A = require('../assets/stock-assessment.js');
const root = path.resolve(__dirname, '..');
const read = file => JSON.parse(fs.readFileSync(path.join(root, file), 'utf8'));
const data = read('forecasts/latest.json'), market = read('market/latest.json');
const learned = read('ml/latest.json');
const now = Math.max(Date.parse(data.generatedAt), Date.parse(market.generatedAt));
const hl = q => Number.isFinite(q?.high) && Number.isFinite(q?.low) &&
  q.low > 0 && q.low <= q.close && q.close <= q.high;
const ohlc = q => hl(q) && Number.isFinite(q.open) && q.low <= q.open && q.open <= q.high;
const records = [];
for (const e of Object.values(data.stocks)) {
  const rows = T.history(e), prior55 = rows.slice(0, -1).slice(-55), recent21 = rows.slice(-21);
  const a = A.evaluate(e, market, learned, 126, now), p = a.plan;
  const highBasis = p.levelBasis === '일별 고가·저가', rangeBasis = p.range.basis === 'atr20';
  assert.equal(highBasis, prior55.length === 55 && prior55.every(hl), e.symbol + ' high basis');
  assert.equal(rangeBasis, recent21.length === 21 && recent21.every(hl), e.symbol + ' range basis');
  if (highBasis) assert.equal(p.breakoutLevel, Math.max(...prior55.map(q => q.high)));
  if (rangeBasis) {
    const values = recent21.slice(1).map((q, i) => Math.max(q.high-q.low,
      Math.abs(q.high-recent21[i].close), Math.abs(q.low-recent21[i].close)));
    assert(Math.abs(p.range.value - values.reduce((x,y)=>x+y,0)/20) < 1e-10);
  }
  const panel = A.panel(a);
  assert(panel.includes(highBasis ? '55일 고점 돌파' : '55일 종가 돌파'), e.symbol + ' breakout label');
  assert(panel.includes(rangeBasis ? '20일 평균 실제 변동폭' : '종가 수익률의 일변동폭'), e.symbol + ' range label');
  const closeOnly = {...e, history:rows.map(({date,close,volume})=>({date,close,volume}))};
  for (const horizon of [126,252]) {
    assert.equal(A.evaluate(e,market,learned,horizon,now).score,
      A.evaluate(closeOnly,market,learned,horizon,now).score, e.symbol + ' unchanged trend score');
  }
  records.push({symbol:e.symbol,asOf:e.asOf,historyBars:rows.length,
    validOHLCBars:rows.filter(ohlc).length,validHighLowBars:rows.filter(hl).length,
    latestOHLCComplete:ohlc(rows.at(-1)),allPublishedOHLCComplete:rows.length>0&&rows.every(ohlc),
    prior55ValidHighLowBars:prior55.filter(hl).length,recent21ValidHighLowBars:recent21.filter(hl).length,
    breakoutBasis:highBasis?'actual-high':'close-only',rangeBasis:p.range.basis,
    fallback:!highBasis||!rangeBasis,score:a.score,decision:a.decision});
}
const count = key => records.filter(key).length;
const total = records.length, rate = n => ({count:n,total,percent:Number((100*n/total).toFixed(4))});
const summary = {generatedAt:new Date().toISOString(),forecastGeneratedAt:data.generatedAt,
  priceBasis:'Yahoo Close; split-adjusted, dividends excluded',indicatorPolicy:T.POLICY.version,
  totalSymbols:total,asOfDates:[...new Set(records.map(r=>r.asOf))].sort(),
  latestOHLCComplete:rate(count(r=>r.latestOHLCComplete)),
  allPublishedOHLCComplete:rate(count(r=>r.allPublishedOHLCComplete)),
  actual55BarHigh:rate(count(r=>r.breakoutBasis==='actual-high')),
  trueRange20:rate(count(r=>r.rangeBasis==='atr20')),
  closeOnlyBreakoutFallback:rate(count(r=>r.breakoutBasis==='close-only')),
  closeVolatilityFallback:rate(count(r=>r.rangeBasis==='close-volatility')),
  anyCloseOnlyFallback:rate(count(r=>r.fallback)),
  publishedBars:records.reduce((n,r)=>n+r.historyBars,0),
  validOHLCBars:records.reduce((n,r)=>n+r.validOHLCBars,0),
  validHighLowBars:records.reduce((n,r)=>n+r.validHighLowBars,0),
  scoreUnchangedWithOHLC:true,panelBasisVerified:true,
  fallbackSymbols:records.filter(r=>r.fallback).map(r=>r.symbol)};
const out = path.join(root,'research/eod-ohlc-coverage');
fs.writeFileSync(out+'.json',JSON.stringify(summary,null,2)+'\n');
const keys = Object.keys(records[0]);
fs.writeFileSync(out+'.csv',keys.join(',')+'\n'+records.map(r=>keys.map(k=>r[k]).join(',')).join('\n')+'\n');
console.log(JSON.stringify({...summary,fallbackSymbols:summary.fallbackSymbols.slice(0,20)},null,2));
