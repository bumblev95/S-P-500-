'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {adSettings}=require('../assets/site-ads.js');
const defaults=require('../assets/site-ads-config.js');
const valid={enabled:true,publisherId:'ca-pub-9876543210123456',slots:{home:'9876543210',stocks:'9876543211'}};
assert.equal(defaults.enabled,false,'unconfigured deployment must not request ads');
assert.equal(adSettings(defaults,'home'),null);
assert.deepEqual(adSettings(valid,'home'),{publisherId:valid.publisherId,slot:valid.slots.home});
for(const config of [null,{}, {...valid,enabled:false},{...valid,enabled:'true'},
  {...valid,publisherId:''},{...valid,publisherId:'ca-pub-123'},
  {...valid,publisherId:'ca-pub-0000000000000000'},
  {...valid,publisherId:'ca-pub-1234567890123456'},
  {...valid,publisherId:'ca-pub-9876543210123456&injected=1'},
  {...valid,slots:{}},{...valid,slots:{home:'<script>alert(1)</script>'}},
  {...valid,slots:{home:9876543210}},{...valid,slots:{home:'0000000000'}}]){
  assert.equal(adSettings(config,'home'),null,'incomplete or unsafe configuration must stay disabled');
}
assert.equal(adSettings(valid,'unregistered'),null);
for(const [file,name] of [['index.html','home'],['stocks.html','stocks']]){
  const source=fs.readFileSync(path.join(__dirname,'..',file),'utf8');
  assert.equal((source.match(/data-site-ad=/g)||[]).length,1,'one manual placement per page');
  assert(source.includes('data-site-ad="'+name+'" aria-label="광고" hidden'));
  assert(source.indexOf('assets/site-ads-config.js')<source.indexOf('assets/site-ads.js'));
  assert(source.includes('href="privacy.html"'));
  assert(!source.includes('pagead2.googlesyndication.com'),'provider must not be loaded unconditionally');
  if(name==='stocks')assert(source.indexOf('data-site-ad="stocks"')>source.indexOf('<div id="app"'));
}
console.log('Ads: disabled defaults, real identifier requirements, injection rejection and two isolated placements passed.');
