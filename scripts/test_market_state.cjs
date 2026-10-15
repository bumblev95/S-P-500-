const assert = require('node:assert/strict');
const {marketState} = require('../assets/technical-guide.js');
const incident = require('./fixtures/market-freshness-2026-10-13.json');
const day = 86400000, now = Date.parse(incident.generatedAt);
const required = {NFCI:16, STLFSI4:16, DRTSCILM:150, FUNDING:5};
const base = {
  generatedAt: new Date(now).toISOString(), credit:{status:'stable'},
  indicators:Object.keys(required).map(id => ({id, status:'ready', asOf:'2026-10-13'}))
};
const clone = () => structuredClone(base);

// Replay run 38427020378: credit-family aggregation is not entry permission.
assert.equal(incident.credit.status, 'stable');
assert.equal(incident.indicators.find(q => q.id === 'FUNDING').status, 'ready');
assert.equal(marketState(incident, now), 'unknown');
for (const status of ['stable', 'watch', 'risk', 'unknown']) {
  assert.equal(marketState({...base, credit:{status}}, now), status);
}

for (const [id, days] of Object.entries(required)) {
  // Equality is allowed; one millisecond beyond the existing limit is not.
  const boundary = Date.parse('2026-10-13') + days * day;
  for (const offset of [-1, 0, 1]) {
    const m = clone(), t = boundary + offset;
    m.generatedAt = new Date(t).toISOString();
    for (const q of m.indicators) q.asOf = new Date(t).toISOString().slice(0, 10);
    m.indicators.find(q => q.id === id).asOf = '2026-10-13';
    assert.equal(marketState(m, t), offset <= 0 ? 'stable' : 'unknown', `${id} boundary ${offset}`);
    for (const q of m.indicators) q.maxAgeDays = required[q.id];
    assert.equal(marketState(m, t), offset <= 0 ? 'stable' : 'unknown', `${id} explicit limit ${offset}`);
  }
  for (const status of ['missing', 'stale', 'unavailable']) {
    const m = clone(); m.indicators.find(q => q.id === id).status = status;
    assert.equal(marketState(m, now), 'unknown', `${id} ${status}`);
  }
  const missing = clone(); missing.indicators = missing.indicators.filter(q => q.id !== id);
  assert.equal(marketState(missing, now), 'unknown', `${id} absent`);
  for (const asOf of [null, 'invalid', '2026-10-14']) {
    const m = clone(); m.indicators.find(q => q.id === id).asOf = asOf;
    assert.equal(marketState(m, now), 'unknown', `${id} invalid/future observation`);
  }
}

const expired = clone(); expired.indicators.find(q => q.id === 'FUNDING').asOf = '2026-10-08';
assert.equal(marketState({...expired, credit:{status:'watch'}}, now), 'unknown');
assert.equal(marketState({...expired, credit:{status:'risk'}}, now), 'risk', 'Fresh risk warnings survive incomplete inputs');
assert.equal(marketState({...expired, credit:{status:'risk'}}, now + 3*day + 1), 'unknown', 'Expired snapshots cannot renew risk warnings');
const cached = clone(); cached.indicators.forEach(q => Object.assign(q, {fromCache:true, fetchStatus:'unavailable'}));
assert.equal(marketState(cached, now), 'stable', 'A fetch failure alone does not invalidate a still-fresh observation');
cached.indicators.find(q => q.id === 'FUNDING').asOf = '2026-10-08';
assert.equal(marketState(cached, now), 'unknown', 'New fetch timestamps cannot freshen old observations');
const shortLimit = clone(); shortLimit.indicators[0].maxAgeDays = 1; shortLimit.indicators[0].asOf = '2026-10-12';
assert.equal(marketState(shortLimit, now), 'unknown', 'Honor the supplied observation limit');
for (const offset of [-1, 0, 1]) {
  const t = now + 3*day + offset, m = clone();
  m.indicators.forEach(q => q.asOf = new Date(t).toISOString().slice(0, 10));
  assert.equal(marketState(m, t), offset <= 0 ? 'stable' : 'unknown', `snapshot boundary ${offset}`);
}
for (const generatedAt of [null, 'invalid', new Date(now+1).toISOString()]) {
  assert.equal(marketState({...base, generatedAt}, now), 'unknown');
}
assert.equal(marketState(null, now), 'unknown');
assert.equal(marketState({...base, credit:undefined}, now), 'unknown');
console.log('Market state: incident replay, fresh/stale/missing inputs, UTC boundaries, cache and risk preservation passed');
