// Optional real-browser regression: npm install --no-save playwright
// PLAYWRIGHT_MODULE/BROWSER_BIN can point to an already installed QA runtime.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const A = require('../assets/stock-assessment.js');
const root = path.resolve(__dirname, '..');
const output = process.env.INDICATOR_SCREENSHOTS || '/tmp/sp500-indicator-qa';
const read = file => JSON.parse(fs.readFileSync(path.join(root, file)));
const market = read('market/latest.json'), forecasts = read('forecasts/latest.json');
const events = read('events/latest.json'), news = read('news/latest.json');
const clock = Math.max(...[market,events,news].map(x => Date.parse(x.generatedAt))) + 1000;
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
      for (const [file,selector] of [['stocks.html','.stockAssessment'],['advanced.html','.stockAssessment'],
        ['advanced-legacy.html','.stockAssessment'],['crypto.html','[data-indicator="신규 진입 판단"]']]) {
        await ready(page, base + file, selector);
        await fits(page, '.vi-gauge');
        if (file !== 'crypto.html') {
          const assessment = page.locator('.stockAssessment').first();
          const expected = A.evaluate(forecasts.stocks.NVDA, market, null, 126, clock);
          if(file==='stocks.html'){
            const headline=await assessment.locator('.sa-heading').boundingBox(),controls=await page.locator('.controlBar').boundingBox();
            assert(headline.y>=controls.y+controls.height,'The final decision must be clear of the controls on initial load');
            await page.screenshot({path:path.join(output,`initial-index-${width}.png`)});
          }
          assert.equal(await assessment.locator('.vi-gauge:visible').count(), 1,
            'The entry category is visual; the numeric trend gauge stays in details');
          assert.equal(await assessment.locator('.sa-setup:visible').count(),0,
            'Detailed strategies start collapsed for beginners');
          assert.equal(await assessment.locator('.sa-state-card > summary:visible').count(),9,
            'All possible entry states are discoverable without opening a disclosure');
          assert.equal(await assessment.locator('.sa-state-map [aria-current="true"]').count(),1);
          assert.equal(await assessment.locator('.sa-state-current').getAttribute('data-state-option'),expected.plan.code);
          assert.equal(await assessment.locator('[data-entry-state]').textContent(),expected.decision);
          assert.equal(await assessment.locator('[data-holding-state]').getAttribute('data-holding-state'),expected.plan.holding.code);
          assert.equal(await assessment.locator('.sa-holding .vi-steps > span:visible').count(),3);
          const holdingActive=assessment.locator('.sa-holding .vi-steps .vi-active');
          assert.equal(await holdingActive.count(),expected.plan.holding.code==='unavailable'?0:1);
          if(expected.plan.holding.code!=='unavailable')assert.equal(await holdingActive.evaluate(n=>getComputedStyle(n).color),
            {good:'rgb(110, 231, 183)',warn:'rgb(249, 207, 107)',bad:'rgb(255, 127, 145)'}[expected.plan.holding.tone],
            'The selected holding response must be visually distinct');
          for(const state of A.entryStates){
            const option=assessment.locator('[data-state-option="'+state.key+'"]');
            await option.locator('summary').click();
            assert.equal(await option.locator('p:visible').count(),1);
            assert.equal(await assessment.locator('.sa-state-card[open]').count(),1);
            assert.equal(await assessment.locator('[data-entry-state]').textContent(),expected.decision,
              'Exploring a state meaning cannot change the actual judgment');
            await fits(page,'.sa-state-card, .sa-state-card summary, .sa-state-card p');
          }
          await assessment.locator('.sa-state-card[open] > summary').click();
          assert.equal(await assessment.locator('.sa-checks li:visible').count(), 0);
          await assessment.locator('.sa-condition-details > summary').click();
          assert.equal(await assessment.locator('.sa-setup:visible').count(),2);
          assert.equal(await assessment.locator('.sa-checks li:visible').count(), 5);
          assert.equal(await assessment.locator('.sa-ai-status:visible').count(), 1);
          assert.equal(await assessment.locator('.sa-conditions [data-ai-reference]').count(), 0,
            'AI research is outside the technical condition checklist');
          const detail = assessment.locator('.sa-trend-details');
          assert.equal(await detail.evaluate(n => n.open), false);
          assert((await detail.locator('summary').textContent()).includes(A.format(expected.score)));
          if (expected.score !== null && Number.isFinite(expected.plan.rr)) {
            assert((await assessment.locator('[data-entry-check="balance"] p').textContent())
              .includes(expected.plan.rr.toFixed(2)), 'Show the actual entry-plan reward/risk ratio');
          }
          await fits(page, '.stockAssessment, .sa-decision-visual, .sa-state-map, .sa-price-strip, .sa-context, .sa-next, .sa-setup-grid, .sa-setup, .sa-setup dl, .sa-holding, .sa-entry-layout, .sa-conditions, .sa-checks, .sa-checks li');
          await detail.locator('summary').click();
          assert.equal(await assessment.locator('.vi-gauge:visible').count(), 2);
          assert((await detail.textContent()).includes('매수 추천'));
          await fits(page, '.vi-gauge, .sa-trend-details');
          await detail.locator('summary').click();
          await assessment.locator('.sa-condition-details > summary').click();
        }
        if (file === 'advanced.html') {
          await page.locator('details.site-disclosure > summary').click();
          const badge = page.locator('#sourceStatus .vi-badge');
          assert.equal(await badge.evaluate(n => getComputedStyle(n).display), 'inline-flex');
          const css = await badge.evaluate(n => ({classes:n.className,color:getComputedStyle(n).color}));
          const palette = {good:'rgb(110, 231, 183)',warn:'rgb(249, 207, 107)',
            bad:'rgb(255, 127, 145)',muted:'rgb(166, 184, 203)'};
          assert.equal(css.color, palette[css.classes.match(/\bvi-(good|warn|bad|muted)\b/)[1]]);
          const coverage = await page.locator('#sourceStatus').innerText();
          assert(coverage.includes(`${market.credit.coverage} / 4개 신용 묶음`), JSON.stringify(coverage));
          for (const label of market.credit.missingFamilies) assert(coverage.includes(label));
          assert(!coverage.includes(`${market.credit.coverage}개 지표`), 'Credit coverage counts families');
          await fits(page, '#sourceStatus > div');
          await page.locator('#sourceStatus').screenshot({path:path.join(output, `credit-coverage-${width}.png`)});
        }
        if (file !== 'crypto.html') {
          await page.locator('.company-events .ce-news-card').first().waitFor();
          const newsTitles=await page.locator('.ce-news-title').allTextContents();
          assert(newsTitles.every(t=>/[가-힣]{2}/.test(t)), 'News opens with Korean summaries');
          assert(!newsTitles.some(t=>/한국어 요약을 준비하지/.test(t)), 'Selected stock summaries are available');
          await page.locator('.ce-filings > summary').click();
          await page.locator('.company-events .ce-event').first().waitFor();
          assert.equal(await page.locator('.company-events').getAttribute('data-event-symbol'), 'NVDA');
          assert.equal(await page.locator('.sa-signals .signal[open]').count(),0,
            'Price signals start with concise titles');
          const priceSignal=page.locator('.sa-signals details.signal').first();
          if(await priceSignal.count()){
            await priceSignal.locator('summary').click();
            assert.equal(await priceSignal.locator('.sa-signal-detail:visible').count(),1);
            await fits(page,'.sa-signal-detail');
            await priceSignal.locator('summary').click();
          }
          await page.locator('.company-events .ce-event').first().locator('summary').click();
          await page.locator('.ce-news-detail > summary').first().click();
          await fits(page, '.company-events, .ce-news-card, .ce-news-title, .ce-news-reason, .ce-news-counts, .ce-event, .ce-event summary, .ce-body');
          assert.equal(await page.locator('.ce-news-card').count(), news.issuers[news.symbols.NVDA].articles.length);
          await page.locator('.company-events').screenshot({path:path.join(output, `events-${file.replace('.html','')}-${width}.png`)});
          assert.equal(await page.locator('#tradePlanner, .ds-planner').count(), 0);
        }
        const gauge = page.locator(selector).first();
        await gauge.screenshot({path:path.join(output, `${file.replace('.html','')}-${width}.png`)});
        if (file === 'stocks.html') {
          const risk = page.locator('#sharedRisk');
          await risk.locator('details').first().evaluate(n => n.open = true);
          await fits(page, '.ds-risk-overview, .ds-risk-table');
          await risk.screenshot({path:path.join(output, `risk-${width}.png`)});
          await page.getByRole('button', {name:'1년',exact:true}).click();
          assert.equal(await page.locator('.stockAssessment .vi-gauge').count(), 2);
          assert.equal(await page.locator('.stockAssessment .vi-gauge:visible').count(), 1);
          assert((await page.locator('.sa-ai-status h3').textContent()).includes('1년'));
          await page.locator('#tickerInput').fill('XOM');
          await page.locator('#tickerInput').press('Enter');
          await page.locator('.company-events[data-event-symbol="XOM"]').waitFor();
          assert.equal(await page.locator('.company-events[data-event-symbol="NVDA"]').count(), 0);
          await page.locator('.company-events .ce-news-card').first().waitFor();
          await page.locator('.ce-filings > summary').click();
          await page.locator('.company-events .ce-event').first().waitFor();
          assert.equal(await page.locator('.ce-news-card').count(), news.issuers[news.symbols.XOM].articles.length);
          const primary=page.locator('.ce-primary-news .ce-news-card');
          assert(await primary.count()>0);
          assert((await primary.locator('.ce-news-reason').allTextContents()).every(t=>t.includes('왜 ')));
          assert((await primary.locator('.ce-news-title').allTextContents()).every(t=>/[가-힣]{2}/.test(t)));
          // The reported turnaround stays favorable on the actual page; shared
          // warnings cannot hide issuer-specific price risks after a switch.
          await page.getByRole('button', {name:'6개월',exact:true}).click();
          await page.locator('#tickerInput').fill('AMD');
          await page.locator('#tickerInput').press('Enter');
          await page.locator('.company-events[data-event-symbol="AMD"] .ce-news-card').first().waitFor();
          const amdHistory=page.locator('.ce-primary-news .ce-news-card').filter({hasText:'회복·성장 성과'});
          if(news.issuers[news.symbols.AMD].articles.some(a=>a.id==='news:f602f5defbad7eb740fda350')){
            assert(await amdHistory.count()>=1);
            assert((await amdHistory.locator('.ce-impact').allTextContents()).every(x=>x==='호재'));
            assert((await amdHistory.locator('.ce-news-title').allTextContents()).some(x=>x.includes('시가총액 1조 달러')));
          }
          assert(!(await page.locator('.sa-specific-risks').textContent()).includes('시장 상태 확인 보류'));
          assert(!(await page.locator('.sa-specific-risks').textContent()).includes('AI 예측 활용 보류'));
          const amdRiskIds=await page.locator('.sa-specific-risks [data-signal]').evaluateAll(nodes=>nodes.map(n=>n.dataset.signal));
          await fits(page,'.sa-signals, .sa-specific-risks, .sa-limitations, .sa-signal-copy');
          await page.locator('.sa-signals').screenshot({path:path.join(output,`issuer-risks-amd-${width}.png`)});
          await page.locator('#tickerInput').fill('JNJ');
          await page.locator('#tickerInput').press('Enter');
          await page.locator('[data-signals-symbol="JNJ"]').waitFor();
          if((forecasts.stocks.AMD.inputs.return1m<0)!==(forecasts.stocks.JNJ.inputs.return1m<0))
            assert.notDeepEqual(await page.locator('.sa-specific-risks [data-signal]').evaluateAll(nodes=>nodes.map(n=>n.dataset.signal)),amdRiskIds,
              'Opposite monthly returns must produce different technical risks');
          if(forecasts.stocks.JNJ.inputs.return1m<0)assert((await page.locator('.sa-specific-risks').textContent()).includes('1개월 수익률'));
          await fits(page,'.sa-signals, .sa-specific-risks, .sa-limitations, .sa-signal-copy');
        }
      }
      await page.close();
    }
    // Credit stability and completeness are separate on the actual screener.
    // Legacy 3/3 metadata cannot be presented as complete four-family coverage.
    const coveragePage = await browser.newPage({viewport:{width:390,height:900}});
    coveragePage.on('pageerror', e => errors.push(e.message));
    await coveragePage.addInitScript(now => {
      const OriginalDate = Date;
      window.Date = class extends OriginalDate {
        constructor(...args) {super(...(args.length ? args : [now]));}
        static now() {return now;}
      };
    }, clock);
    let creditFixture;
    await coveragePage.route('**/market/latest.json*', route =>
      route.fulfill({json:{...market,credit:creditFixture}}));
    for (const [credit,text,missing,badge] of [
      [{status:'stable',coverage:3,expected:4,complete:false,missingFamilies:['회사채 GZ/EBP']},
        '3 / 4개 신용 묶음','회사채 GZ/EBP','관측 범위 내 안정'],
      [{status:'stable',coverage:4,expected:4,complete:true,missingFamilies:[]},
        '4 / 4개 신용 묶음',null,'관측 범위 내 안정'],
      [{status:'unknown',coverage:0,expected:4,complete:false,
        missingFamilies:['금융여건','단기자금조달','은행대출','회사채 GZ/EBP']},
        '0 / 4개 신용 묶음','은행대출','자료 확인 필요'],
      [{status:'stable',coverage:3,expected:3},'신용 묶음 범위 확인 필요',null,'관측 범위 내 안정'],
      [{status:'unknown',expected:4},'신용 묶음 범위 확인 필요',null,'자료 확인 필요']
    ]) {
      creditFixture=credit;
      await ready(coveragePage, base+'advanced.html', '.stockAssessment');
      await coveragePage.locator('details.site-disclosure > summary').click();
      const info=await coveragePage.locator('#sourceStatus').innerText();
      assert(info.includes(text));
      assert(!/3\s*\/\s*3|undefined|NaN/.test(info));
      assert.equal(await coveragePage.locator('#sourceStatus .vi-badge').innerText(),badge);
      if (missing) assert(info.includes('미사용:') && info.includes(missing));
      else assert(!info.includes('미사용:'));
      await fits(coveragePage,'#sourceStatus > div');
    }
    await coveragePage.close();
    // Deterministic price states share the same failed market/AI gates. Verify
    // actual risk rows survive stock switches and a missing forecast horizon.
    const riskPage=await browser.newPage({viewport:{width:390,height:900}});
    riskPage.on('pageerror',e=>errors.push(e.message));
    await riskPage.addInitScript(now=>{
      const OriginalDate=Date;
      window.Date=class extends OriginalDate {
        constructor(...args){super(...(args.length?args:[now]));}
        static now(){return now;}
      };
    },clock);
    const day=new Date(clock).toISOString().slice(0,10),end=Date.parse(day);
    const history=Array.from({length:80},(_,i)=>({date:new Date(end-(79-i)*86400000).toISOString().slice(0,10),
      close:i===79?100:[100,110,100,90,100][i%5]}));
    const entry={status:'ready',fresh:true,asOf:day,price:100,history,
      predictions:{126:{...forecasts.stocks.NVDA.predictions[126],anchor:100,base:110,bear:90,bull:120}}};
    const fixtures={...forecasts,stocks:{
      NVDA:{...entry,symbol:'NVDA',inputs:{ma20:100,ma50:105,ma200:110,return1m:-.07,return3m:-.12,volatility4m:.75}},
      XOM:{...entry,symbol:'XOM',history:history.map((q,i)=>({...q,close:60+40*i/79})),
        inputs:{ma20:97,ma50:90,ma200:80,return1m:.25,return3m:.35,volatility4m:.75}}
    }};
    await riskPage.route('**/config/*.json*',route=>route.fulfill({json:{sheetCsvUrl:'',submitUrl:''}}));
    await riskPage.route('**/forecasts/latest.json*',route=>route.fulfill({json:fixtures}));
    await riskPage.route('**/market/latest.json*',route=>route.fulfill({json:null}));
    await riskPage.route('**/ml/latest.json*',route=>route.fulfill({json:null}));
    await ready(riskPage,base+'stocks.html','.sa-specific-risks');
    const ids=()=>riskPage.locator('.sa-specific-risks [data-signal]').evaluateAll(nodes=>nodes.map(n=>n.dataset.signal));
    const weakIds=await ids();
    for(const id of ['ma50','ma-order','return1m','return3m','volatility'])assert(weakIds.includes(id));
    assert(weakIds.length>=5,'Common gates must not consume the first four price-risk slots');
    assert.equal(await riskPage.locator('.sa-specific-risks [data-signal="weak-trend"]').count(),0);
    for(const id of ['market-data','ai-validation','weak-trend'])assert.equal(await riskPage.locator('.sa-limitations [data-signal="'+id+'"]').count(),1);
    await fits(riskPage,'.sa-signals, .sa-specific-risks, .sa-limitations, .sa-signal-copy');
    await riskPage.locator('.sa-signals').screenshot({path:path.join(output,'risk-weak-fixture.png')});
    await riskPage.locator('#tickerInput').fill('XOM');
    await riskPage.locator('#tickerInput').press('Enter');
    await riskPage.locator('[data-signals-symbol="XOM"]').waitFor();
    const hotIds=await ids();
    assert.notDeepEqual(hotIds,weakIds);
    assert(hotIds.includes('overheated'));
    assert(!hotIds.includes('ma50'));
    for(const id of ['market-data','ai-validation'])assert.equal(await riskPage.locator('.sa-limitations [data-signal="'+id+'"]').count(),1);
    await fits(riskPage,'.sa-signals, .sa-specific-risks, .sa-limitations, .sa-signal-copy');
    await riskPage.locator('.sa-signals').screenshot({path:path.join(output,'risk-hot-fixture.png')});
    await riskPage.getByRole('button',{name:'1년',exact:true}).click();
    await riskPage.locator('.guide').filter({hasText:'선택 기간의 전망 자료가 부족'}).waitFor();
    assert.deepEqual(await ids(),hotIds,'Missing forecast must preserve observed price risks');
    assert((await riskPage.locator('.sa-limitations [data-signal="ai-validation"]').textContent()).includes('1년'));
    // Complete rule-based conditions with a genuinely withheld AI record.
    // This is isolated QA data; published market/forecast files are untouched.
    const f={anchor:100,base:110,bear:90,bull:120,direction:'up',learned:true,
      logReturn:Math.log(1.1),lowLogReturn:Math.log(.9),highLogReturn:Math.log(1.2)};
    const readyHistory=Array.from({length:260},(_,i)=>({date:new Date(end-(259-i)*86400000).toISOString().slice(0,10),close:i===259?100:90+i*.036+Math.sin(i*.3)*.25,volume:1000}));
    const readyEntry={...entry,symbol:'NVDA',history:readyHistory,
      inputs:{ma20:100,ma50:95,ma200:90,return1m:.04,return3m:.12,volatility4m:.2},
      predictions:{126:{...f,horizon:126},252:{...f,horizon:252}}};
    const readyMarket={generatedAt:new Date(clock).toISOString(),
      credit:{status:'stable',coverage:4,expected:4,complete:true,missingFamilies:[]},
      indicators:['NFCI','STLFSI4','DRTSCILM','FUNDING','GZ_SPREAD','EBP'].map(id=>({
        id,label:id,unit:'',url:'',status:'ready',asOf:day,maxAgeDays:5,value:0,severity:0}))};
    const research={status:'trained',generatedAt:new Date(clock).toISOString(),
      validation:{126:{passed:false},252:{passed:false}},stocks:{NVDA:{asOf:day,price:100,
      predictions:Object.fromEntries([126,252].map(h=>[h,{status:'withheld',forecast:{...f,horizon:h},
        reasons:['시험용 AI 검증 미통과']}]))}}};
    await riskPage.unrouteAll();
    await riskPage.route('**/config/*.json*',route=>route.fulfill({json:{sheetCsvUrl:'',submitUrl:''}}));
    await riskPage.route('**/forecasts/latest.json*',route=>route.fulfill({json:{stocks:{NVDA:readyEntry}}}));
    await riskPage.route('**/market/latest.json*',route=>route.fulfill({json:readyMarket}));
    await riskPage.route('**/ml/latest.json*',route=>route.fulfill({json:research}));
    await ready(riskPage,base+'stocks.html','.stockAssessment');
    assert.equal(await riskPage.locator('.stockAssessment [data-entry-state]').textContent(),'진입 검토');
    assert.equal(await riskPage.locator('.stockAssessment').getAttribute('data-decision-basis'),'technical-rules');
    assert.equal(await riskPage.locator('.sa-ai-status').getAttribute('data-ai-reference'),'unavailable');
    assert((await riskPage.locator('.sa-ai-status .vi-badge').textContent()).includes('검증 미통과'));
    assert.equal(await riskPage.locator('[data-entry-state]').getAttribute('data-entry-state'),'buy');
    assert.equal(await riskPage.locator('[data-setup="breakout"]').getAttribute('data-setup-state'),'ready');
    await riskPage.getByRole('button',{name:'1년',exact:true}).click();
    assert.equal(await riskPage.locator('.stockAssessment [data-entry-state]').textContent(),'진입 검토');
    assert((await riskPage.locator('.sa-ai-status h3').textContent()).includes('1년'));
    await fits(riskPage,'.stockAssessment, .sa-checks, .sa-ai-status');
    await riskPage.locator('.stockAssessment').screenshot({path:path.join(output,'entry-ready-withheld-ai-fixture.png')});
    await riskPage.close();
    // Failed/stale feeds get grey indicators without a pointer on the real page.
    const page = await browser.newPage({viewport:{width:390,height:900}});
    page.on('pageerror', e => errors.push(e.message));
    await page.route('**/forecasts/latest.json*', route => route.fulfill({json:{stocks:{
      NVDA:{...forecasts.stocks.NVDA, fresh:false}
    }}}));
    await page.route('**/market/latest.json*', route => route.fulfill({json:null}));
    await ready(page, base + 'stocks.html', '.stockAssessment');
    assert.equal(await page.locator('.stockAssessment .vi-unknown:visible').count(), 1);
    assert.equal(await page.locator('[data-entry-state]').getAttribute('data-entry-state'),'unavailable');
    assert.equal(await page.locator('[data-setup-state="unavailable"]').count(),2);
    assert.equal(await page.locator('.stockAssessment .vi-pointer').count(), 0);
    for (const key of ['trend','price','balance','heat']) {
      assert.equal(await page.locator(`[data-entry-check="${key}"] .vi-badge.vi-muted`).count(), 1,
        'Unavailable price data must not receive a passing entry badge');
    }
    await page.locator('#sharedRisk .vi-unknown').waitFor();
    assert.equal(await page.locator('#sharedRisk .vi-pointer').count(), 0);
    await page.locator('.stockAssessment').screenshot({path:path.join(output,'stock-unavailable.png')});
    // Fixture responses exercise the exchange page only; no market files change.
    let failed = false;
    await page.unrouteAll();
    await page.route('**/events/latest.json*', route => route.fulfill({status:503, json:{error:'QA unavailable'}}));
    await ready(page, base + 'stocks.html', '.company-events');
    await page.locator('.ce-news-card').first().waitFor();
    await page.locator('.ce-filings > summary').click();
    await page.locator('.ce-status').filter({hasText:'자료 읽기 실패'}).waitFor();
    assert.equal(await page.locator('.company-events .ce-event').count(), 0);
    await page.locator('.company-events').screenshot({path:path.join(output,'events-unavailable.png')});
    await page.unroute('**/events/latest.json*');
    await page.route('**/news/latest.json*', route => route.fulfill({status:503,json:{error:'QA unavailable'}}));
    await ready(page, base + 'stocks.html', '.company-events');
    await page.locator('.ce-news-status').filter({hasText:'뉴스 읽기 실패'}).waitFor();
    assert.equal(await page.locator('.ce-news-card').count(), 0);
    await page.locator('.ce-filings > summary').click();
    await page.locator('.ce-event').first().waitFor();
    await page.unroute('**/news/latest.json*');
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
    console.log('Browser: 320/390/1280 px, four stock/spot pages, company news, distinct weak/overheated risks, shared entry states, missing forecast horizon, stock/horizon switches, failed feeds and risk table passed.');
  } finally {await browser?.close(); await new Promise(resolve => server.close(resolve));}
})().catch(e => {console.error(e); process.exitCode = 1;});
