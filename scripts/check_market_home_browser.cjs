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
    const now=Date.parse(data.rankings.evaluatedAt||data.generatedAt);
    const asOf=new Date(now-86400000).toISOString().slice(0,10);
    const waiting=[{symbol:'AAPL',name:'애플',asOf,code:'breakout'},{symbol:'MSFT',name:'마이크로소프트',asOf,code:'pullback'},{symbol:'NVDA',name:'엔비디아',asOf,code:'riskwait'}];
    const ranks={...data.rankings,buy:[],waiting,marketGeneratedAt:new Date(now-3600000).toISOString()};
    const scenarios=[
      ['waiting',ranks],
      ['buy',{...ranks,buy:[{symbol:'AAPL',name:'애플',asOf}]}],
      ['empty',{...ranks,waiting:[]}],
      ['stale',{...ranks,marketGeneratedAt:new Date(now-4*86400000).toISOString()}]
    ];
    for(const theme of ['light','dark']){
      const page=await browser.newPage({colorScheme:theme});
      await page.clock.setFixedTime(new Date(now));
      const errors=[];page.on('pageerror',e=>errors.push(e.message));
      await page.goto('http://127.0.0.1:8765/',{waitUntil:'networkidle'});
      await page.waitForSelector('[data-sector]');
      assert.equal(await page.locator('[data-sector]').count(),11);
      assert(await page.locator('.hp-pick').count()<=6);
      await page.locator('[data-sector]').first().click();
      assert.match(await page.locator('[data-sector-detail]').innerText(),/하루 .*이번 주/);
      for(const width of [320,375,768,1024,1440]){
        await page.setViewportSize({width,height:1000});
        assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1),theme+' overflow at '+width);
        const marks=await page.locator('.hp-sector-bar').evaluateAll(bars=>bars.map(bar=>{const a=bar.getBoundingClientRect(),p=bar.parentElement.getBoundingClientRect();return a.left>=p.left-.5&&a.right<=p.right+.5;}));
        assert(marks.every(Boolean),'bar outside lane');
        await page.screenshot({path:'home-preview/'+theme+'-'+width+'.png',fullPage:true});
      }
      for(const [name,rankings] of scenarios){
        await page.route('**/market/home.json?*',route=>route.fulfill({json:{...data,rankings}}));
        await page.goto('http://127.0.0.1:8765/',{waitUntil:'networkidle'});
        await page.waitForFunction(()=>document.querySelector('[data-home-status]').textContent.startsWith('갱신'));
        const buy=page.locator('[data-home-buy]');
        if(name==='waiting'){
          assert((await buy.innerText()).includes('현재 매수 후보 없음'));
          assert((await buy.innerText()).includes('매수 조건 충족 전'));
          assert.deepEqual(await buy.locator('.hp-wait-state').allTextContents(),['돌파 대기','눌림목 대기','위험 조절 대기']);
          assert.equal(await buy.locator('.hp-rank').count(),0);
          const pick=buy.locator('.hp-wait-pick').first();
          assert.equal(await pick.getAttribute('href'),'stocks.html?symbol=AAPL');
          const tones=await pick.evaluate(el=>({background:getComputedStyle(el).backgroundColor,expected:getComputedStyle(document.getElementById('market-home')).getPropertyValue('--hp-ambersurface').trim()}));
          const colorParts=value=>value.match(/[\d.]+/g).map(Number);
          assert.deepEqual(colorParts(tones.background),colorParts(tones.expected),'Waiting cards use amber instead of buy green');
        }else if(name==='buy'){
          assert.equal(await buy.locator('.hp-pick').count(),1,'Do not pad a single actual buy with waiting candidates');
          assert.equal(await buy.locator('.hp-rank').innerText(),'1');
          assert.equal(await buy.locator('.hp-entry-wait').count(),0);
        }else{
          assert.equal(await buy.locator('.hp-pick').count(),0);
          assert.equal(await buy.locator('.hp-entry-wait').count(),0);
          assert.equal(await buy.innerText(),name==='stale'?'시장 자료 갱신 대기':'현재 매수 후보 없음');
        }
        for(const width of [320,375,768,1024,1440]){
          await page.setViewportSize({width,height:1000});
          assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1),name+' '+theme+' overflow at '+width);
          if(name==='waiting'){
            const bounded=await buy.locator('.hp-wait-state').evaluateAll(labels=>labels.every(el=>el.getBoundingClientRect().width<=el.parentElement.getBoundingClientRect().width));
            assert(bounded,'Waiting labels must fit each card');
            await page.screenshot({path:'home-preview/waiting-'+theme+'-'+width+'.png',fullPage:true});
          }
        }
        if(name==='waiting'&&theme==='dark'){
          await buy.locator('.hp-wait-pick').first().click();
          await page.waitForURL('**/stocks.html?symbol=AAPL');
          await page.waitForFunction(()=>!document.getElementById('tickerInput').disabled);
          assert((await page.locator('#tickerInput').inputValue()).includes('AAPL'),'Waiting candidate link preserves the selected stock');
        }
        await page.unroute('**/market/home.json?*');
      }
      assert.deepEqual(errors,[]);
      if(theme==='dark'){
        const symbol=data.rankings.sell[0]?.symbol||data.rankings.buy[0]?.symbol||'NVDA';
        await page.goto('http://127.0.0.1:8765/?symbol='+symbol,{waitUntil:'networkidle'});
        await page.waitForURL('**/stocks.html?symbol='+symbol);
        await page.waitForFunction(()=>!document.getElementById('tickerInput').disabled);
        assert((await page.locator('#tickerInput').inputValue()).includes(symbol),'selected stock preserved');
        assert((await page.locator('#app').innerText()).includes(symbol));
      }
      await page.close();
    }
    console.log('Browser: empty buy, all waiting labels, actual buy priority, stale market, desktop/mobile 320–1440px, light/dark, sector detail, bar bounds and stock deep links passed.');
  }finally{if(browser)await browser.close();server.kill();}
})().catch(e=>{console.error(e);process.exitCode=1;});
