(function (root) {
  'use strict';

  const sectors = {
    'Information Technology': '기술',
    'Communication Services': '커뮤니케이션',
    'Consumer Discretionary': '임의소비재',
    'Consumer Staples': '필수소비재',
    'Energy': '에너지',
    'Financials': '금융',
    'Health Care': '헬스케어',
    'Industrials': '산업재',
    'Materials': '소재',
    'Real Estate': '부동산',
    'Utilities': '유틸리티',
  };
  const pageSize = 10;

  async function read(path) {
    const response = await fetch(path);
    if (!response.ok) throw Error('Stock discovery data unavailable');
    return response.json();
  }

  function mount({toggle, panel, onSelect}) {
    const ui = Object.fromEntries(Array.from(panel.querySelectorAll('[data-explore]'),
      el => [el.dataset.explore, el]));
    const doc = panel.ownerDocument;
    let items = [], page = 0, selected = '';
    let members = null, coverage = null, trends = null, sectorJob, congressJob, trendJob;
    let sectorError = false, congressError = false;

    function node(tag, text) {
      const el = doc.createElement(tag);
      el.textContent = text;
      return el;
    }

    function setOpen(open, restoreFocus = false) {
      panel.hidden = !open;
      toggle.setAttribute('aria-expanded', String(open));
      if (open) {
        loadSectors();
        loadTrends();
        if (ui.congress.checked) loadCongress();
        render();
      }
      if (restoreFocus) toggle.focus({preventScroll: true});
    }

    async function loadSectors() {
      if (members || sectorJob) return;
      sectorError = false;
      sectorJob = read('research/universe.json');
      try {
        const data = await sectorJob;
        if (!data.members || typeof data.members !== 'object') throw Error('Invalid sector data');
        members = data.members;
        const available = new Set(items.map(item => members[item.symbol]?.sector));
        for (const [value, label] of Object.entries(sectors)) {
          if (available.has(value)) {
            const option = node('option', label);
            option.value = value;
            ui.sector.append(option);
          }
        }
      } catch (_) {
        sectorError = true;
      } finally {
        sectorJob = null;
        if (!panel.hidden) render();
      }
    }

    async function loadCongress() {
      if (coverage || congressJob) return;
      congressError = false;
      congressJob = read('data/congress/by-symbol/index.json');
      try {
        const data = await congressJob;
        if (!data.symbols || typeof data.symbols !== 'object') throw Error('Invalid disclosure index');
        // NVDA's longer archive is published separately from the disclosure index.
        coverage = new Set([...Object.keys(data.symbols), 'NVDA']);
      } catch (_) {
        congressError = true;
      } finally {
        congressJob = null;
        if (!panel.hidden) render();
      }
    }

    async function loadTrends() {
      if (trends || trendJob) return;
      trendJob = read('forecasts/by-symbol/explore-trends.json');
      try {
        const data = await trendJob;
        if (data.schemaVersion === 1 && data.trends) trends = data.trends;
      } catch (_) {
        // Browsing still works when the optional price summary is unavailable.
      } finally {
        trendJob = null;
        if (!panel.hidden && trends) render();
      }
    }

    function trendView(symbol) {
      const trend = trends?.[symbol];
      if (!trend || !Number.isFinite(trend.returnPct) || !Array.isArray(trend.points)
          || trend.points.length !== 9 || !trend.points.every(v => Number.isFinite(v) && v >= 0 && v <= 100)) return null;
      const movement = node('span', '');
      const format = new Intl.NumberFormat('ko-KR', {maximumFractionDigits:2, signDisplay:'exceptZero'});
      const pct = format.format(trend.returnPct) + '%';
      movement.className = 'stock-explore-move ' + (trend.returnPct > 0 ? 'is-up' : trend.returnPct < 0 ? 'is-down' : '');
      movement.title = trend.from + '–' + trend.asOf + ' · 실제 종가 기준';
      movement.setAttribute('aria-label', '최근 21거래일 ' + pct);
      const ns = 'http://www.w3.org/2000/svg';
      const spark = doc.createElementNS(ns,'svg');
      spark.setAttribute('viewBox', '0 0 48 20');
      spark.setAttribute('aria-hidden', 'true');
      const line = doc.createElementNS(ns,'polyline');
      line.setAttribute('points', trend.points.map((value,i)=>[2+5.5*i,18-value*.16].join(',')).join(' '));
      line.setAttribute('fill','none');
      line.setAttribute('stroke','currentColor');
      line.setAttribute('stroke-width','1.6');
      line.setAttribute('stroke-linecap','round');
      line.setAttribute('stroke-linejoin','round');
      spark.append(line);
      movement.append(spark,node('span',pct));
      return movement;
    }

    function addResult(item) {
      const detail = members?.[item.symbol];
      const name = root.CompanySearch.name(item.symbol, item.name || detail?.name);
      const row = node('li', '');
      const link = node('a', '');
      link.href = 'stocks.html?symbol=' + encodeURIComponent(item.symbol);
      if (item.symbol === selected) link.setAttribute('aria-current', 'true');
      const identity = node('span',name === item.symbol ? '' : name);
      identity.className = 'stock-explore-identity';
      if (sectors[detail?.sector]) identity.append(node('small', sectors[detail.sector]));
      link.append(node('strong',item.symbol),identity);
      const movement = trendView(item.symbol);
      if (movement) link.append(movement);
      link.addEventListener('click', event => {
        if (event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        setOpen(false, true);
        onSelect(item.symbol);
      });
      row.append(link);
      ui.list.append(row);
    }

    function render() {
      const filterCongress = ui.congress.checked;
      const filterSector = ui.sector.value;
      ui.sector.disabled = !members;
      ui.list.replaceChildren();
      ui.pages.hidden = true;
      if (filterCongress && !coverage) {
        ui.status.textContent = congressError ? '의원 거래 목록을 불러오지 못했습니다. ' : '의원 거래 목록을 불러오는 중입니다.';
        if (congressError) addRetry(loadCongress);
        return;
      }
      const filtered = items.filter(item => (!filterSector || members[item.symbol]?.sector === filterSector)
        && (!filterCongress || coverage.has(item.symbol)));
      const totalPages = Math.ceil(filtered.length / pageSize);
      page = Math.min(page, Math.max(0, totalPages - 1));
      ui.status.textContent = filtered.length
        ? filtered.length + '개 종목 · 티커 A–Z' + (trends ? ' · 최근 21거래일' : '')
        : '선택한 조건에 해당하는 종목이 없습니다.';
      if (sectorError) {
        ui.status.append(' · 섹터 목록을 불러오지 못했습니다. ');
        addRetry(loadSectors);
      }
      for (const item of filtered.slice(page * pageSize, (page + 1) * pageSize)) addResult(item);
      ui.pages.hidden = totalPages <= 1;
      ui.position.textContent = (page + 1) + ' / ' + totalPages;
      ui.previous.disabled = page === 0;
      ui.next.disabled = page + 1 >= totalPages;
    }

    function addRetry(reload) {
      const retry = node('button', '다시 시도');
      retry.type = 'button';
      retry.addEventListener('click', () => { reload(); render(); });
      ui.status.append(retry);
    }

    toggle.addEventListener('click', () => setOpen(panel.hidden));
    ui.close.addEventListener('click', () => setOpen(false, true));
    panel.addEventListener('keydown', event => {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      setOpen(false, true);
    });
    ui.sector.addEventListener('change', () => { page = 0; render(); });
    ui.congress.addEventListener('change', () => {
      page = 0;
      if (ui.congress.checked) loadCongress();
      render();
    });
    ui.previous.addEventListener('click', () => {
      page--;
      render();
      if (ui.previous.disabled) ui.next.focus();
    });
    ui.next.addEventListener('click', () => {
      page++;
      render();
      if (ui.next.disabled) ui.previous.focus();
    });

    return {
      setItems(next) {
        items = Array.from(next).sort((a, b) => a.symbol.localeCompare(b.symbol, 'en'));
        toggle.disabled = !items.length;
        if (!panel.hidden) render();
      },
      setSelection(symbol) {
        selected = symbol;
        if (!panel.hidden) render();
      },
    };
  }

  root.StockExplore = {mount};
})(window);
