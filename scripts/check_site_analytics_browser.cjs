'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {chromium} = require('playwright');
const root = path.join(__dirname, '..');
const ID = 'G-0C529GQ91Z';
const KEY = 'sp500.analytics.consent.v1';
const origin = 'https://bumblev95.github.io';
const base = origin + '/S-P-500-/';
const analyticsSource = fs.readFileSync(path.join(root, 'assets/site-analytics.js'), 'utf8');
const files = ['index.html','stocks.html','crypto.html','futures.html','simulation.html',
  'advanced.html','research.html','model-validation.html','signal-lab.html','leverage-lab.html',
  'exit-experiment.html','momentum-experiment.html','selector-experiment.html','privacy.html'];
for (const name of files) {
  const source = fs.readFileSync(path.join(root, name), 'utf8');
  assert.equal((source.match(/src="assets\/site-analytics\.js\?v=1"/g) || []).length, 1, name);
  for (const script of source.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g))
    new vm.Script(script[1], {filename: name});
}
const rootHomepage = fs.readFileSync(path.join(root, 'research/adsense-root-site/index.html'), 'utf8');
assert(rootHomepage.includes('<base href="' + base + '">'), 'root homepage uses shared project assets');
assert.equal((rootHomepage.match(/src="assets\/site-analytics\.js\?v=1"/g) || []).length, 1);
const fixture = `<!doctype html><html lang="ko"><head><meta charset="utf-8">
<base href="${base}">
<title>Analytics test</title><link rel="stylesheet" href="assets/site-analytics.css">
<script src="assets/site-analytics.js"></script></head><body><main>
<input id="search" value="PRIVATE SEARCH TEXT"><input id="entryPrice" value="98765">
<button data-h="252">1년</button><button data-mode="replay">과거 재현</button>
<nav><a id="root-home" href="${origin}/">메인</a><a id="project-stocks" href="stocks.html">주식</a></nav>
<span id="site-analytics-choice"></span>
<section id="home-news"><a href="https://news.example/article?secret=PRIVATE">뉴스</a></section>
</main></body></html>`;
async function commands(page) {
  return page.evaluate(() => (window.dataLayer || []).map(args => Array.from(args)));
}
async function events(page, name) {
  return (await commands(page)).filter(c => c[0] === 'event' && (!name || c[1] === name));
}
async function fixtureContext(browser, choice) {
  const context = await browser.newContext({viewport:{width:390,height:844}});
  const requests = [];
  if (choice) await context.addInitScript(({key,choice}) => localStorage.setItem(key,choice), {key:KEY,choice});
  await context.route('**/*', route => {
    const url = new URL(route.request().url());
    if (/google-analytics\.com$|googletagmanager\.com$/.test(url.hostname)) {
      requests.push(url.href);
      return route.fulfill({contentType:'application/javascript',body:'window.__analyticsMockLoaded=true;'});
    }
    if (url.pathname.endsWith('/assets/site-analytics.js'))
      return route.fulfill({contentType:'application/javascript',body:analyticsSource});
    if (url.pathname.endsWith('/assets/site-analytics.css'))
      return route.fulfill({contentType:'text/css',body:fs.readFileSync(path.join(root,'assets/site-analytics.css'),'utf8')});
    return route.fulfill({contentType:'text/html',body:fixture});
  });
  return {context,requests};
}
async function regressionMatrix(browser) {
  const locations = [
    {url:origin+'/',canonical:origin+'/',cookiePath:'/'},
    {url:origin+'/index.html',canonical:origin+'/',cookiePath:'/'},
    {url:base,canonical:base,cookiePath:'/S-P-500-/'},
    ...files.map(file => ({url:base+file,canonical:file==='index.html'?base:base+file,cookiePath:'/S-P-500-/'}))
  ];
  for (const location of locations) {
    const {context,requests} = await fixtureContext(browser);
    try {
      const page = await context.newPage();
      await page.goto(location.url+'?secret=PRIVATE#PRIVATE');
      await page.evaluate(() => {
        window.__firstAnalytics = SiteAnalytics;
        SiteAnalytics.viewAsset('stock','AAPL');
        SiteAnalytics.searchSelected('AAPL');
        SiteAnalytics.feature('horizon','252');
      });
      await page.addScriptTag({content:analyticsSource});
      assert.equal(await page.evaluate(() => SiteAnalytics===window.__firstAnalytics),true,'duplicate script preserves singleton');
      assert.equal(await page.locator('.site-analytics-consent').count(),1,location.url+' has one consent UI');
      assert.equal(await page.locator('.site-analytics-footer').count(),1);
      assert.equal(requests.length,0,'no Google requests before consent: '+location.url);
      assert.equal((await commands(page)).length,0,'no unconsented command backlog');
      const box = await page.locator('.site-analytics-consent').boundingBox();
      assert(box && box.x>=0 && box.x+box.width<=390 && box.y>=0 && box.y+box.height<=844,'mobile banner fits '+location.url);
      await page.locator('[data-analytics-choice="denied"]').click();
      await page.evaluate(() => SiteAnalytics.searchSelected('MSFT'));
      assert.equal(requests.length,0,'initial rejection keeps Google unloaded');
      assert.equal((await commands(page)).length,0);
      await page.locator('.site-analytics-footer button').click();
      await page.locator('[data-analytics-choice="granted"]').click();
      await page.waitForFunction(() => window.__analyticsMockLoaded===true);
      await page.addScriptTag({content:analyticsSource});
      await page.evaluate(() => {SiteAnalytics.setConsent('granted');SiteAnalytics.setConsent('granted');});
      const config = (await commands(page)).filter(c=>c[0]==='config');
      assert.equal(config.length,1,'one config/initial page_view per document');
      assert.equal(config[0][1],ID);
      assert.equal(config[0][2].page_location,location.canonical,'canonical comes from location, not base tag');
      assert.equal(config[0][2].cookie_path,location.cookiePath);
      assert.equal(config[0][2].cookie_domain,'none');
      assert.equal(config[0][2].cookie_flags,'SameSite=Lax;Secure');
      assert.equal((await events(page,'page_view')).length,0,'no duplicate manual page_view');
      assert.equal(await page.locator('script[data-site-analytics="ga4"]').count(),1);
      assert.equal(requests.length,1,'one Google tag initialization');
      assert.equal((await events(page,'stock_view')).length,1,'current asset counted once after consent');
      await page.evaluate(() => {
        for (const id of ['root-home','project-stocks']) {
          const link=document.getElementById(id);
          link.addEventListener('click',event=>event.preventDefault(),{once:true});
          link.click();
        }
      });
      assert.deepEqual((await events(page,'nav_click')).map(c=>c[2].destination),['메인','주식']);
      for (const event of await events(page)) assert.equal(event[2].page_location,location.canonical);
      assert(!JSON.stringify(await commands(page)).includes('PRIVATE'),'query and hash excluded');
      const names=['_ga','_ga_'+ID.slice(2)];
      await context.addCookies(['/', '/S-P-500-/'].flatMap(cookiePath=>names.map(name=>
        ({name,value:'test',domain:'bumblev95.github.io',path:cookiePath,secure:true,sameSite:'Lax'}))));
      await context.addCookies([{name:'unrelated',value:'keep',domain:'bumblev95.github.io',path:'/',secure:true}]);
      const before=(await events(page)).length;
      await page.evaluate(() => SiteAnalytics.setConsent('denied'));
      await page.addScriptTag({content:analyticsSource});
      await page.evaluate(() => {SiteAnalytics.viewAsset('stock','MSFT');SiteAnalytics.feature('horizon','252');});
      assert.equal((await events(page)).length,before,'revocation blocks events');
      assert.equal(await page.evaluate(id=>window['ga-disable-'+id],ID),true);
      const cookies=await context.cookies();
      assert.equal(cookies.filter(c=>names.includes(c.name)).length,0,'revocation clears both consent-shared cookie paths');
      assert(cookies.some(c=>c.name==='unrelated'),'unrelated cookies preserved');
      await page.reload();
      assert.equal(requests.length,1,'saved rejection blocks tag');
      assert.equal((await commands(page)).length,0);
      await page.locator('.site-analytics-footer button').click();
      await page.locator('[data-analytics-choice="granted"]').click();
      await page.waitForFunction(() => window.__analyticsMockLoaded===true);
      await page.reload();
      await page.waitForFunction(() => window.__analyticsMockLoaded===true);
      assert.equal((await commands(page)).filter(c=>c[0]==='config').length,1,'saved grant initializes once');
      const requestCount=requests.length;
      await page.goto(location.url+'?analytics=off&secret=PRIVATE');
      await page.evaluate(({key}) => {
        SiteAnalytics.setConsent('granted');
        window.dispatchEvent(new StorageEvent('storage',{key,newValue:'granted'}));
        SiteAnalytics.viewAsset('stock','NVDA');
      },{key:KEY});
      await page.locator('.site-analytics-footer button').click();
      await page.locator('[data-analytics-choice="granted"]').click();
      assert.equal(requests.length,requestCount,'analytics=off cannot be overridden');
      assert.equal((await commands(page)).length,0);
      assert.equal(await page.evaluate(key=>localStorage.getItem(key),KEY),'denied');
      assert.equal(await page.locator('#site-analytics-choice').textContent(),'방문 통계 거부 중');
      await page.goto(location.url+'?analytics=on&analytics=off');
      await page.evaluate(() => SiteAnalytics.setConsent('granted'));
      assert.equal(requests.length,requestCount,'any analytics=off query value excludes analytics');
      assert.equal((await commands(page)).length,0);
    } finally {await context.close();}
  }
  const {context,requests} = await fixtureContext(browser);
  try {
    const home=await context.newPage(), stocks=await context.newPage();
    await home.goto(origin+'/'); await stocks.goto(base+'stocks.html');
    await home.evaluate(() => SiteAnalytics.setConsent('granted'));
    await stocks.waitForFunction(() => (window.dataLayer||[]).some(c=>c[0]==='config'));
    assert.equal((await commands(stocks)).filter(c=>c[0]==='config').length,1,'root consent shared with project tab');
    await stocks.evaluate(() => SiteAnalytics.setConsent('denied'));
    await home.waitForFunction(id => window['ga-disable-'+id]===true,ID);
    const count=requests.length;
    await home.reload(); await stocks.reload();
    assert.equal(requests.length,count,'cross-tab rejection persists on both paths');
  } finally {await context.close();}
  for (const url of [origin+'/stocks.html',origin+'/another-project/stocks.html',base+'advanced-legacy.html',
    'https://localhost/S-P-500-/stocks.html','https://bumblev95.github.io.example/S-P-500-/stocks.html',
    origin+'/?symbol=AAPL',base+'?symbol=AAPL']) {
    const {context,requests}=await fixtureContext(browser,'granted');
    try {
      const page=await context.newPage(); await page.goto(url);
      assert.equal(await page.locator('.site-analytics-consent').count(),0,'ineligible or redirect page: '+url);
      assert.equal((await commands(page)).length,0);
      assert.equal(requests.length,0);
    } finally {await context.close();}
  }
  console.log('PASS: root / and /index.html, project homepage and all 14 pages, canonical URLs/cookie paths, duplicate initialization, consent/revocation, cross-tab choices and immutable analytics=off');
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
    await regressionMatrix(browser);
    console.log('PASS: 14 pages, consent lifecycle, no private inputs, owner exclusion, event deduplication and mobile layout');
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1;});
