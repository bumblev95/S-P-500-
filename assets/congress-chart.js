/* Congressional disclosures on the stock page's historical close series. */
(function () {
  'use strict';
  const supported = new Set(['NVDA']);
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

  function markup(symbol) {
    if (!supported.has(symbol)) {
      return '<aside class="cg-other">의원 거래 차트 지원 종목 <a href="stocks.html?symbol=NVDA">NVDA</a> · <a href="congress.html">의원 거래 적중률</a></aside>';
    }
    return '<section class="cg-chart" aria-label="의원 거래 공시"><div class="cg-heading">' +
      '<label class="cg-switch"><input type="checkbox" data-cg="enabled"> 의원 거래 보기</label>' +
      '<a href="congress.html">의원 거래 적중률 ↗</a></div>' +
      '<div data-cg="panel" hidden><div class="cg-filters">' +
      '<label>날짜 기준<select data-cg="basis"><option value="tradeDate">거래일</option><option value="disclosedDate">공시일</option></select></label>' +
      '<label>거래 방향<select data-cg="side"><option value="all">전체</option><option value="buy">매수</option><option value="sell">매도</option></select></label>' +
      '<label data-cg="memberLabel" hidden>의원<select data-cg="member"></select></label>' +
      '</div><p class="cg-status" data-cg="status" role="status" aria-live="polite"></p>' +
      '<div class="cg-date" data-cg="picker" hidden><label>날짜별 공시<select data-cg="date"></select></label></div>' +
      '<div class="cg-cluster" data-cg="cluster"></div><div class="cg-detail" data-cg="detail"></div>' +
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

  function load(symbol) {
    if (!cache.has(symbol)) {
      const job = fetch('data/congress/' + encodeURIComponent(symbol) + '.json')
        .then(response => {
          if (!response.ok) throw new Error('disclosures unavailable');
          return response.json();
        }).then(data => {
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
      const link = safeLink(e.filingUrl, '공시 원문 ↗') || safeLink(context.data.sourceUrl, '집계 출처 ↗');
      if (link) header.append(link);
      item.append(header, element('p', (ownerName[e.owner] || ownerName.unspecified) + ' · ' + (e.amount || '금액 미표기') + ' USD'));
      item.append(element('p', '거래일 ' + e.tradeDate + ' · 공시일 ' + e.disclosedDate));
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
    const spacing = (context.portraits ? 33 : 26) * scale;
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
    svg.setAttribute('role', 'group');
    const overlay = svgTag('g', { class: 'cg-overlay', 'aria-label': '의원 거래 표식' });
    context.overlay = overlay;
    let iconIndex = 0;
    for (const group of groups) {
      const dates = group.map(m => m.day).reverse();
      const events = dates.flatMap(d => byDay.get(d));
      const buy = events.some(e => e.side === 'buy'), sell = events.some(e => e.side === 'sell');
      const direction = buy && sell ? 'both' : buy ? 'buy' : 'sell';
      const sideText = direction === 'buy' ? '매수' : direction === 'sell' ? '매도' : '매수·매도';
      const names = Array.from(new Set(events.map(e=>e.member)));
      // Dates are newest first; only show a verified portrait belonging to this cluster.
      const representative = names.find(name => portraitUrl(context, name));
      const portrait = representative ? portraitUrl(context, representative) : null;
      const membersLabel = names.length === 1 ? names[0] : representative
        ? '대표 '+representative+' 외 '+(names.length-1)+'명'
        : '의원 '+names.length+'명';
      const radius = Math.min(35, Math.max(11, (portrait ? 13 : 9)*scale));
      const anchor = group[Math.floor((group.length-1)/2)];
      const badgeY = anchor.py < radius*3 ? anchor.py + radius*2.3 :
        direction === 'sell' && anchor.py < (svg.viewBox?.baseVal.height || 500)-radius*3.5 ? anchor.py+radius*2.3 : anchor.py-radius*2.3;
      const title = (dates.length === 1 ? dates[0] : dates[dates.length-1]+' ~ '+dates[0])+' · '+membersLabel+' · '+sideText+' '+events.length+'건';
      const g = svgTag('g', { class: 'cg-marker cg-mark-'+direction, role: 'button', tabindex: '0', 'aria-label': title+' 상세 보기' });
      g.append(svgTag('title', {}));
      g.firstChild.textContent = title;
      for (const m of group) {
        g.append(svgTag('line', { x1:m.px, y1:m.py, x2:anchor.px, y2:badgeY, class:'cg-stem' }));
        g.append(svgTag('circle', { cx:m.px, cy:m.py, r:2.8, class:'cg-pin' }));
      }
      const hit = svgTag('circle', {cx:anchor.px,cy:badgeY,r:radius*1.4,fill:'transparent'});
      const badge = svgTag('circle', {cx:anchor.px,cy:badgeY,r:radius,class:'cg-badge'});
      const glyph = direction === 'buy' ? '▲' : direction === 'sell' ? '▼' : '↕';
      const stamp = glyph + (events.length > 1 ? events.length : '');
      const typeScale = stamp.length > 2 ? .72 : stamp.length > 1 ? .84 : 1.05;
      const label = svgTag('text', { x:anchor.px, y:badgeY, 'font-size':radius*typeScale });
      label.textContent = stamp;
      g.append(hit,badge,label);
      if (portrait) {
        const clipId = 'cg-portrait-clip-' + (++iconIndex);
        const clip = svgTag('clipPath', {id:clipId});
        clip.append(svgTag('circle', {cx:anchor.px,cy:badgeY,r:radius-1.3}));
        const photo = svgTag('image', {
          x:anchor.px-radius, y:badgeY-radius, width:radius*2, height:radius*2,
          'clip-path':'url(#'+clipId+')', preserveAspectRatio:'xMidYMid slice'
        });
        const flag = svgTag('g', {'aria-hidden':'true'});
        const flagRadius=radius*(stamp.length>1?.68:.55), flagX=anchor.px+radius*.8, flagY=badgeY+radius*.75;
        flag.append(svgTag('circle',{cx:flagX,cy:flagY,r:flagRadius,class:'cg-badge'}));
        const icon=svgTag('text',{x:flagX,y:flagY,'font-size':flagRadius*typeScale});
        icon.textContent=label.textContent;
        flag.append(icon);
        const defs=svgTag('defs',{});
        defs.append(clip);
        photo.addEventListener('error',()=>{photo.remove();flag.remove();},{once:true});
        photo.setAttribute('href',portrait);
        g.append(defs,photo,flag);
      }
      const select = () => {
        addDetails(context, dates[0], dates);
        ui.date.focus({preventScroll:true});
        ui.detail.scrollIntoView?.({block:'nearest',behavior:'instant'});
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
    if (!sorted.length) ui.status.textContent = '선택한 조건에 해당하는 거래가 없습니다.';
    else if (!visible) ui.status.textContent = '현재 차트의 실제 종가와 일치하는 거래 날짜가 없습니다. 전체 기간의 공시는 아래에서 확인할 수 있습니다.';
    else ui.status.textContent = '현재 차트에 '+visible+'일 표시 · ▲ 매수 / ▼ 매도 / ↕ 혼합 · 숫자는 공시 건수, 여러 의원이 겹치면 선택한 날짜 기준 가장 최근 의원이 대표로 표시됩니다.';
  }

  function mount({root,symbol,points=[],x,y}) {
    current?.observer?.disconnect();
    current = null;
    if (!supported.has(symbol) || !root) return;
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
      ui.memberLabel.hidden = false;
      ui.credit.textContent = '자료 기준 '+data.asOf+' · 표식 가격은 해당일 종가 · ';
      const credit = safeLink(data.sourceUrl,'거래 자료');
      if (credit) ui.credit.append(credit);
      draw(context);
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
    loadPortraits().then(portraits => {
      if (current !== context || !root.isConnected || !portraits || !Object.keys(portraits).length) return;
      context.portraits=portraits;
      if (context.data && prefs.enabled) {
        markChart(context);
        addDetails(context, context.selectedDay, context.alternatives);
      }
    });
  }

  window.CongressChart = { markup, mount, loadData: load };
})();
