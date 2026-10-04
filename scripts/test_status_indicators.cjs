const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const V = require('../assets/market-visuals.js');
const A = require('../assets/stock-assessment.js');

// Missing values must never look like a neutral or healthy observation.
for (const html of [V.riskGauge(null), V.riskGauge('unknown'),
  V.entryGauge('unavailable', '판단 보류'), V.directionGauge(null, '갱신 확인'),
  ...[null, undefined, NaN, Infinity, -1, 101].map(x => V.trendGauge(x))]) {
  assert(html.includes('data-state="unknown"'));
  assert(!html.includes('class="vi-pointer"'));
  assert(!html.includes('vi-active'));
  assert(!/NaN|undefined|Infinity/.test(html));
}
for (const state of ['stable', 'watch', 'risk']) {
  const html = V.riskGauge(state);
  assert(html.includes(`data-state="${state}"`));
  assert(html.includes('class="vi-pointer"'));
  assert(html.includes('위기 확률 아님'));
}
for (const code of ['watch', 'pullback', 'confirm']) {
  assert(V.entryGauge(code).includes('data-state="watch"'));
  assert(V.entrySteps(code).includes('aria-current="step"'));
}
assert(V.entryGauge('avoid').includes('진입 보류'));
assert(V.entryGauge('avoid').includes('보유 자산 매도와 별도'));
assert(!V.entrySteps('unavailable').includes('aria-current'));

// Keep the established trend thresholds/colours, including a real zero score.
for (const score of [0, 34, 35, 45, 46, 59, 60, 77, 78, 100]) {
  const html = V.trendGauge(score, A.trend(score));
  assert(html.includes(`${score}/100`));
  assert(html.includes(`vi-value vi-${A.color(score)}`));
  assert(html.includes(A.trend(score)));
  assert(html.includes(`rotate(${(-90 + 1.8 * score).toFixed(2)} 120 108)`));
}
assert(V.badge('<img src=x>', 'unknown').includes('&lt;img src=x&gt;'));
assert(V.table([['値', null]]).includes('자료 없음'));

// Render the actual risk panel through its public loader/mount path with a
// frozen clock. Old data stays visible but cannot get a healthy badge/needle.
const stamp = '2026-09-14T20:00:00Z';
const indicators = [
  {id:'GZ_SPREAD', label:'GZ 신용스프레드', status:'ready', value:0,
    severity:0, asOf:'2026-07-01', maxAgeDays:75, unit:'%p', frequency:'monthly',
    url:'https://www.federalreserve.gov/econres/notes.htm'},
  {id:'NFCI', label:'금융여건', status:'ready', value:0, severity:1,
    asOf:'2026-09-04', maxAgeDays:16, unit:'index', fetchStatus:'unavailable'},
  {id:'IORB', label:'IORB 참고', status:'unavailable', value:3.65,
    severity:null, asOf:'2026-09-11', maxAgeDays:5, unit:'%'},
  {id:'SOFR', label:'SOFR 참고', status:'ready', value:3.62,
    severity:null, asOf:'2026-09-11', maxAgeDays:5, unit:'%'},
  {id:'DGS10', label:'금리 값 없음', status:'ready', value:null,
    severity:2, change:1, asOf:'2026-09-11', maxAgeDays:7, unit:'%'}
];
async function renderRisk(snapshot, clock) {
  class Clock extends Date {
    constructor(...args) { super(...(args.length ? args : [clock])); }
    static now() { return clock; }
  }
  const host = {innerHTML:''};
  const root = {MarketVisuals:V};
  vm.runInNewContext(fs.readFileSync('assets/decision-support.js', 'utf8'), {
    window:root, Date:Clock, URL, document:{getElementById:id => id === 'sharedRisk' ? host : null},
    fetch:async url => ({ok:true, json:async () => url.startsWith('market/') ? snapshot : {}})
  });
  await root.DecisionSupport.load();
  root.DecisionSupport.mountStock({e:{symbol:'TEST'}, plan:{}, h:126, ai:{}});
  return host.innerHTML;
}
(async () => {
  const snapshot = {generatedAt:stamp, indicators};
  const current = await renderRisk(snapshot, Date.parse(stamp));
  assert(current.includes('data-state="watch"'));
  assert(current.includes('0.00 index'));
  assert(current.includes('수집 지연 · 마지막 확보값 사용'));
  assert(current.includes('vi-badge vi-muted">참고'));
  assert(current.includes('vi-badge vi-muted">자료 부족'));
  assert(current.includes('2026-07-01'));
  assert(current.includes('https://www.federalreserve.gov/econres/notes.htm'));
  const old = await renderRisk(snapshot, Date.parse(stamp) + 86400000 * 5);
  assert(old.includes('0.00 %p'));
  assert(old.includes('data-state="unknown"'));
  assert(!old.includes('class="vi-pointer"'));
  assert(old.includes('vi-badge vi-muted">판단 제외'));
  assert(!old.includes('vi-badge vi-good'));
  // Every consumer loads both the renderer and its stylesheet.
  for (const file of ['stocks.html','advanced.html','advanced-legacy.html','crypto.html','futures.html']) {
    const html = fs.readFileSync(file, 'utf8');
    assert(html.includes('assets/status-indicators.css'), file);
    assert(html.indexOf('assets/market-visuals.js') < html.indexOf('assets/decision-support.js'), file);
  }
  console.log('Indicators: unknown/stale guards, exact trend thresholds, entry semantics, cached risk values and page dependencies passed.');
})().catch(e => {console.error(e); process.exitCode = 1;});
