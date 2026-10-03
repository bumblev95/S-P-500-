const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const C=require('../assets/company-events.js'),now=Date.parse('2026-10-03T02:00:00Z');
const event={id:'sec:0001045810-26-000100',date:'2026-10-02',dateKind:'filed',title:'실적·재무 현황 공시',
 category:'earnings',form:'8-K',items:['2.02','7.01'],reportDate:'2026-09-30',summary:'확인한 공시 항목',
 observedAt:'2026-10-02T23:00:00Z',source:{name:'SEC EDGAR',url:'https://www.sec.gov/Archives/edgar/data/1045810/000104581026000100/nvda-20260930.htm'}};
const future={id:'estimate',date:'2026-11-17',dateKind:'estimated',title:'실적 발표 예상일',
 observedAt:'2026-10-02T23:00:00Z',source:{name:'Yahoo Finance',url:'https://finance.yahoo.com/quote/NVDA/calendar/'}};
const fixture={schemaVersion:1,symbols:{NVDA:'1045810','NVDA-B':'1045810'},issuers:{1045810:{cik:1045810,
 sec:{status:'ready',lastSuccessAt:'2026-10-02T23:00:00Z'},events:[event]}},upcoming:{NVDA:[future]}};
let s=C.select(fixture,'nvda',now);assert.equal(s.past.length,1);assert.equal(s.upcoming.length,1);assert(s.fresh);
assert.equal(C.select(fixture,'NVDA.B',now).past[0].id,event.id);
let html=C.panel('NVDA',fixture,now);assert(html.includes('최근 공시 확인'));assert(html.includes('D−45'));
assert(html.includes('공시일'));assert(html.includes('예상 일정'));assert(html.includes('공시일은 사건 발생일'));
assert(html.includes('noopener noreferrer'));assert(!/undefined|NaN|Infinity/.test(html));
assert(!C.select(fixture,'NVDA',now+9*86400000).upcoming.length);
assert(!C.select(fixture,'NVDA',now+5*86400000).fresh);
assert(!C.select(fixture,'NVDA',now-86400000).past.length);
assert(C.panel('ETF',fixture,now).includes('공시 수집 대기'));
for(const change of [{date:'2026-10-04'},{date:'2026-09-31'},{observedAt:'2026-10-01T00:00:00Z'},
 {source:{url:'https://evil.example/file.htm'}},{source:{url:'javascript:alert(1)'}}]){
 const bad=structuredClone(fixture);bad.issuers[1045810].events=[{...event,...change}];
 assert.equal(C.select(bad,'NVDA',now).past.length,0);
}
for(const url of ['https://www.sec.gov.evil.example/Archives/edgar/data/1/000000000000000001/x.htm',
 'https://user@www.sec.gov/Archives/edgar/data/1/000000000000000001/x.htm','http://www.sec.gov/file.htm'])assert(!C.safeSource(url));
const xss=structuredClone(fixture);xss.issuers[1045810].events[0].title='<img src=x onerror=alert(1)>';
html=C.panel('NVDA',xss,now);assert(!html.includes('<img'));assert(html.includes('&lt;img'));
const delayed=structuredClone(fixture);delayed.issuers[1045810].sec.status='access_denied';
html=C.panel('NVDA',delayed,now);assert(html.includes('수집 지연'));assert(html.includes(event.title));
assert(!html.includes('최근 공시 확인</span>'));
const many=structuredClone(fixture);many.issuers[1045810].events=Array.from({length:8},(_,i)=>({...event,id:'sec:'+i}));
html=C.panel('NVDA',many,now);assert(html.includes('이전 공시 4개 더 보기'));
// The calculator is absent on every previously connected stock/spot/futures page.
for(const file of ['index.html','assets/crypto.js','assets/perp-page.js','assets/decision-support.js'])
 assert(!/tradePlanner|거래 계획 계산기|data-plan=/.test(fs.readFileSync(file,'utf8')),file);
for(const file of ['index.html','advanced.html','advanced-legacy.html']){
 const text=fs.readFileSync(file,'utf8');assert(text.includes('assets/company-events.js'));assert(text.includes('assets/company-events.css'));
 assert(text.indexOf('assets/company-events.js')<text.indexOf('assets/decision-support.js'));
}
(async()=>{
 // Late replies cannot put the previous company's data into the selected host.
 let release;const root={};const clock=class extends Date{static now(){return now}};
 vm.runInNewContext(fs.readFileSync('assets/company-events.js','utf8'),{window:root,Date:clock,URL,
  fetch:undefined});
 const api=root.CompanyEvents;
 const pending=api.load(()=>new Promise(resolve=>{release=resolve}));
 const host={dataset:{},innerHTML:'',isConnected:true};api.mount(host,'NVDA');api.mount(host,'NVDA.B');
 release({ok:true,json:async()=>fixture});await pending;await Promise.resolve();
 assert(host.innerHTML.includes('data-event-symbol="NVDA-B"'));assert(!host.innerHTML.includes('data-event-symbol="NVDA"'));
 await api.load(async()=>{throw Error('offline')},true);
 assert(api.panel('NVDA').includes('자료 읽기 실패'));
 console.log('Company events: public dates, estimates, source allowlist, stale/missing feeds, shared issuers, selection races and calculator removal passed.');
})().catch(e=>{console.error(e);process.exitCode=1});
