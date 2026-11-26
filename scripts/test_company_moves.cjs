const assert = require('node:assert/strict');
const test = require('node:test');
const {recentMoves,sameDateSources,panel} = require('../assets/company-events.js');

test('ranks gains and losses in the price snapshot window and skips gaps', () => {
  const history = [
    ['2026-08-01',20],['2026-08-02',40],['2026-11-02',100],['2026-11-03',95],
    ['2026-11-04',105],['2026-11-05',100],['2026-11-06',120],['2026-11-12',30],
    ['2026-11-13',32],['2026-11-16',35],['2026-11-20',35],['2026-11-23',90]
  ].map(([date,close])=>({date,close}));
  const moves = recentMoves(history.reverse(),'2026-11-20');
  assert.deepEqual(moves.up.map(m=>m.date),['2026-11-06','2026-11-04','2026-11-16']);
  assert.deepEqual(moves.down.map(m=>m.date),['2026-11-03','2026-11-05']);
  assert.equal(moves.earliest,'2026-11-02');
  assert.deepEqual(recentMoves(history,'bad').up,[]);
});

test('matches US Eastern day, de-duplicates sources, and scopes checked reporting', () => {
  const move={date:'2026-11-20'};
  const now=Date.parse('2026-11-26T12:00:00Z');
  const source={name:'News',url:'https://sample.org'};
  const filing={title:'Filing',date:'2026-11-23',dateKind:'filed',acceptanceAt:'2026-11-21T02:00:00Z',source};
  const news=[
    {title:'Wrong day',publishedAt:'2026-11-20T04:00:00Z',source:{url:'https://other.org'}},
    {title:'Already listed',publishedAt:'2026-11-21T03:00:00Z',source}
  ];
  assert.deepEqual(sameDateSources(move,[filing],news,now,'MSFT').map(e=>e.title),['Filing']);
  assert.equal(sameDateSources(move,[filing],news,now,'NVDA')[0].kind,'검토한 보도');
});

test('uses actual history in the normal company section and preserves its empty state', () => {
  const now=Date.parse('2026-11-26T12:00:00Z');
  const price={asOf:'2026-11-20',history:[{date:'2026-11-19',close:145.98},{date:'2026-11-20',close:125.53}]};
  const html=panel('NVDA',null,now,null,price);
  assert.match(html, /최근 90일 큰 주가 변동/);
  assert.match(html, /-14\.01%/);
  assert.match(html, /reuters\.com/);
  assert.doesNotMatch(panel('NVDA',null,now,null,{...price,history:[]}),/ce-move-grid/);
});
