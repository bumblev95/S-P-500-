/* Congressional disclosures on the stock page's historical close series. */
(function () {
  'use strict';
  const archiveSymbol = 'NVDA';
  const shardRoot = 'data/congress/by-symbol/';
  let indexRequest;
  const cache = new Map();
  const ns = 'http://www.w3.org/2000/svg';
  let portraitRequest;
  const prefs = { enabled: true, basis: 'tradeDate', side: 'all' };
  const selection = new Map();
  let current = null;
  const ownerName = {
    spouse: '배우자', dependent: '부양 자녀', joint: '공동 명의',
    self: '본인', unspecified: '명의 구분 미표기'
  };

  function markup() {
    return '<section class="cg-chart" aria-label="의원 거래 공시"><div class="cg-heading">' +
      '<label class="cg-switch"><input type="checkbox" data-cg="enabled"> 의원 거래 보기</label>' +
      '<a href="congress.html">의원 거래 적중률 ↗</a></div>' +
      '<div data-cg="panel" hidden><div class="cg-cluster" data-cg="cluster"></div>' +
      '<div class="cg-detail" data-cg="detail" tabindex="-1"></div><div class="cg-filters">' +
      '<label>날짜 기준<select data-cg="basis"><option value="tradeDate">거래일</option><option value="disclosedDate">공시 제출일</option></select></label>' +
      '<label>거래 방향<select data-cg="side"><option value="all">전체</option><option value="buy">매수</option><option value="sell">매도</option></select></label>' +
      '<label data-cg="memberLabel" hidden>의원<select data-cg="member"></select></label>' +
      '</div><p class="cg-status" data-cg="status" role="status" aria-live="polite"></p>' +
      '<div class="cg-date" data-cg="picker" hidden><label>날짜별 공시<select data-cg="date"></select></label></div>' +
      '<p class="cg-foot" data-cg="credit"></p></div></section>';
  }

  function element(tag, text) {
    const el = document.createElement(tag);
    if (text !== undefined) el.textContent = text;
    return el;
  }

  function option(value, label) {
    const el = element('option', label);
    el.value = value;
    return el;
  }

  function svgTag(tag, attrs) {
    const el = document.createElementNS(ns, tag);
    for (const [key, value] of Object.entries(attrs)) el.setAttribute(key, value);
    return el;
  }

  function safeLink(url, label) {
    try {
      const address = new URL(url);
      if (address.protocol !== 'https:') return null;
      const anchor = element('a', label);
      anchor.href = address.href;
      anchor.target = '_blank';
      anchor.rel = 'noopener noreferrer';
      return anchor;
    } catch (_) { return null; }
  }

  async function readJSON(url) {
    const response = await fetch(url);
    if (!response.ok) throw new Error('disclosures unavailable');
    return response.json();
  }

  function loadIndex() {
    if (!indexRequest) {
      indexRequest = readJSON(shardRoot + 'index.json').then(index => {
        if (!index.symbols || !Array.isArray(index.sources) || !index.asOf) {
          throw new Error('invalid disclosure index');
        }
        return index;
      }).catch(error => { indexRequest = null; throw error; });
    }
    return indexRequest;
  }

  async function readSymbol(symbol) {
    if (symbol === archiveSymbol) return readJSON('data/congress/NVDA.json');
    const index = await loadIndex();
    const count = Object.hasOwn(index.symbols, symbol) ? index.symbols[symbol] : 0;
    if (!count) return {symbol, events:[], sources:index.sources, asOf:index.asOf, licenseUrl:index.licenseUrl};
    const data = await readJSON(shardRoot + encodeURIComponent(symbol) + '.json');
    if (data.events?.length !== count) throw new Error('disclosure count mismatch');
    return {...data, sources:index.sources, asOf:index.asOf, licenseUrl:index.licenseUrl};
  }

  function load(symbol) {
    if (!cache.has(symbol)) {
      const job = readSymbol(symbol).then(data => {
        if (data.symbol !== symbol || !Array.isArray(data.events)) throw new Error('invalid disclosures');
        return data;
      }).catch(error => { cache.delete(symbol); throw error; });
      cache.set(symbol, job);
    }
    return cache.get(symbol);
  }

  function loadPortraits() {
    if (!portraitRequest) {
      portraitRequest = fetch('assets/congress-portraits.json')
        .then(response => response.ok ? response.json() : {})
        .catch(() => ({}));
    }
    return portraitRequest;
  }

  function portraitUrl(context, name) {
    const path = context.portraits?.[name];
    return typeof path === 'string' && /^assets\/congress-portraits\/[a-zA-Z0-9_-]+\.(?:jpg|jpeg|png|webp)$/i.test(path) ? path : null;
  }

  function actionName(event) {
    const action = event.side === 'buy' ? '매수' : event.partial ? '일부 매도' : '매도';
    return event.option ? '옵션 ' + action : action;
  }

  function addDetails(context, day, alternatives) {
    const { ui, byDay, datesOnChart } = context;
    const list = byDay.get(day) || [];
    ui.date.value = day;
    context.selectedDay = day;
    context.alternatives = alternatives;
    if (context.data) selection.set(context.symbol, {member:ui.member.value,day});
    ui.detail.replaceChildren();
    ui.cluster.replaceChildren();
    if (alternatives && alternatives.length > 1) {
      ui.cluster.append(element('span', '이 표식의 날짜'));
      for (const date of alternatives) {
        const btn = element('button', date.slice(5));
        btn.type = 'button';
        btn.setAttribute('aria-label', date + ' 공시 보기');
        btn.setAttribute('aria-pressed', String(date === day));
        btn.addEventListener('click', () => addDetails(context, date, alternatives));
        ui.cluster.append(btn);
      }
    }
    if (!list.length) return;
    const title = element('h3', day + ' · ' + list.length + '건');
    if (!datesOnChart.has(day)) title.append(element('small', '  차트 표시 범위 밖 또는 해당일 종가 없음'));
    ui.detail.append(title);
    const ul = element('ul');
    for (const e of list) {
      const item = element('li');
      item.className = 'cg-item';
      const header = element('div');
      const action = element('b', actionName(e));
      action.className = 'cg-' + (e.side === 'buy' ? 'buy' : 'sell');
      const portrait = portraitUrl(context, e.member);
      if (portrait) {
        const image = element('img');
        image.className = 'cg-portrait';
        image.alt = '';
        image.loading = 'lazy';
        image.addEventListener('error', () => image.remove(), {once:true});
        image.src = portrait;
        header.append(image);
      }
      header.append(action, element('strong', e.member));
      if (e.chamber) header.append(element('span', e.chamber === 'senate' ? '상원' : '하원'));
      const link = safeLink(e.filingUrl, '공시 원문 ↗') || safeLink(context.data.sourceUrl, '집계 출처 ↗');
      if (link) header.append(link);
      const amount = e.amount ? '신고 금액 범위 ' + e.amount + ' USD' : '신고 금액 범위 미표기';
      item.append(header, element('p', (ownerName[e.owner] || ownerName.unspecified) + ' · ' + amount));
      const basis = e.chamber ? '공시 제출일 ' : '공시일 ';
      const delay = Number.isInteger(e.delayDays) ? ' · 제출까지 ' + e.delayDays + '일' : '';
      item.append(element('p', '거래일 ' + e.tradeDate + ' · ' + basis + e.disclosedDate + delay));
      if (e.optionDescription) item.append(element('p', e.optionDescription));
      if (!e.option && Number.isFinite(e.absolute90dPct) && Number.isFinite(e.excess90d)) {
        const signed = value => (value > 0 ? '+' : '') + value.toFixed(1);
        const relative = e.side === 'sell' ? -e.excess90d : e.excess90d;
        item.append(element('p','거래일 이후 90일 · NVDA '+signed(e.absolute90dPct)+'% · SPY 대비 '+signed(relative)+'%p'));
      }
      ul.append(item);
    }
    ui.detail.append(ul);
  }

  function clearOverlay(context) {
    context.overlay?.remove();
    context.overlay = null;
    if (context.svg) {
      if (context.svgRole) context.svg.setAttribute('role', context.svgRole);
      else context.svg.removeAttribute('role');
    }
  }

  function markChart(context) {
    clearOverlay(context);
    const { svg, ui, points, x, y, byDay } = context;
    context.datesOnChart.clear();
    if (!prefs.enabled || !svg || typeof x !== 'function' || typeof y !== 'function') return;
    const groups = [];
    const viewWidth = svg.viewBox?.baseVal.width || 930;
    const scale = viewWidth / Math.max(260, svg.getBoundingClientRect().width || viewWidth);
    const spacing = 29 * scale;
    const plotBottom = Number(svg.dataset.plotBottom);
    const badgeY = plotBottom + 16 * scale;
    const height = svg.viewBox?.baseVal.height || 454;
    const radius = 11 * scale;
    const rowY = Math.min(badgeY, height - 30 - radius);
    for (const point of points) {
      const day = point.date;
      if (!byDay.has(day) || point.actual === false || !(point.close > 0)) continue;
      const px = x(point.offset), py = y(point.close);
      if (!Number.isFinite(px) || !Number.isFinite(py)) continue;
      context.datesOnChart.add(day);
      const mark = { day, px, py };
      const last = groups[groups.length-1];
      if (last && px-last[0].px < spacing) last.push(mark);
      else groups.push([mark]);
    }
    if (!groups.length) return;
    const center = group => group[Math.floor((group.length-1)/2)];
    const separated = [];
    for (const group of groups) {
      let next = group;
      while (separated.length && center(next).px - center(separated.at(-1)).px < spacing) {
        next = separated.pop().concat(next);
      }
      separated.push(next);
    }
    svg.setAttribute('role', 'group');
    const overlay = svgTag('g', { class: 'cg-overlay', 'aria-label': '의원 거래 표식' });
    context.overlay = overlay;
    for (const group of separated) {
      const dates = group.map(m => m.day).reverse();
      const events = dates.flatMap(d => byDay.get(d));
      const buy = events.some(e => e.side === 'buy'), sell = events.some(e => e.side === 'sell');
      const direction = buy && sell ? 'both' : buy ? 'buy' : 'sell';
      const sideText = direction === 'buy' ? '매수' : direction === 'sell' ? '매도' : '매수·매도';
      const names = Array.from(new Set(events.map(e=>e.member)));
      const membersLabel = names.length === 1 ? names[0] : '의원 '+names.length+'명';
      const anchor = center(group);
      const title = (dates.length === 1 ? dates[0] : dates[dates.length-1]+' ~ '+dates[0])+' · '+membersLabel+' · '+sideText+' '+events.length+'건';
      const g = svgTag('g', { class: 'cg-marker cg-mark-'+direction, role: 'button', tabindex: '0', 'aria-label': title+' 상세 보기' });
      g.append(svgTag('title', {}));
      g.firstChild.textContent = title;
      for (const m of group) {
        g.append(svgTag('circle', { cx:m.px, cy:m.py, r:2.6 * scale, class:'cg-pin' }));
      }
      const hit = svgTag('circle', {cx:anchor.px,cy:rowY,r:radius*1.4,fill:'transparent'});
      const badge = svgTag('circle', {cx:anchor.px,cy:rowY,r:radius,class:'cg-badge'});
      const glyph = direction === 'buy' ? '▲' : direction === 'sell' ? '▼' : '↕';
      const stamp = glyph + (events.length > 1 ? events.length : '');
      const typeScale = stamp.length > 2 ? .72 : stamp.length > 1 ? .84 : 1.05;
      const label = svgTag('text', { x:anchor.px, y:rowY, 'font-size':radius*typeScale });
      label.textContent = stamp;
      g.append(hit,badge,label);
      const select = () => {
        addDetails(context, dates[0], dates);
        const focus = ui.cluster.querySelector('button[aria-pressed="true"]') || ui.detail;
        focus.focus({preventScroll:true});
        (focus === ui.detail ? ui.detail : ui.cluster).scrollIntoView?.({block:'nearest',behavior:'instant'});
      };
      g.addEventListener('click', select);
      g.addEventListener('keydown', event => {
        if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); select(); }
      });
      overlay.append(g);
    }
    svg.append(overlay);
  }

  function draw(context) {
    const { ui, data } = context;
    ui.panel.hidden = !prefs.enabled;
    if (!prefs.enabled) { clearOverlay(context); return; }
    if (!data) return;
    const byDay = new Map();
    for (const event of data.events) {
      if (ui.member.value && ui.member.value !== event.member) continue;
      if (prefs.side !== 'all' && prefs.side !== event.side) continue;
      const day = event[prefs.basis];
      if (!day) continue;
      if (!byDay.has(day)) byDay.set(day, []);
      byDay.get(day).push(event);
    }
    context.byDay = byDay;
    markChart(context);
    const sorted = Array.from(byDay.keys()).sort().reverse();
    const visible = context.datesOnChart.size;
    ui.picker.hidden = !sorted.length;
    ui.date.replaceChildren(option('', '날짜를 선택하세요'));
    for (const day of sorted) {
      const suffix = context.datesOnChart.has(day) ? ' · 차트 표시' : '';
      ui.date.append(option(day, day + ' · ' + byDay.get(day).length + '건' + suffix));
    }
    let selected = byDay.has(context.selectedDay) ? context.selectedDay : '';
    if (!selected && ui.member.value) selected = sorted.find(day => context.datesOnChart.has(day)) || sorted[0] || '';
    addDetails(context, selected);
    if (!data.events.length) ui.status.textContent = '현재 수집 자료에서 이 종목의 의원 매수·매도 공시를 확인하지 못했습니다.';
    else if (!sorted.length) ui.status.textContent = '선택한 조건에 해당하는 거래가 없습니다.';
    else if (!visible) ui.status.textContent = '현재 차트의 실제 종가와 일치하는 거래 날짜가 없습니다. 전체 기간의 공시는 아래에서 확인할 수 있습니다.';
    else ui.status.textContent = '공시 '+data.events.length+'건 · 현재 차트에 '+visible+'일 표시 · ▲ 매수 / ▼ 매도 / ↕ 혼합 · 숫자는 공시 건수입니다.';
  }

  function mount({root,symbol,points=[],x,y}) {
    current?.observer?.disconnect();
    current = null;
    if (!root) return;
    const panel = root.matches?.('.cg-chart') ? root : root.querySelector('.cg-chart');
    if (!panel) return;
    const ui = Object.fromEntries(Array.from(panel.querySelectorAll('[data-cg]'), el => [el.dataset.cg, el]));
    const svg = root.querySelector('.chartStage svg');
    const saved = selection.get(symbol);
    const context = {ui,svg,symbol,svgRole:svg?.getAttribute('role'),points:points||[],x,y,data:null,byDay:new Map(),datesOnChart:new Set(),selectedDay:saved?.day || ''};
    current = context;
    const query = new URLSearchParams(window.location.search);
    const desiredMember = saved ? saved.member : (query.get('member') || '');
    ui.enabled.checked = prefs.enabled;
    ui.basis.value = prefs.basis;
    ui.side.value = prefs.side;
    ui.memberLabel.hidden = true;
    ui.status.textContent = '거래 공시를 불러오는 중입니다.';
    ui.enabled.onchange = () => { prefs.enabled=ui.enabled.checked; draw(context); };
    ui.basis.onchange = () => { prefs.basis=ui.basis.value; context.selectedDay=''; draw(context); };
    ui.side.onchange = () => { prefs.side=ui.side.value; draw(context); };
    ui.member.onchange = () => { context.selectedDay=''; draw(context); };
    ui.date.onchange = () => addDetails(context, ui.date.value);
    draw(context);
    const retrieve = () => load(symbol).then(data => {
      if (current !== context || !root.isConnected) return;
      context.data = data;
      const names = Array.from(new Set(data.events.map(e=>e.member))).sort((a,b)=>a.localeCompare(b,'en'));
      ui.member.replaceChildren(option('','전체 의원'),...names.map(name=>option(name,name)));
      const name = names.find(n=>n.toLowerCase()===desiredMember.toLowerCase());
      if (name) ui.member.value = name;
      ui.memberLabel.hidden = !names.length;
      ui.credit.textContent = '자료 기준 ' + data.asOf + ' · 표식 가격은 해당일 종가 · ';
      if (data.sources) {
        data.sources.forEach((source, index) => {
          const link = safeLink(source.url, source.name);
          if (!link) return;
          if (index) ui.credit.append(' / ');
          ui.credit.append(link);
        });
        const license = safeLink(data.licenseUrl, 'CC BY 4.0');
        if (license) ui.credit.append(' · ', license, ' · 차트용으로 정리');
        ui.credit.append(' · 제출일과 실제 공개 시점은 다를 수 있습니다.');
      } else {
        const credit = safeLink(data.sourceUrl, '거래 자료');
        if (credit) ui.credit.append(credit);
      }
      draw(context);
      if (!names.length) return;
      loadPortraits().then(portraits => {
        if (current !== context || !root.isConnected || !portraits || !Object.keys(portraits).length) return;
        context.portraits = portraits;
        if (prefs.enabled) {
          if (context.selectedDay) addDetails(context, context.selectedDay, context.alternatives);
        }
      });
      if (svg && typeof ResizeObserver !== 'undefined') {
        let width = svg.getBoundingClientRect().width;
        context.observer = new ResizeObserver(() => {
          if (current !== context || !root.isConnected) { context.observer.disconnect(); return; }
          const next = svg.getBoundingClientRect().width;
          if (next !== width) { width=next; markChart(context); }
        });
        context.observer.observe(svg);
      }
    }).catch(() => {
      if (current !== context || !root.isConnected) return;
      ui.status.textContent = '거래 공시를 불러오지 못했습니다. ';
      const retry = element('button','다시 시도');
      retry.type='button';
      retry.onclick=()=>{ui.status.textContent='거래 공시를 불러오는 중입니다.'; retrieve();};
      ui.status.append(retry);
    });
    retrieve();

  }

  window.CongressChart = { markup, mount, loadData: load };
})();
