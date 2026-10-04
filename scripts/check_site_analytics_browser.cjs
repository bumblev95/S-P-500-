'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {chromium} = require('playwright');
const root = path.join(__dirname, '..');
const ID = 'G-0C529GQ91Z';
const origin = 'https://bumblev95.github.io';
const base = origin + '/S-P-500-/';
const files = ['index.html','stocks.html','crypto.html','futures.html','simulation.html',
  'advanced.html','research.html','model-validation.html','signal-lab.html','leverage-lab.html',
  'exit-experiment.html','momentum-experiment.html','selector-experiment.html','privacy.html'];
for (const name of files) {
  const source = fs.readFileSync(path.join(root, name), 'utf8');
  assert.equal((source.match(/src="assets\/site-analytics\.js\?v=1"/g) || []).length, 1, name);
  for (const script of source.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g))
    new vm.Script(script[1], {filename: name});
}
const fixture = `<!doctype html><html lang="ko"><head><meta charset="utf-8">
<title>Analytics test</title><link rel="stylesheet" href="assets/site-analytics.css">
<script src="assets/site-analytics.js"></script></head><body><main>
<input id="search" value="PRIVATE SEARCH TEXT"><input id="entryPrice" value="98765">
<button data-h="252">1년</button><button data-mode="replay">과거 재현</button>
<section id="home-news"><a href="https://news.example/article?secret=PRIVATE">뉴스</a></section>
</main></body></html>`;
async function commands(page) {
  return page.evaluate(() => (window.dataLayer || []).map(args => Array.from(args)));
}
async function events(page, name) {
  return (await commands(page)).filter(c => c[0] === 'event' && (!name || c[1] === name));
}
(async () => {
  const browser = await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || undefined});
  try {
    const context = await browser.newContext({viewport:{width:390,height:844}});
    let googleRequests = 0;
    await context.route('**/*', route => {
      const url = new URL(route.request().url());
      if (url.hostname === 'www.googletagmanager.com') {
        googleRequests++;
        return route.fulfill({contentType:'application/javascript',body:'window.__analyticsMockLoaded=true;'});
      }
      if (url.hostname !== 'bumblev95.github.io') return route.abort();
      if (url.pathname.endsWith('/assets/site-analytics.js') || url.pathname.endsWith('/assets/site-analytics.css')) {
        const file = path.join(root, 'assets', path.basename(url.pathname));
        return route.fulfill({contentType:file.endsWith('.js')?'application/javascript':'text/css',body:fs.readFileSync(file,'utf8')});
      }
      return route.fulfill({contentType:'text/html',body:fixture});
    });
    const page = await context.newPage();
    await page.goto(base + 'stocks.html?symbol=AAPL&secret=PRIVATE#PRIVATE');
    await page.evaluate(() => {SiteAnalytics.viewAsset('stock','AAPL');SiteAnalytics.searchSelected('AAPL');});
    assert.equal(googleRequests,0,'no analytics requests before consent');
    assert.equal((await commands(page)).length,0,'no backlog of unconsented events');
    const box = await page.locator('.site-analytics-consent').boundingBox();
    assert(box.x>=0 && box.x+box.width<=390 && box.y>=0 && box.y+box.height<=844,'mobile banner fits viewport');
    await page.locator('[data-analytics-choice="granted"]').click();
    await page.waitForFunction(() => window.__analyticsMockLoaded === true);
    const config = (await commands(page)).filter(c=>c[0]==='config');
    assert.equal(config.length,1,'one initial config/pageview');
    assert.equal(config[0][1],ID);
    assert.equal(config[0][2].page_location,base+'stocks.html');
    assert.equal(config[0][2].allow_google_signals,false);
    assert.equal((await events(page,'stock_view')).length,1,'current asset counted after consent');
    await page.evaluate(() => {
      SiteAnalytics.viewAsset('stock','AAPL');SiteAnalytics.viewAsset('stock','AAPL');
      SiteAnalytics.viewAsset('stock','MSFT');SiteAnalytics.searchSelected('MSFT');
      SiteAnalytics.viewAsset('stock','MSFT');SiteAnalytics.viewAsset('stock','AAPL');
      SiteAnalytics.viewAsset('stock','jack@example.com');
      SiteAnalytics.feature('horizon','PRIVATE');
    });
    assert.equal((await events(page,'stock_view')).length,3,'rerenders deduplicate, returning to a stock counts');
    assert.equal((await events(page,'search_result_select')).length,1,'no preconsent search replay');
    await page.locator('[data-h="252"]').click();
    assert.equal((await events(page,'feature_use')).at(-1)[2].choice,'252');
    await page.locator('[data-mode="replay"]').click();
    assert.equal((await events(page,'feature_use')).at(-1)[2].feature,'mode');
    assert(!JSON.stringify(await commands(page)).includes('PRIVATE'));
    assert(!JSON.stringify(await commands(page)).includes('98765'),'private trading fields not sent');
    await page.evaluate(() => {document.cookie='_ga=test; Path=/S-P-500-/; Secure';SiteAnalytics.setConsent('denied');});
    assert.equal(await page.evaluate(id=>window['ga-disable-'+id],ID),true);
    assert(!await page.evaluate(()=>document.cookie.includes('_ga=')),'analytics cookie removed after revocation');
    const before = (await events(page)).length;
    await page.evaluate(()=>{SiteAnalytics.viewAsset('stock','NVDA');SiteAnalytics.searchSelected('NVDA');});
    assert.equal((await events(page)).length,before,'no events after revocation');
    const requests = googleRequests;
    await page.goto(base+'crypto.html');
    assert.equal(googleRequests,requests,'saved rejection blocks next page tag');
    assert.equal((await commands(page)).length,0);
    await page.locator('.site-analytics-footer button').click();
    await page.locator('[data-analytics-choice="granted"]').click();
    await page.evaluate(()=>{SiteAnalytics.viewAsset('spot','BTC');SiteAnalytics.viewAsset('spot','BTC');});
    assert.equal((await events(page,'coin_view')).length,1);
    await page.goto(base+'futures.html');
    await page.evaluate(()=>SiteAnalytics.viewAsset('futures','ETH'));
    assert.equal((await commands(page)).filter(c=>c[0]==='config').length,1,'consent restored on new page');
    assert.equal((await events(page,'coin_view'))[0][2].asset_type,'futures');
    await page.goto(base+'stocks.html?analytics=off');
    assert.equal((await commands(page)).length,0,'owner exclusion works');
    await page.goto(origin+'/another-project/stocks.html');
    assert.equal(await page.locator('.site-analytics-consent').count(),0,'other projects excluded');
    await context.close();
    const deniedContext = await browser.newContext();
    await deniedContext.route('**/*', route => {
      const url=new URL(route.request().url());
      if(url.hostname==='www.googletagmanager.com')throw new Error('Google requested after reject');
      if(url.pathname.endsWith('site-analytics.js'))return route.fulfill({contentType:'application/javascript',body:fs.readFileSync(path.join(root,'assets/site-analytics.js'),'utf8')});
      if(url.pathname.endsWith('.css'))return route.fulfill({contentType:'text/css',body:''});
      return route.fulfill({contentType:'text/html',body:fixture});
    });
    const deniedPage=await deniedContext.newPage();
    await deniedPage.goto(base);
    await deniedPage.locator('[data-analytics-choice="denied"]').click();
    await deniedPage.locator('[data-h="252"]').click();
    assert.equal((await commands(deniedPage)).length,0,'reject keeps analytics unloaded');
    await deniedContext.close();
    console.log('PASS: 14 pages, consent lifecycle, no private inputs, owner exclusion, event deduplication and mobile layout');
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1;});
