'use strict';
// Render metadata in the response HTML; crawlers need no browser-side injection.
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const base = 'https://bumblev95.github.io/S-P-500-/';
const home = 'https://bumblev95.github.io/';
const primary = ['index.html','stocks.html','crypto.html','futures.html','simulation.html','advanced.html','research.html','model-validation.html','signal-lab.html','leverage-lab.html','exit-experiment.html','momentum-experiment.html','selector-experiment.html'];
const articles = ['learn.html','guide-top3.html','guide-indicators.html','guide-sell.html','guide-backtesting.html','guide-news.html','methodology.html','about.html','contact.html','terms.html','privacy.html'];
const editorial = new Set(['learn.html','methodology.html', ...articles.filter(f => f.startsWith('guide-'))]);
const decode = s => s.replace(/&amp;/g, '&').replace(/&quot;/g, '"').replace(/&#39;/g, "'");
const escape = s => s.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
const read = f => fs.readFileSync(path.join(root, f), 'utf8');
let changed = false;
function write(file, content) {
  if (fs.existsSync(path.join(root,file)) && read(file) === content) return;
  changed = true;
  if (process.argv.includes('--check')) { console.error('Stale search output: '+file); return; }
  fs.writeFileSync(path.join(root,file), content);
}
const projectEntries = [];
const rootEntries = [];
for (const file of [...primary, ...articles]) {
  const source = read(file);
  const title = decode(source.match(/<title>([^<]+)<\/title>/)[1]);
  const description = decode(source.match(/<meta name="description" content="([^"]+)"/)[1]);
  const url = file === 'index.html' ? home : base+file;
  const graph = [];
  if (file === 'index.html') {
    graph.push({'@type':'WebSite','@id':home+'#website',url:home,name:'S&P 500 Market Dashboard',inLanguage:'ko',publisher:{'@type':'Person',name:'Jack Lee',url:base+'about.html'}});
    graph.push({'@type':'WebPage','@id':url+'#page',url,name:title,description,inLanguage:'ko',isPartOf:{'@id':home+'#website'}});
  } else {
    const crumbs = [{name:'S&P 500 시장 대시보드',item:home}];
    if (file.startsWith('guide-')) crumbs.push({name:'초보자 주식 가이드',item:base+'learn.html'});
    crumbs.push({name:title.split(' · ')[0],item:url});
    graph.push({'@type':'BreadcrumbList',itemListElement:crumbs.map((c,i)=>({'@type':'ListItem',position:i+1,...c}))});
    const date = source.match(/<time datetime="(\d{4}-\d{2}-\d{2})"/);
    graph.push({'@type':editorial.has(file)?'Article':'WebPage','@id':url+'#page',url,name:title,headline:title,description,inLanguage:'ko',mainEntityOfPage:url,
      ...(editorial.has(file)?{author:{'@type':'Person',name:'Jack Lee',url:base+'about.html'},...(date?{dateModified:date[1]}:{})}:{})});
  }
  const block = '\n<!-- search-metadata:start -->\n'+
    `<meta property="og:type" content="${editorial.has(file)?'article':'website'}">\n<meta property="og:locale" content="ko_KR">\n<meta property="og:site_name" content="S&amp;P 500 Market Dashboard">\n<meta property="og:title" content="${escape(title)}">\n<meta property="og:description" content="${escape(description)}">\n<meta property="og:url" content="${url}">\n<meta name="twitter:card" content="summary">\n`+
    '<script type="application/ld+json">'+JSON.stringify({'@context':'https://schema.org','@graph':graph}).replace(/</g,'\\u003c')+'</script>\n<!-- search-metadata:end -->\n';
  const clean = source.replace(/\n<!-- search-metadata:start -->[\s\S]*?<!-- search-metadata:end -->\n/g,'');
  write(file, clean.replace('</head>',block+'</head>'));
  // Only visible editorial update dates are used; live dashboards have no stale
  // HTML modification date masquerading as the market observation date.
  const date = source.match(/<time datetime="(\d{4}-\d{2}-\d{2})"/);
  const entry = `  <url><loc>${url}</loc>${date?'<lastmod>'+date[1]+'</lastmod>':''}</url>`;
  rootEntries.push(entry);
  if (file !== 'index.html') projectEntries.push(entry);
}
const sitemap = entries => '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'+entries.join('\n')+'\n</urlset>\n';
write('sitemap.xml',sitemap(projectEntries));
write('research/adsense-root-site/sitemap.xml',sitemap(rootEntries));
write('research/adsense-root-site/index.html',read('index.html').replace('<head>\n','<head>\n  <base href="'+base+'">\n'));
if (process.argv.includes('--check') && changed) process.exitCode = 1;
else console.log('Search metadata and scoped sitemaps '+(changed?'updated':'verified')+'.');
