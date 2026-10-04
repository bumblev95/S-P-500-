'use strict';
const {chromium}=require('playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),{spawn}=require('node:child_process');
(async()=>{
  const server=spawn('python3',['-m','http.server','8765','--bind','127.0.0.1'],{stdio:'ignore'});
  let browser;
  try{
    for(let i=0;i<30;i++){try{await fetch('http://127.0.0.1:8765/index.html');break;}catch(_){await new Promise(r=>setTimeout(r,100));}}
    browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH||undefined});
    fs.mkdirSync('home-preview',{recursive:true});
    const data=JSON.parse(fs.readFileSync('market/home.json','utf8'));
    const now=Date.parse(data.rankings.evaluatedAt||data.generatedAt),asOf=data.rankings.asOf;
    const buy=['AAPL','MSFT','NVDA'].map(symbol=>({symbol,name:symbol,asOf,code:'breakout',holdingCode:'hold',selection:'relative'}));
    const sell=['AON','APP','CCI'].map(symbol=>({symbol,name:symbol,asOf,code:'avoid',holdingCode:'reduce',selection:'signal'}));
    const ranks={...data.rankings,buy,sell,marketGeneratedAt:new Date(now-3600000).toISOString()};
    const scenarios=[
      ['relative',ranks],
      ['one-signal',{...ranks,buy:[{...buy[0],code:'buy',selection:'signal'},buy[1],buy[2]]}],
      ['risk',{...ranks,buy:buy.map(q=>({...q,code:'avoid'}))}],
      ['stale-market',{...ranks,buy:buy.map(q=>({...q,code:'unavailable'})),marketGeneratedAt:new Date(now-4*86400000).toISOString()}],
      ['stale-prices',{...ranks,buy:buy.map(q=>({...q,asOf:'2026-09-20'})),sell:sell.map(q=>({...q,asOf:'2026-09-20'}))}],
      ['empty',{...ranks,buy:[],sell:[],waiting:buy}]
    ];
    for(const theme of ['light','dark']){
      const page=await browser.newPage({colorScheme:theme});
      await page.clock.install({time:new Date(now)});
      const errors=[];page.on('pageerror',e=>errors.push(e.message));
      await page.goto('http://127.0.0.1:8765/',{waitUntil:'networkidle'});
      await page.waitForSelector('[data-sector]');
      assert.equal(await page.locator('[data-sector]').count(),11);
      if(data.rankings.eligibleCount>=6){
        assert.equal(await page.locator('[data-home-buy] .hp-pick').count(),3);
        assert.equal(await page.locator('[data-home-sell] .hp-pick').count(),3);
      }
      assert.equal(await page.locator('.hp-entry-wait').count(),0);
      await page.locator('[data-sector]').first().click();
      assert.match(await page.locator('[data-sector-detail]').innerText(),/하루 .*이번 주/);
      for(const width of [320,375,768,1024,1440]){
        await page.setViewportSize({width,height:1000});
        assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1),theme+' overflow at '+width);
        const marks=await page.locator('.hp-sector-bar').evaluateAll(bars=>bars.map(bar=>{
          const a=bar.getBoundingClientRect(),p=bar.parentElement.getBoundingClientRect();
          return a.left>=p.left-.5&&a.right<=p.right+.5;
        }));
        assert(marks.every(Boolean),'bar outside lane');
        await page.screenshot({path:'home-preview/'+theme+'-'+width+'.png',fullPage:true});
      }
      for(const [name,rankings] of scenarios){
        await page.route('**/market/home.json?*',route=>route.fulfill({json:{...data,rankings}}));
        await page.goto('http://127.0.0.1:8765/',{waitUntil:'networkidle'});
        await page.waitForFunction(()=>document.querySelector('[data-home-status]').textContent.startsWith('갱신'));
        const picks=page.locator('[data-home-buy]'),sales=page.locator('[data-home-sell]');
        assert.equal(await page.locator('.hp-entry-wait').count(),0);
        assert(!(await page.locator('.hp-picks').innerText()).includes('진입 대기 후보'));
        if(['empty','stale-prices'].includes(name)){
          assert.equal(await picks.locator('.hp-pick').count(),0);
          assert.equal(await sales.locator('.hp-pick').count(),0);
          assert.equal(await picks.innerText(),'최신 순위 자료 확인 중');
        }else{
          assert.equal(await picks.locator('.hp-pick').count(),3,name+' keeps three buys');
          assert.equal(await sales.locator('.hp-pick').count(),3,name+' keeps three sells');
          assert.deepEqual(await picks.locator('.hp-rank').allTextContents(),['1','2','3']);
          assert.equal(await picks.locator('.hp-pick').first().getAttribute('href'),'stocks.html?symbol=AAPL');
          const labels=await picks.locator('.hp-pick-signal').allTextContents();
          assert.equal(labels.filter(label=>label==='조건 충족').length,name==='one-signal'?1:0);
          if(name==='risk')assert(labels.every(label=>label==='진입 보류'));
          if(name==='stale-market'){
            assert(labels.every(label=>label==='자료 확인'));
            assert((await page.locator('[data-home-ranking-note]').innerText()).includes('시장 자료 갱신 지연'));
          }
        }
        for(const width of [320,375,768,1024,1440]){
          await page.setViewportSize({width,height:1000});
          assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1),name+' '+theme+' overflow at '+width);
          const bounded=await picks.locator('.hp-pick-signal').evaluateAll(labels=>labels.every(el=>el.getBoundingClientRect().width<=el.parentElement.getBoundingClientRect().width));
          assert(bounded,'Status labels must fit each card');
          if(name==='one-signal')await page.screenshot({path:'home-preview/signals-'+theme+'-'+width+'.png',fullPage:true});
        }
        await page.unroute('**/market/home.json?*');
      }

      // Keep a tab open: a new daily rank arrives, an HTTP failure preserves it,
      // then the next refresh recovers without a manual reload.
      let value={...data,rankings:ranks},fail=false,requests=0;
      await page.route('**/market/home.json?*',route=>{
        requests++;return fail?route.fulfill({status:503,body:'Unavailable'}):route.fulfill({json:value});
      });
      await page.goto('http://127.0.0.1:8765/',{waitUntil:'networkidle'});
      await page.waitForFunction(()=>document.querySelector('[data-home-status]').textContent.startsWith('갱신'));
      const initialRequests=requests;
      value={...data,rankings:{...ranks,buy:[{...buy[0],symbol:'TSLA'},buy[1],buy[2]]}};
      await page.clock.fastForward(6*60000);
      await page.waitForFunction(()=>document.querySelector('[data-home-buy] .hp-name').textContent==='TSLA');
      assert(requests>initialRequests,'Visible page periodically re-fetches the snapshot');
      fail=true;await page.clock.fastForward(6*60000);
      await page.waitForSelector('[data-home-retry]');
      assert.equal(await page.locator('[data-home-buy] .hp-pick').count(),3,'Refresh failure keeps loaded rankings');
      assert((await page.locator('[data-home-status]').innerText()).includes('최근 저장 자료'));
      fail=false;value={...data,rankings:ranks};
      await page.clock.fastForward(6*60000);
      await page.waitForFunction(()=>document.querySelector('[data-home-buy] .hp-name').textContent==='AAPL');
      assert.equal(await page.locator('[data-home-retry]').count(),0,'Successful refresh clears the error');
      await page.unroute('**/market/home.json?*');
      assert.deepEqual(errors,[]);
      if(theme==='dark'){
        await page.goto('http://127.0.0.1:8765/?symbol=AAPL',{waitUntil:'networkidle'});
        await page.waitForURL('**/stocks.html?symbol=AAPL');
        await page.waitForFunction(()=>!document.getElementById('tickerInput').disabled);
        assert((await page.locator('#tickerInput').inputValue()).includes('AAPL'),'selected stock preserved');
        assert((await page.locator('#app').innerText()).includes('AAPL'));
      }
      await page.close();
    }
    console.log('Browser: daily three per side, honest status labels, no waiting section, refresh/failure/recovery, 320–1440px, themes, sector charts and stock links passed.');
  }finally{if(browser)await browser.close();server.kill();}
})().catch(e=>{console.error(e);process.exitCode=1;});
