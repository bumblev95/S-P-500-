(() => {
  'use strict';

  const byId = id => document.getElementById(id);
  const table = byId('cr-table');
  const side = byId('cr-side');
  const minimum = byId('cr-min');
  const sort = byId('cr-sort');
  const outcome = byId('cr-outcome');
  const data = new Map();
  const marketScope = 'market';
  const sources = {
    nvda: {file:'data/congress/NVDA.json', name:'Pathos Investments', url:'https://pathosinvestments.com/congress/nvda'},
    market: {file:'data/congress/market.json', name:'SteadyShares', url:'https://steadyshares.com/politicians/leaderboard'}
  };
  const memberNames = {
    'Robert P. Bresnahan, Jr.':'롭 브레스너핸', 'Cleo Fields':'클리오 필즈',
    'Josh Gottheimer':'조시 고트하이머', 'Lisa C. McClain':'리사 매클레인',
    'Gilbert Ray Cisneros, Jr.':'길 시스네로스', 'Marjorie Taylor Greene':'마저리 테일러 그린',
    'Daniel Meuser':'댄 뮤저', 'Sheldon Whitehouse':'셸던 화이트하우스',
    'Jared Moskowitz':'재러드 모스코위츠', 'Val T. Hoyle':'밸 호일', 'Nancy Pelosi':'낸시 펠로시',
    'John Boozman':'존 부즈먼', 'Jefferson Shreve':'제퍼슨 슈리브'
  };
  let scope;
  let requestNumber = 0;
  const minimumByScope = {nvda:10, market:20};
  const number = new Intl.NumberFormat('ko-KR');
  const pct = value => (value * 100).toFixed(1) + '%';
  const points = value => (value > 0 ? '+' : '') + value.toFixed(1) + '%p';

  function link(label, url) {
    const anchor = document.createElement('a');
    anchor.textContent = label;
    anchor.href = url;
    return anchor;
  }

  function profileChart(member) {
    const params = new URLSearchParams({symbol:'NVDA', member});
    return 'stocks.html?' + params.toString() + '#congress-chart';
  }

  function nvdaRows(snapshot) {
    const absolute = outcome.value === 'absolute';
    const seen = new Set();
    const members = new Map();
    for (const event of snapshot.events) {
      const score = absolute ? event.absolute90dPct : event.excess90d;
      if (!Number.isFinite(score) || !event.member || event.tradeDate < '2024-01-01' || event.option) continue;
      if (!['buy', 'sell'].includes(event.side) || (side.value !== 'all' && event.side !== side.value)) continue;
      const key = [event.member, event.tradeDate, event.side].join('|');
      if (seen.has(key)) continue;
      seen.add(key);
      if (!members.has(event.member)) members.set(event.member, {name:event.member, nameKo:event.memberKo || memberNames[event.member], count:0, wins:0, buyN:0, buyWins:0, sellN:0, sellWins:0});
      const row = members.get(event.member);
      const win = absolute && event.side === 'sell' ? score < 0 : score > 0;
      row.count++;
      row[event.side + 'N']++;
      if (win) {
        row.wins++;
        row[event.side + 'Wins']++;
      }
    }
    return Array.from(members.values());
  }

  function cell(row, value, className) {
    const td = row.insertCell();
    td.textContent = value;
    if (className) td.className = className;
    return td;
  }

  function showTable(snapshot) {
    const isMarket = scope === marketScope;
    const isExcess = isMarket && sort.value === 'excess';
    const values = isMarket ? snapshot.rows : nvdaRows(snapshot);
    const rows = values.filter(row => row.count >= Number(minimum.value));
    const difference = isExcess ? (a,b) => b.excess-a.excess : (a,b) => b.wins*a.count-a.wins*b.count;
    rows.sort((a,b) => difference(a,b) || b.count-a.count || a.name.localeCompare(b.name));
    const head = table.tHead.rows[0];
    head.replaceChildren();
    const headers = isMarket ? ['순위 · 의원', '시장 초과 비율', '초과 / 매수', '평균 격차', '공시 지연 중앙값'] : ['순위 · 의원', '적중률', '적중 / 평가', '매수 적중', '매도 적중'];
    headers.forEach((label,index) => {
      const th = document.createElement('th');
      th.scope = 'col'; th.textContent = label;
      if (index >= 3) th.className = 'cr-wide';
      head.append(th);
    });
    const body = table.tBodies[0];
    body.replaceChildren();
    let rank = 0;
    rows.forEach((member, index) => {
      if (index === 0 || difference(member, rows[index-1]) !== 0) rank = index+1;
      const row = body.insertRow();
      const name = document.createElement('th');
      name.scope = 'row';
      const place = document.createElement('span');
      place.className = 'cr-place'; place.textContent = rank + '.';
      const label = member.nameKo || member.name;
      name.append(place, isMarket ? document.createTextNode(label) : link(label, profileChart(member.name)));
      const buy = member.buyN ? member.buyWins+' / '+member.buyN : '—';
      const sell = member.sellN ? member.sellWins+' / '+member.sellN : '—';
      const detail = document.createElement('small');
      detail.className = 'cr-mobile';
      detail.textContent = isMarket ? '평균 격차 ' + points(member.excess) + ' · 공시 ' + member.medianDelay + '일' : '매수 ' + buy + ' · 매도 ' + sell;
      name.append(detail);
      row.append(name);
      cell(row, pct(member.wins/member.count), isExcess ? '' : 'cr-highlight');
      cell(row, number.format(member.wins) + ' / ' + number.format(member.count));
      cell(row, isMarket ? points(member.excess) : buy, isExcess ? 'cr-wide cr-highlight' : 'cr-wide');
      cell(row, isMarket ? member.medianDelay + '일' : sell, 'cr-wide');
    });
    byId('cr-table-wrap').hidden = !rows.length;
    byId('cr-status').textContent = rows.length ? rows.length+'명 · 최소 '+minimum.value+'건' : '이 조건을 충족한 의원이 없습니다. 최소 평가 건수나 거래 방향을 바꿔 보세요.';
    byId('cr-asof').textContent = (isMarket ? '가격 기준일 ' : '공시 자료 기준일 ') + snapshot.asOf;
    byId('cr-caption').textContent = byId('cr-title').textContent + ' · ' + byId('cr-status').textContent;
  }

  function describe(snapshot) {
    const isMarket = scope === marketScope;
    const absolute = !isMarket && outcome.value === 'absolute';
    byId('cr-title').textContent = isMarket ? '전체 종목 매수 공시 순위' : '엔비디아 매매 적중률';
    byId('cr-context').textContent = isMarket
      ? '각 의원이 공시한 매수 중 같은 기간 S&P 500 추종 ETF(SPY)를 앞선 비율을 봅니다.'
      : absolute ? '매수 후 엔비디아가 오르거나, 매도 후 내리면 적중입니다.' : '매수 후 엔비디아가 SPY를 앞서거나, 매도 후 SPY를 밑돌면 적중입니다.';
    byId('cr-method-text').textContent = isMarket
      ? snapshot.tradeStart+' 이후 거래가 대상입니다. 각 공시 제출일 당일 또는 이후 첫 종가부터 '+snapshot.asOf+' 종가까지 SPY와 비교합니다. 배당을 제외하며, 각 거래의 평가 기간은 다릅니다. 평균 격차는 거래별 수익률에서 같은 기간 SPY 수익률을 뺀 값의 단순 평균입니다.'
      : '2024년 1월 이후 각 거래일을 기준으로 90일 성과를 평가합니다. 의원별로 같은 날 같은 방향의 거래를 한 건으로 묶고, 명시된 옵션과 90일 결과가 없는 거래는 제외합니다. '+(absolute ? '거래일과 90일 뒤 각각 당일 또는 이후 첫 거래일의 분할 조정 종가를 비교하며 배당은 제외합니다. 변동이 0이면 적중으로 세지 않습니다.' : 'SPY와의 성과 차이가 0이면 적중으로 세지 않습니다.')+' 의원 이름에는 배우자·가족 명의 공시도 포함될 수 있습니다. 당시 공시를 보고 따라 매매한 성과와는 차이가 있습니다.';
    const sourceLine = byId('cr-source');
    sourceLine.replaceChildren(document.createTextNode('자료 제공 · '), link(sources[scope].name, sources[scope].url));
    if (absolute && snapshot.absolute90dMethod?.sourceUrl) sourceLine.append(' · ', link('NVDA 일별 종가 (Yahoo Finance)',snapshot.absolute90dMethod.sourceUrl));
    if (isMarket) sourceLine.append(' · ', link('CC BY 4.0', 'https://creativecommons.org/licenses/by/4.0/'), ' · 평가 건수 필터와 적중률 정렬 적용');
  }

  function refresh() {
    const snapshot = data.get(scope);
    if (!snapshot) return;
    describe(snapshot);
    showTable(snapshot);
  }

  async function chooseScope(nextScope) {
    scope = nextScope;
    const isMarket = scope === marketScope;
    const token = ++requestNumber;
    document.querySelectorAll('[data-scope]').forEach(btn => btn.setAttribute('aria-pressed',String(btn.dataset.scope === scope)));
    byId('cr-sort-label').hidden = !isMarket;
    byId('cr-side-label').hidden = isMarket;
    byId('cr-outcome-label').hidden = true;
    minimum.replaceChildren();
    (isMarket ? [5,20,50] : [5,10,20]).forEach(n => minimum.add(new Option(n+'건 이상', String(n))));
    minimum.value = String(minimumByScope[scope]);
    byId('cr-table-wrap').hidden = true;
    byId('cr-retry').hidden = true;
    byId('cr-error').hidden = true;
    byId('cr-status').textContent = '집계 불러오는 중…';
    byId('cr-asof').textContent = '';
    byId('cr-title').textContent = isMarket ? '전체 종목 매수 공시 순위' : '엔비디아 매매 적중률';
    byId('cr-context').textContent = '';
    byId('cr-method').hidden = true;
    try {
      if (!data.has(nextScope)) {
        const response = await fetch(sources[nextScope].file);
        if (!response.ok) throw Error('HTTP ' + response.status);
        const snapshot = await response.json();
        const rows = isMarket ? snapshot.rows : snapshot.events;
        if (!Array.isArray(rows) || !snapshot.asOf) throw Error('Invalid snapshot');
        data.set(nextScope,snapshot);
      }
      if (token !== requestNumber) return;
      const snapshot = data.get(nextScope);
      if (!isMarket) {
        const absoluteAvailable = snapshot.events.some(event => Number.isFinite(event.absolute90dPct));
        byId('cr-outcome-label').hidden = !absoluteAvailable;
        if (!absoluteAvailable) outcome.value = 'relative';
      }
      byId('cr-method').hidden = false;
      refresh();
    } catch {
      if (token !== requestNumber) return;
      byId('cr-status').textContent = '자료를 불러오지 못했습니다.';
      byId('cr-error').hidden = false;
      byId('cr-error').replaceChildren('원본 자료 · ',link(sources[nextScope].name,sources[nextScope].url));
      byId('cr-retry').hidden = false;
    }
  }

  document.querySelectorAll('[data-scope]').forEach(btn => btn.addEventListener('click',() => chooseScope(btn.dataset.scope)));
  [side,outcome,sort].forEach(control => control.addEventListener('change',refresh));
  minimum.addEventListener('change',() => {minimumByScope[scope] = Number(minimum.value); refresh();});
  byId('cr-retry').addEventListener('click',() => chooseScope(scope));
  chooseScope(new URLSearchParams(location.search).get('scope') === marketScope ? marketScope : 'nvda');
})();
