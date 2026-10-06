'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const primary = ['index.html','stocks.html','crypto.html','futures.html','simulation.html','advanced.html','research.html','model-validation.html','signal-lab.html','leverage-lab.html','exit-experiment.html','momentum-experiment.html','selector-experiment.html'];
const articles = ['learn.html','guide-top3.html','guide-indicators.html','guide-backtesting.html','guide-news.html','methodology.html','about.html','contact.html','terms.html','privacy.html'];
const links = ['learn.html','methodology.html','about.html','contact.html','privacy.html','terms.html'];
const read = file => fs.readFileSync(path.join(root, file), 'utf8');
for (const file of [...primary, ...articles]) {
  const html = read(file);
  assert.equal((html.match(/class="site-info-footer"/g) || []).length, 1, file + ': one site-information footer');
  const footer = html.split('class="site-info-footer"')[1].split('</footer>')[0];
  for (const target of links) assert(footer.includes('href="' + target + '"'), file + ': reachable ' + target);
  const canonical = file === 'index.html' ? 'https://bumblev95.github.io/' : 'https://bumblev95.github.io/S-P-500-/' + file;
  assert(html.includes('rel="canonical" href="' + canonical + '"'), file + ': canonical URL');
}
for (const file of articles) {
  const html = read(file);
  assert.equal((html.match(/<h1(?:\s|>)/g) || []).length, 1, file + ': clear page heading');
  assert(html.includes('name="description"'), file + ': distinct description');
  assert(!/data-site-ad=|adsbygoogle\.js|<iframe/i.test(html), file + ': explanatory pages have no advertising or embedded copied page');
  // All internal destinations on the new static pages must exist independently
  // of JavaScript; external links retain the original provider destination.
  for (const [, target] of html.matchAll(/(?:href|src)="([^"]+)"/g)) {
    if (/^(https?:|data:|#)/.test(target)) continue;
    const dest = target.split(/[?#]/)[0];
    assert(fs.existsSync(path.join(root, dest === './' ? 'index.html' : dest)), file + ': missing destination ' + target);
  }
}
const homepage = read('index.html');
assert.equal(read('research/adsense-root-site/index.html').replace('  <base href="https://bumblev95.github.io/S-P-500-/">\n',''), homepage, 'hostname root must match the current main markup');
const locations = [...read('sitemap.xml').matchAll(/<loc>([^<]+)<\/loc>/g)].map(x => x[1]);
assert.equal(new Set(locations).size, locations.length, 'no duplicate sitemap URLs');
for (const file of articles) assert(locations.includes('https://bumblev95.github.io/S-P-500-/' + file), file + ': discoverable');
assert(read('robots.txt').includes('Sitemap: https://bumblev95.github.io/sitemap.xml'));
assert(!/^Disallow:\s*\/\s*$/m.test(read('robots.txt')), 'site must remain crawlable');
console.log('Site information: static guidance, internal destinations, primary-page navigation, synchronized root, canonical URLs and sitemap passed.');

if (process.argv.includes('--browser')) {
  const {chromium} = require('playwright');
  (async () => {
    let browser;
    const origin = 'https://bumblev95.github.io';
    const base = origin + '/S-P-500-/';
    try {
      browser = await chromium.launch({headless:true, executablePath:process.env.SITE_ADS_CHROMIUM || undefined});
      const context = await browser.newContext({javaScriptEnabled:false});
      const external = [];
      await context.route('**/*', route => {
        const url = new URL(route.request().url());
        if (url.origin !== origin) {external.push(url.href); return route.abort();}
        const relative = url.pathname === '/' ? 'research/adsense-root-site/index.html' : url.pathname.replace(/^\/S-P-500-\//, '');
        const local = path.resolve(root, relative);
        if (!local.startsWith(root + path.sep) || !fs.existsSync(local)) return route.fulfill({status:404,body:'Not found'});
        const type = {'.html':'text/html; charset=utf-8','.css':'text/css; charset=utf-8','.xml':'application/xml'}[path.extname(local)] || 'text/plain';
        return route.fulfill({contentType:type,body:fs.readFileSync(local)});
      });
      const page = await context.newPage();
      for (const file of ['index.html', ...articles]) {
        external.length = 0;
        await page.goto(file === 'index.html' ? origin + '/' : base + file);
        assert.equal(await page.locator('h1:visible').count(), 1, file + ': readable heading without scripts');
        assert(await page.locator('.site-info-footer').isVisible(), file + ': static navigation');
        if (file !== 'index.html') {
          assert((await page.locator('article').innerText()).length > 350, file + ': actual explanatory content');
          assert.equal(external.length, 0, file + ': static explanations need no external services');
        }
        for (const width of [320,375,768,1280]) {
          await page.setViewportSize({width,height:900});
          assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), file + ': horizontal page overflow at ' + width);
        }
      }
      await page.goto(origin + '/');
      await page.getByRole('link',{name:'TOP3 읽기',exact:true}).click();
      assert.equal(new URL(page.url()).pathname, '/S-P-500-/guide-top3.html', 'root base resolves guide correctly');
      await page.locator('.site-info-footer').getByRole('link',{name:'분석 기준·자료 출처',exact:true}).click();
      assert.equal(new URL(page.url()).pathname, '/S-P-500-/methodology.html');
      assert.equal(external.filter(url => /googlesyndication|google-analytics|googletagmanager/.test(url)).length, 0, 'reading static guidance must not request ads or external tracking');
      fs.mkdirSync(path.join(root,'site-information-preview'), {recursive:true});
      await page.setViewportSize({width:1280,height:900});
      await page.screenshot({path:path.join(root,'site-information-preview/methodology-desktop.png'),fullPage:true});
      await page.goto(base + 'learn.html');
      await page.setViewportSize({width:375,height:900});
      await page.screenshot({path:path.join(root,'site-information-preview/guide-mobile.png'),fullPage:true});
      console.log('Browser information: guides readable with JavaScript disabled, root-to-guide navigation, 320–1280px layout and zero external tracking passed.');
    } finally {if (browser) await browser.close();}
  })().catch(error => {console.error(error); process.exitCode = 1;});
}
