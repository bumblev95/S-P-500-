'use strict';
const {chromium}=require('playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),{spawn}=require('node:child_process');
(async()=>{
  const server=spawn('python3',['-m','http.server','8765','--bind','127.0.0.1'],{stdio:'ignore'});
  let browser;
  try{
    for(let i=0;i<30;i++){try{await fetch('http://127.0.0.1:8765/index.html');break;}catch(_){await new Promise(r=>setTimeout(r,100));}}
    browser=await chromium.launch({headless:true});
    fs.mkdirSync('home-preview',{recursive:true});
    const data=JSON.parse(fs.readFileSync('market/home.json','utf8'));
    for(const theme of ['light','dark']){
      const page=await browser.newPage({colorScheme:theme});
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
    console.log('Browser: desktop/mobile 320–1440px, light/dark, sector detail, bar bounds and stock deep links passed.');
  }finally{if(browser)await browser.close();server.kill();}
})().catch(e=>{console.error(e);process.exitCode=1;});
