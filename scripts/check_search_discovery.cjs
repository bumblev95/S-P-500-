'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const root = path.resolve(__dirname,'..');
const base = 'https://bumblev95.github.io/S-P-500-/';
const home = 'https://bumblev95.github.io/';
const read = f => fs.readFileSync(path.join(root,f),'utf8');
execFileSync(process.execPath,[path.join(__dirname,'build_search_metadata.cjs'),'--check'],{stdio:'inherit'});
const urls = [...read('sitemap.xml').matchAll(/<loc>([^<]+)<\/loc>/g)].map(m=>m[1]);
const rootUrls = [...read('research/adsense-root-site/sitemap.xml').matchAll(/<loc>([^<]+)<\/loc>/g)].map(m=>m[1]);
assert.equal(new Set(urls).size,urls.length);
assert.deepEqual(rootUrls,[home,...urls]);
const titles = new Set();
for (const url of [home,...urls]) {
  assert(!url.endsWith('.xml/') && !url.includes('?') && !url.includes('#'));
  if (url !== home) assert(url.startsWith(base),'project sitemap must stay inside its property');
  const file = url === home ? 'index.html' : url.slice(base.length);
  const html = read(file);
  assert(!/<meta[^>]+(?:noindex|nofollow)/i.test(html),file+': public page must be indexable');
  assert(!/http-equiv="refresh"/i.test(html),file+': sitemap must not include redirect archives');
  assert.equal((html.match(/rel="canonical"/g)||[]).length,1);
  assert(html.includes('rel="canonical" href="'+url+'"'));
  const title = html.match(/<title>([^<]+)<\/title>/)[1];
  assert(!titles.has(title),'unique page title: '+file);titles.add(title);
  assert(html.includes('property="og:url" content="'+url+'"'));
  const schema = JSON.parse(html.match(/<script type="application\/ld\+json">([^<]+)<\/script>/)[1]);
  const page = schema['@graph'].find(n=>n['@id']===url+'#page');
  assert(page && page.url === url);
  if (file.startsWith('guide-')) {
    assert.equal(page['@type'],'Article');
    assert.equal(page.dateModified,html.match(/<time datetime="([^"]+)"/)[1]);
    assert(html.includes('href="learn.html"'),'article must link to guide directory');
    assert(html.includes('class="site-breadcrumbs"'));
  }
  const crumb = schema['@graph'].find(n=>n['@type']==='BreadcrumbList');
  if (crumb) assert.equal(crumb.itemListElement.at(-1).item,url);
}
assert(urls.includes(base+'guide-sell.html'));
assert(read('index.html').includes('href="guide-sell.html"'));
assert(read('stocks.html').includes('id="stock-help-title"'));
assert(read('robots.txt').includes('Sitemap: '+base+'sitemap.xml'));
console.log('PASS: 24 metadata/schema pages, 23 property-scoped URLs, canonical homepage mirror, visible guide navigation and truthful update dates.');
