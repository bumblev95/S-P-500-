(function (root) {
  'use strict';
  if (!root.document || root.SiteAnalytics) return;
  const doc = root.document;
  const ID = 'G-0C529GQ91Z';
  const BASE = '/S-P-500-/';
  const KEY = 'sp500.analytics.consent.v1';
  const pages = {
    'index.html': '메인', 'stocks.html': '주식', 'crypto.html': '코인 현물',
    'futures.html': '선물', 'simulation.html': '모의운용', 'advanced.html': '고급 분석',
    'research.html': '검증 자료실', 'model-validation.html': '모델 검증',
    'signal-lab.html': '신호 연구', 'leverage-lab.html': '레버리지 연구',
    'exit-experiment.html': '청산 연구', 'momentum-experiment.html': '모멘텀 연구',
    'selector-experiment.html': '선택 연구', 'privacy.html': '개인정보 안내'
  };
  const filename = root.location.pathname.split('/').pop() || 'index.html';
  const eligible = root.location.hostname === 'bumblev95.github.io' &&
    root.location.pathname.startsWith(BASE) && Object.hasOwn(pages, filename);
  const canonical = 'https://bumblev95.github.io' + BASE + (filename === 'index.html' ? '' : filename);
  const pageName = pages[filename] || '';
  const features = {
    horizon: ['30', '120', '126', '252', '365'],
    path: ['center', 'sample'],
    mode: ['center', 'sample', 'forward', 'replay'],
    timeframe: ['5m', '15m', '1d'],
    asset: ['stocks', 'crypto'],
    sector: ['XLK', 'XLC', 'XLY', 'XLF', 'XLI', 'XLV', 'XLP', 'XLRE', 'XLU', 'XLB', 'XLE'],
    profile: ['momentumBoost5xRisk4', 'momentumBoostOne', 'momentumBreakoutOne',
      'momentumBreakoutThree', 'momentum14Target6', 'momentum14', 'wideRecovery', 'leverage5x3x', 'baseline'],
    advanced_view: ['screen', 'compare', 'value', 'validation'],
    refresh: ['click'], levels: ['toggle'], trade_chart: ['open']
  };
  let consent = null, started = false, banner = null, latestAsset = null, lastAsset = '';
  function readChoice() {
    try { const c = root.localStorage.getItem(KEY); return ['granted', 'denied'].includes(c) ? c : null; }
    catch (_) { return null; }
  }
  consent = readChoice();
  if (new URLSearchParams(root.location.search).get('analytics') === 'off') {
    consent = 'denied';
    try { root.localStorage.setItem(KEY, consent); } catch (_) {}
  }
  root['ga-disable-' + ID] = true;
  function gtag() { root.dataLayer.push(arguments); }
  function canSend() { return eligible && consent === 'granted' && started && !root['ga-disable-' + ID]; }
  function send(name, parameters) {
    if (!canSend()) return;
    gtag('event', name, Object.assign({page_name: pageName, page_location: canonical}, parameters));
  }
  function viewAsset(type, value) {
    const ticker = String(value || '').toUpperCase();
    if (!['stock', 'spot', 'futures'].includes(type) || !/^[A-Z][A-Z0-9.-]{0,9}$/.test(ticker)) return;
    latestAsset = {asset_type: type, ticker: ticker};
    const key = type + ':' + ticker;
    if (!canSend() || lastAsset === key) return;
    lastAsset = key;
    send(type === 'stock' ? 'stock_view' : 'coin_view', latestAsset);
  }
  function searchSelected(value) {
    const ticker = String(value || '').toUpperCase();
    if (/^[A-Z][A-Z0-9.-]{0,9}$/.test(ticker)) send('search_result_select', {ticker: ticker});
  }
  function feature(name, value) {
    const choice = String(value || '');
    if (features[name] && features[name].includes(choice)) send('feature_use', {feature: name, choice: choice});
  }
  function start() {
    if (!eligible || consent !== 'granted') return;
    root['ga-disable-' + ID] = false;
    if (started) {
      gtag('consent', 'update', {analytics_storage: 'granted'});
      return;
    }
    started = true;
    root.dataLayer = root.dataLayer || [];
    root.gtag = root.gtag || gtag;
    gtag('consent', 'default', {
      analytics_storage: 'denied', ad_storage: 'denied',
      ad_user_data: 'denied', ad_personalization: 'denied'
    });
    gtag('consent', 'update', {analytics_storage: 'granted'});
    gtag('js', new Date());
    let referrer = '';
    try { if (doc.referrer) referrer = new URL(doc.referrer).origin + '/'; } catch (_) {}
    // Standard config sends one initial page_view. No duplicate manual page_view.
    gtag('config', ID, {
      page_title: pageName + ' · S&P 500', page_location: canonical, page_referrer: referrer,
      allow_google_signals: false, allow_ad_personalization_signals: false,
      cookie_domain: 'none', cookie_path: BASE, cookie_flags: 'SameSite=Lax;Secure'
    });
    const script = doc.createElement('script');
    script.async = true;
    script.src = 'https://www.googletagmanager.com/gtag/js?id=' + ID;
    script.dataset.siteAnalytics = 'ga4';
    doc.head.appendChild(script);
    if (latestAsset) viewAsset(latestAsset.asset_type, latestAsset.ticker);
  }
  function clearCookies() {
    const names = ['_ga', '_ga_' + ID.slice(2)];
    for (const name of names) doc.cookie = name + '=; Max-Age=0; Path=' + BASE + '; SameSite=Lax; Secure';
  }
  function setConsent(choice) {
    if (!['granted', 'denied'].includes(choice)) return;
    consent = choice;
    try { root.localStorage.setItem(KEY, choice); } catch (_) {}
    if (choice === 'granted') start();
    else {
      root['ga-disable-' + ID] = true;
      if (started) gtag('consent', 'update', {analytics_storage: 'denied'});
      clearCookies();
    }
    if (banner) banner.hidden = true;
    const status = doc.getElementById('site-analytics-choice');
    if (status) status.textContent = choice === 'granted' ? '방문 통계 허용 중' : '방문 통계 거부 중';
  }
  function settings() { if (banner) { banner.hidden = false; banner.querySelector('button').focus(); } }
  root.SiteAnalytics = {viewAsset: viewAsset, searchSelected: searchSelected, feature: feature,
    setConsent: setConsent, settings: settings};
  function clicked(event) {
    const target = event.target.closest && event.target.closest('button,a');
    if (!target || target.disabled) return;
    const attributes = {h: 'horizon', path: 'path', mode: 'mode', tf: 'timeframe',
      asset: 'asset', sector: 'sector', profile: 'profile', view: 'advanced_view'};
    for (const key of Object.keys(attributes)) {
      if (target.dataset[key] !== undefined) feature(attributes[key], target.dataset[key]);
    }
    if (target.id === 'refresh') feature('refresh', 'click');
    if (target.id === 'levelToggle') feature('levels', 'toggle');
    if (target.dataset.trade) feature('trade_chart', 'open');
    if (target.tagName !== 'A') return;
    try {
      const url = new URL(target.href, root.location.href);
      if (!['https:', 'http:'].includes(url.protocol)) return;
      if (url.origin === root.location.origin && url.pathname.startsWith(BASE)) {
        const file = url.pathname.split('/').pop() || 'index.html';
        if (pages[file]) send('nav_click', {destination: pages[file]});
      } else if (target.closest('#home-news,#companyEvents')) {
        send('news_click', {link_domain: url.hostname,
          area: target.closest('#home-news') ? 'market_news' : 'company_news'});
      }
    } catch (_) {}
  }
  function init() {
    if (!eligible) return;
    // Old main-page ticker links immediately redirect to stocks.html.
    if (filename === 'index.html' && new URLSearchParams(root.location.search).has('symbol')) return;
    banner = doc.createElement('aside');
    banner.className = 'site-analytics-consent';
    banner.setAttribute('aria-label', '방문 통계 선택');
    banner.hidden = consent !== null;
    banner.innerHTML = '<div><strong>방문 통계</strong><p>방문·기능 사용 통계를 Google Analytics로 수집해 사이트를 개선합니다. '
      + '<a href="privacy.html#analytics">자세히</a></p></div><div class="site-analytics-actions">'
      + '<button type="button" data-analytics-choice="denied">거부</button>'
      + '<button type="button" data-analytics-choice="granted">허용</button></div>';
    banner.querySelectorAll('[data-analytics-choice]').forEach(button =>
      button.addEventListener('click', () => setConsent(button.dataset.analyticsChoice)));
    const footer = doc.createElement('div');
    footer.className = 'site-analytics-footer';
    const button = doc.createElement('button');
    button.type = 'button'; button.textContent = '방문 통계 설정';
    button.addEventListener('click', settings);
    footer.appendChild(button);
    doc.body.appendChild(footer); doc.body.appendChild(banner);
    doc.addEventListener('click', clicked, true);
    doc.addEventListener('change', event => {
      if (event.target.id === 'analysisHorizon') feature('horizon', event.target.value);
    });
    root.addEventListener('storage', event => {
      if (event.key === KEY && ['granted', 'denied'].includes(event.newValue)) setConsent(event.newValue);
    });
    if (consent === 'granted') start();
    const status = doc.getElementById('site-analytics-choice');
    if (status) status.textContent = consent === 'granted' ? '방문 통계 허용 중' : consent === 'denied' ? '방문 통계 거부 중' : '아직 선택하지 않았습니다';
  }
  if (doc.readyState === 'loading') doc.addEventListener('DOMContentLoaded', init, {once: true});
  else init();
})(window);
