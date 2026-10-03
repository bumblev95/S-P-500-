// Optional real-browser regression: npm install --no-save playwright
// PLAYWRIGHT_MODULE/BROWSER_BIN can point to an already installed QA runtime.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(__dirname, '..');
const output = process.env.INDICATOR_SCREENSHOTS || '/tmp/sp500-indicator-qa';
const read = file => JSON.parse(fs.readFileSync(path.join(root, file)));
const market = read('market/latest.json'), forecasts = read('forecasts/latest.json');
const clock = Date.parse(market.generatedAt) + 1000;
const types = {'.html':'text/html', '.js':'application/javascript', '.css':'text/css', '.json':'application/json'};
const server = http.createServer((req, res) => {
  const file = path.resolve(root, '.' + decodeURIComponent(new URL(req.url, 'http://localhost').pathname));
  if (!file.startsWith(root + path.sep)) {res.writeHead(403); res.end(); return;}
  try {res.setHeader('Content-Type', types[path.extname(file)] || 'application/octet-stream'); res.end(fs.readFileSync(file));}
  catch (_) {res.writeHead(404); res.end('missing');}
});
async function ready(page, url, selector) {
  await page.goto(url, {waitUntil:'networkidle'});
  await page.waitForSelector(selector);
}
async function fits(page, selector) {
  const bad = await page.locator(selector).evaluateAll(nodes => nodes.filter(n => {
    const r = n.getBoundingClientRect();
    return r.left < -1 || r.right > innerWidth + 1 || n.scrollWidth > n.clientWidth + 1;
  }).map(n => ({class:n.className, width:n.clientWidth, scroll:n.scrollWidth,
    left:n.getBoundingClientRect().left, right:n.getBoundingClientRect().right})));
  assert.deepEqual(bad, [], page.url() + ': ' + selector + ' must fit the viewport');
}
(async () => {
  fs.mkdirSync(output, {recursive:true});
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const base = `http://127.0.0.1:${server.address().port}/`;
  let browser;
  try {
    browser = await chromium.launch({headless:true,
      ...(process.env.BROWSER_BIN ? {executablePath:process.env.BROWSER_BIN} : {}), args:['--no-sandbox']});
    const errors = [];
    for (const width of [320,390,1280]) {
      const page = await browser.newPage({viewport:{width,height:900}, deviceScaleFactor:1});
      page.on('pageerror', e => errors.push(e.message));
      await page.addInitScript(now => {
        const OriginalDate = Date;
        window.Date = class extends OriginalDate {
          constructor(...args) {super(...(args.length ? args : [now]));}
          static now() {return now;}
        };
        // The legacy detail panel is empty until a stock has been selected.
        // Use an isolated saved record, as in test_legacy_assessment.cjs.
        if (location.pathname.endsWith('/advanced-legacy.html')) {
          localStorage.setItem('sp500_sector_valuation_dashboard_ko_family_v25', JSON.stringify({
            selectedSymbol:'NVDA',selectedSector:'All',lastConstituentRefresh:now,
            settings:{years:3,analysisMode:3,autoSave:false}, stocks:[{symbol:'NVDA',
              name:'QA saved record',sector:'Watchlist',isCustom:true,price:200,forwardEPS:6,
              epsGrowth:10,revGrowth:8,grossMargin:40,opMargin:25,exitPE:22,discountRate:12,
              risk:{rate:2,cyc:2,margin:2,balance:2,crowding:2,reg:2}}]
          }));
        }
      }, clock);
      await page.route('**/config/*.json*', route => route.fulfill({json:{sheetCsvUrl:'',submitUrl:''}}));
      for (const [file,selector] of [['index.html','.stockAssessment'],['advanced.html','.stockAssessment'],
        ['advanced-legacy.html','.stockAssessment'],['crypto.html','[data-indicator="신규 진입 판단"]']]) {
        await ready(page, base + file, selector);
        await fits(page, '.vi-gauge');
        const gauge = page.locator(selector).first();
        await gauge.screenshot({path:path.join(output, `${file.replace('.html','')}-${width}.png`)});
        if (file === 'index.html') {
          const risk = page.locator('#sharedRisk');
          await risk.locator('details').first().evaluate(n => n.open = true);
          await fits(page, '.ds-risk-overview, .ds-risk-table');
          await risk.screenshot({path:path.join(output, `risk-${width}.png`)});
          await page.getByRole('button', {name:'1년',exact:true}).click();
          assert.equal(await page.locator('.stockAssessment .vi-gauge').count(), 2);
        }
      }
      await page.close();
    }
    // Failed/stale feeds get grey indicators without a pointer on the real page.
    const page = await browser.newPage({viewport:{width:390,height:900}});
    page.on('pageerror', e => errors.push(e.message));
    await page.route('**/forecasts/latest.json*', route => route.fulfill({json:{stocks:{
      NVDA:{...forecasts.stocks.NVDA, fresh:false}
    }}}));
    await page.route('**/market/latest.json*', route => route.fulfill({json:null}));
    await ready(page, base + 'index.html', '.stockAssessment');
    assert.equal(await page.locator('.stockAssessment .vi-unknown').count(), 2);
    assert.equal(await page.locator('.stockAssessment .vi-pointer').count(), 0);
    await page.locator('#sharedRisk .vi-unknown').waitFor();
    assert.equal(await page.locator('#sharedRisk .vi-pointer').count(), 0);
    await page.locator('.stockAssessment').screenshot({path:path.join(output,'stock-unavailable.png')});
    // Fixture responses exercise the exchange page only; no market files change.
    let failed = false;
    await page.unrouteAll();
    await page.route('https://api.hyperliquid.xyz/info', route => {
      if (failed) return route.fulfill({status:403, json:{error:'QA blocked feed'}});
      const body = route.request().postDataJSON(), now = Date.now();
      if (body.type === 'metaAndAssetCtxs') return route.fulfill({json:[{universe:[{name:'BTC'}]},
        [{markPx:'100',oraclePx:'100',funding:'0',openInterest:'1000000',dayNtlVlm:'1000000000'}]]});
      if (body.type === 'l2Book') return route.fulfill({json:{time:now,levels:[[{px:'99.999'}],[{px:'100.001'}]]}});
      const ms = {'5m':300000,'15m':900000,'1h':3600000,'1d':86400000}[body.req.interval];
      const end = Math.floor(now / ms) * ms;
      return route.fulfill({json:Array.from({length:240}, (_,i) => ({s:'BTC',i:body.req.interval,
        t:end-(240-i)*ms,T:end-(239-i)*ms-1,o:'100',c:'100',h:'100.1',l:'99.9',v:'1000'}))});
    });
    await ready(page, base + 'futures.html', '[data-indicator="단기 선물 진입"]');
    await fits(page, '.vi-gauge');
    assert.equal(await page.locator('[data-indicator="단기 선물 진입"]').getAttribute('data-state'), 'neutral');
    await page.locator('[data-indicator="단기 선물 진입"]').screenshot({path:path.join(output,'futures-wait.png')});
    failed = true;
    await page.locator('#refresh').click();
    await page.locator('[data-indicator="단기 선물 진입"].vi-unknown').waitFor();
    assert.equal(await page.locator('[data-indicator="단기 선물 진입"] .vi-pointer').count(), 0);
    await page.locator('[data-indicator="단기 선물 진입"]').screenshot({path:path.join(output,'futures-unavailable.png')});
    assert.deepEqual(errors, [], 'No uncaught browser errors');
    console.log('Browser: 320/390/1280 px, four stock/spot pages, risk table, horizon switch and failed stock/exchange feeds passed.');
  } finally {await browser?.close(); await new Promise(resolve => server.close(resolve));}
})().catch(e => {console.error(e); process.exitCode = 1;});
