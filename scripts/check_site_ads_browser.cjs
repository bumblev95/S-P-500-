'use strict';
const {chromium}=require('playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),http=require('node:http'),path=require('node:path');
const root=path.resolve(__dirname,'..');
const config={enabled:true,publisherId:'ca-pub-9876543210123456',slots:{home:'9876543210',stocks:'9876543211'}};
const mockScript=status=>`window.adsbygoogle={push:function(){window.__adPushes=(window.__adPushes||0)+1;var ad=Array.from(document.querySelectorAll('ins.adsbygoogle')).find(function(el){return !el.hasAttribute('data-mock-requested')});if(ad)ad.setAttribute('data-mock-requested','true');setTimeout(function(){if(ad){ad.setAttribute('data-ad-status',${JSON.stringify(status)});if(${JSON.stringify(status)}==='filled'){ad.innerHTML='<div style="display:grid;place-items:center;height:100%;border:1px dashed #8b9dad;font:14px system-ui;color:#899db0">광고 영역 미리보기</div>'}}},10)}};`;
const server=http.createServer((req,res)=>{
  const pathname=decodeURIComponent(new URL(req.url,'http://localhost').pathname);
  const file=path.resolve(root,'.'+(pathname==='/'?'/index.html':pathname));
  if(!file.startsWith(root+path.sep)){res.writeHead(403);res.end();return;}
  try{
    const type={'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.json':'application/json; charset=utf-8'}[path.extname(file)]||'text/plain';
    res.writeHead(200,{'content-type':type});res.end(fs.readFileSync(file));
  }catch(_){res.writeHead(404);res.end();}
});
(async()=>{
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const base='http://127.0.0.1:'+server.address().port;
  let browser;
  try{
    browser=await chromium.launch({headless:true,executablePath:process.env.SITE_ADS_CHROMIUM||undefined});
    fs.mkdirSync('ad-preview',{recursive:true});
    async function scenario({status='filled',enabled=true,blocked=false,extraUnit=false,throwPush=false,theme='light',pathname='/'}){
      const page=await browser.newPage({viewport:{width:1280,height:900},colorScheme:theme});
      const errors=[],requests=[];
      page.on('pageerror',e=>errors.push(e.message));
      await page.route('**/*',route=>{
        const url=new URL(route.request().url());
        if(url.hostname==='pagead2.googlesyndication.com'){
          requests.push(url.href);
          if(blocked)return route.abort();
          return route.fulfill({contentType:'text/javascript',body:throwPush?'window.adsbygoogle={push:function(){throw Error("blocked ad request")}};':mockScript(status)});
        }
        if(url.origin!==base)return route.abort();
        if(url.pathname==='/assets/site-ads-config.js'&&enabled){
          return route.fulfill({contentType:'text/javascript',body:'window.SiteAdsConfig='+JSON.stringify(config)+';'});
        }
        if(pathname==='/stocks.html'&&url.pathname==='/stocks.html'){
          // Exercise the real stock ad placement without requiring the large live datasets.
          const original=fs.readFileSync(path.join(root,'stocks.html'),'utf8');
          const stripped=original.replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi,match=>match.includes('assets/site-ads')?match:'');
          return route.fulfill({contentType:'text/html; charset=utf-8',body:stripped});
        }
        return route.continue();
      });
      await page.goto(base+pathname,{waitUntil:'networkidle'});
      await page.evaluate(extra=>{
        if(extra){
          const source=document.querySelector('[data-site-ad]');
          const copy=source.cloneNode(true);
          copy.dataset.siteAd='stocks';delete copy.dataset.adState;
          copy.hidden=true;copy.querySelector('[data-site-ad-body]').innerHTML='';
          source.after(copy);
        }
        window.SiteAds.init();window.SiteAds.init();
      },extraUnit);
      await page.evaluate(()=>window.scrollTo(0,document.body.scrollHeight));
      if(enabled){
        await page.waitForFunction(()=>Array.from(document.querySelectorAll('[data-site-ad]')).every(el=>['filled','unfilled','unfill-optimized','unavailable'].includes(el.dataset.adState)));
        assert.equal(requests.length,1,'load provider once despite repeated initialization');
        assert.equal(await page.locator('[data-site-ads-provider]').count(),1);
        if(blocked||throwPush){
          assert.equal(await page.locator('[data-site-ad]:visible').count(),0);
        }else{
          assert.equal(await page.evaluate(()=>window.__adPushes),extraUnit?2:1,'request each unit once');
          assert.equal(await page.locator('[data-site-ad]:visible').count(),status!=='unfilled'?(extraUnit?2:1):0);
        }
      }else{
        assert.equal(requests.length,0,'disabled configuration must not contact ad provider');
        assert.equal(await page.locator('ins.adsbygoogle').count(),0);
        assert.equal(await page.locator('[data-site-ad]:visible').count(),0);
      }
      for(const width of [320,375,768,1280]){
        await page.setViewportSize({width,height:900});
        assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'overflow at '+width);
        if(status==='filled'&&enabled&&!blocked&&!throwPush){
          const bounded=await page.locator('ins.adsbygoogle').evaluateAll(ads=>ads.every(ad=>{const r=ad.getBoundingClientRect();return r.width>=200&&r.left>=0&&r.right<=innerWidth+1;}));
          assert(bounded,'ad must fit available page width');
          if(!extraUnit&&(width===375||width===1280)&&pathname==='/')await page.screenshot({path:'ad-preview/'+theme+'-'+width+'.png',fullPage:true});
        }
      }
      assert.deepEqual(errors,[], 'advertising must not throw into the page');
      await page.close();
    }
    await scenario({enabled:false});
    await scenario({extraUnit:true});
    await scenario({theme:'dark'});
    await scenario({pathname:'/stocks.html'});
    await scenario({status:'unfilled'});
    await scenario({status:'unfill-optimized'});
    await scenario({blocked:true});
    await scenario({throwPush:true});
    const privacy=await browser.newPage();
    await privacy.goto(base+'/privacy.html');
    assert.equal(await privacy.locator('h1').innerText(),'개인정보·광고 안내');
    assert.equal(await privacy.locator('[data-site-ad]').count(),0);
    await privacy.close();
    console.log('Browser ads: zero requests when disabled, single provider, separate units, unfilled/blocked recovery, both placements and responsive light/dark layouts passed.');
  }finally{
    if(browser)await browser.close();
    await new Promise(resolve=>server.close(resolve));
  }
})().catch(e=>{console.error(e);process.exitCode=1;});
