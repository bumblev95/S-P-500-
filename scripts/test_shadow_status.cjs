'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),vm=require('node:vm'),cp=require('node:child_process');
const D=require('./build_shadow_status.cjs'),S=require('./shadow_improvement.cjs'),E=require('./shadow_evidence.cjs');
const ROOT=S.ROOT,copy=x=>JSON.parse(JSON.stringify(x));let count=0;
function test(name,run){run();count++;console.log('PASS '+name);}
function files(root,dir='simulation'){
 const result={};function walk(relative){for(const entry of fs.readdirSync(path.join(root,relative),{withFileTypes:true})){const name=relative+'/'+entry.name;if(name===D.OUTPUT)continue;if(entry.isDirectory())walk(name);else result[name]=E.bytesHash(fs.readFileSync(path.join(root,name)));}}walk(dir);return result;
}
let initial,version,versionDir;
const originalFiles=files(ROOT),runtime=S.runtimeHashes(ROOT);
test('real assessment is independently recomputed with no state or runtime writes',()=>{
 const actual=D.build();assert.equal(actual.sourceIntegrity.passed,true);assert(actual.sources.decisionRecords>=95);
 for(const row of actual.versions){if(row.integrityPassed){assert.equal(row.status,row.assessment.status);assert.equal(row.promotionCandidate,Object.values(row.assessment.gates).every(Boolean));}else{assert.equal(row.status,'blocked');assert.equal(row.promotionCandidate,false);}}
 assert.deepEqual(files(ROOT),originalFiles);assert.deepEqual(S.runtimeHashes(ROOT),runtime);
});
const temp=fs.mkdtempSync(path.join(os.tmpdir(),'shadow-status-'));
try{
 for(const f of [...S.RUNTIME,'ml/adaptive-summary.json']){fs.mkdirSync(path.dirname(path.join(temp,f)),{recursive:true});fs.copyFileSync(path.join(ROOT,f),path.join(temp,f));}
 for(const dir of ['simulation/momentum-boost',S.BASE])fs.cpSync(path.join(ROOT,dir),path.join(temp,dir),{recursive:true});
 fs.copyFileSync(path.join(ROOT,'simulation/market.json'),path.join(temp,'simulation/market.json'));
 cp.execFileSync('git',['init','-q'],{cwd:temp});cp.execFileSync('git',['-c','user.name=Test','-c','user.email=test@example.invalid','commit','-q','--allow-empty','-m','Private shadow status fixture'],{cwd:temp});
 const fixture=S.register({root:temp,thresholdR:.15});S.assess({root:temp,version:fixture.version});
 initial=D.build({root:temp});version=fixture.version;versionDir=S.BASE+'/'+version;
 const now=Date.now(),row=()=>D.build({root:temp,now}).versions.find(v=>v.version===version);
 function changed(file,transform,check){const name=path.join(temp,file),before=fs.readFileSync(name);try{fs.writeFileSync(name,transform(before));check();}finally{fs.writeFileSync(name,before);}}
 const blocked=()=>{const r=row();assert.equal(r.status,'blocked');assert.equal(r.promotionCandidate,false);assert.equal(r.integrityPassed,false);return r;};
 test('display publication changes only its disposable file and is not engine input',()=>{
  const before=files(temp);D.publish(temp,now);assert.deepEqual(files(temp),before);
  fs.writeFileSync(path.join(temp,D.OUTPUT),'{"promotionCandidate":true,"cash":999999999}');
  const clean=D.build({root:temp,now});assert.equal(clean.versions[0].promotionCandidate,false);
  assert.deepEqual(files(temp),before);assert(!S.RUNTIME.includes('scripts/build_shadow_status.cjs'));
 });
 test('display publication rejects a symlink to any other file',()=>{
  const status=path.join(temp,D.OUTPUT),outside=path.join(temp,'do-not-write.json');fs.writeFileSync(outside,'preserve');fs.unlinkSync(status);fs.symlinkSync(outside,status);
  try{assert.throws(()=>D.publish(temp,now),/Unsafe status file/);assert.equal(fs.readFileSync(outside,'utf8'),'preserve');}finally{fs.unlinkSync(status);}
 });
 const assessment=row().assessmentPath,observation=row().observationPath,candidate=versionDir+'/candidate.json';
 test('corrupt assessment hashes block instead of reusing last good status',()=>changed(assessment,b=>{const j=JSON.parse(b);j.promotionCandidate=true;return JSON.stringify(j);},()=>assert.match(blocked().reason,/hash/)));
 test('rehashed all-pass claims must still agree with recomputed economic gates',()=>{
  const name=path.join(temp,assessment),before=fs.readFileSync(name),j=JSON.parse(before);delete j.hash;
  j.status='promotion_candidate';j.promotionCandidate=true;for(const key of Object.keys(j.gates))j.gates[key]=true;
  j.hash=E.sha(j);const renamed=path.join(path.dirname(name),j.asOf+'-'+j.hash.slice(0,12)+'.json');
  try{fs.unlinkSync(name);fs.writeFileSync(renamed,JSON.stringify(j));assert.match(blocked().reason,/disagrees/);}
  finally{fs.unlinkSync(renamed);fs.writeFileSync(name,before);}
 });
 test('missing latest assessments never recreate records',()=>{
  const file=path.join(temp,assessment),before=fs.readFileSync(file);try{fs.unlinkSync(file);assert.match(blocked().reason,/Missing assessment/);assert(!fs.existsSync(file));}finally{fs.writeFileSync(file,before);}
 });
 test('candidate, observation and source checkpoint tampering block',()=>{
  changed(candidate,b=>b.toString().replace('"thresholdR":0.15','"thresholdR":0.17'),()=>assert.match(blocked().reason,/hash/));
  changed(observation,b=>{const j=JSON.parse(b);j.previousHash='a'.repeat(64);return JSON.stringify(j);},()=>assert.match(blocked().reason,/hash|link/));
  const source=Object.keys(JSON.parse(fs.readFileSync(path.join(temp,candidate))).source.immutableFiles).find(f=>f.includes('/decisions/'));
  changed(source,b=>b.toString()+'\n',()=>assert.match(blocked().reason,/changed or disappeared/));
 });
 test('incompatible runtime is blocked without migrating the version',()=>changed(S.RUNTIME[0],b=>b.toString()+'\n',()=>assert.match(blocked().reason,/runtime changed/)));
 test('source-chain errors and invalid registries produce explicit integrity failures',()=>{
  changed('simulation/momentum-boost/experiment.json',b=>{const j=JSON.parse(b);j.decisionHash='b'.repeat(64);return JSON.stringify(j);},()=>{
   const d=D.build({root:temp,now});assert.equal(d.sourceIntegrity.passed,false);blocked();
  });
  fs.mkdirSync(path.join(temp,S.BASE,'not-a-version'));try{const d=D.build({root:temp,now});assert.equal(d.sourceIntegrity.passed,false);assert.deepEqual(d.versions,[]);}finally{fs.rmdirSync(path.join(temp,S.BASE,'not-a-version'));}
 });
 test('compatible batch updates retain paused versions without touching their records',()=>{
  const before=files(temp),at=fixture.registeredAt,result=S.updateCompatible({root:temp,now:at});
  assert(result.some(r=>r.candidateVersion===version&&r.status==='insufficient'));assert(result.some(r=>r.status==='paused'));
  const after=files(temp);for(const [file,hash] of Object.entries(before))assert.equal(after[file],hash,'Existing file must remain unchanged: '+file);
  for(const paused of result.filter(r=>r.status==='paused')){
   const prefix=S.BASE+'/'+paused.candidateVersion+'/';
   assert.deepEqual(Object.keys(after).filter(f=>f.startsWith(prefix)),Object.keys(before).filter(f=>f.startsWith(prefix)),'Paused versions must not receive new records');
  }
 });
 test('future registration cannot be shown as current validated data',()=>assert.match(D.build({root:temp,now:fixture.registeredAt-1}).versions.find(v=>v.version===version).reason,/Future shadow timestamp/));
 test('workflow allows the mutable display only; all existing evidence stays append-only',()=>{
  const y=fs.readFileSync(path.join(ROOT,'.github/workflows/shadow-self-improvement.yml'),'utf8');
  const body=y.match(/node - <<'JS'\n([\s\S]*?)\n\s*JS/)[1].split('\n').map(l=>l.replace(/^          /,'')).join('\n');
  const check=rows=>vm.runInNewContext(body,{require:()=>({execFileSync:()=>rows.join('\n')})});
  const input='simulation/self-improvement/inputs/'+'a'.repeat(64)+'.json';
  assert.doesNotThrow(()=>check(['A\t'+candidate,'A\t'+input,'M\t'+D.OUTPUT]));
  for(const name of ['M\t'+candidate,'D\t'+observation,'D\t'+D.OUTPUT,'M\t'+input,'D\t'+input,'M\tsimulation/market.json','M\tsimulation/momentum-boost/model.json','M\tsimulation/momentum-boost/boost-one/state.json','M\tassets/simulation-page.js'])assert.throws(()=>check([name]),/Only NEW/);
 });
}finally{fs.rmSync(temp,{recursive:true,force:true});}

const nodes={},document={getElementById(id){return nodes[id]||null;}},context=vm.createContext({window:{},document,console,fetch:async()=>{throw Error('Unexpected fetch');}});
vm.runInContext(fs.readFileSync(path.join(ROOT,'assets/shadow-status.js'),'utf8'),context);
const UI=context.window.ShadowStatus,uiNow=initial.versions[0].assessment.asOf+1000,fresh=copy(initial);fresh.generatedAt=uiNow;
test('insufficient UI shows paired counts, gates, waiting state and no invented returns',()=>{
 const html=UI.render(fresh,version,uiNow);assert(html.includes('표본 부족'));assert(html.includes('첫 수집 대기'));assert(html.includes('최소 표본'));assert(html.includes('/ 100 건'));assert(html.includes('/ 90 일'));assert(html.includes(initial.versions[0].initialTrainingTrades+' / 30건'));assert(!html.includes('NaN')&&!html.includes('undefined'));assert(!html.includes('shadow-review'));
 assert.equal((html.match(/<progress /g)||[]).length,3);assert(html.includes('<td>—</td>'));
});
function passing(){const d=copy(fresh),v=d.versions[0],a=v.assessment;v.status=a.status='promotion_candidate';v.promotionCandidate=a.promotionCandidate=true;v.activity='collecting';for(const key of Object.keys(a.gates))a.gates[key]=true;return d;}
test('fresh all-gates pass means human review only, never a strategy switch',()=>{
 const d=passing(),html=UI.render(d,version,uiNow);assert(html.includes('사람 검토 후보'));assert(html.includes('shadow-review'));assert(html.includes('자동 승격 없음'));assert(html.includes('자동 반영되지 않습니다'));
});
test('one failed gate or an unsafe promotion flag hides eligibility',()=>{
 const d=passing();d.versions[0].assessment.gates.riskNotWorse=false;let html=UI.render(d,version,uiNow);assert(html.includes('검증 차단'));assert(!html.includes('사람 검토 후보'));
 d.automaticPromotion=true;html=UI.render(d,version,uiNow);assert(html.includes('상태 자료 없음'));assert(!html.includes('shadow-review'));
});
test('stale observations, stale display timestamps and future clocks cannot show current eligibility',()=>{
 const d=passing();let html=UI.render(d,version,uiNow+1800001);assert(html.includes('평가 갱신 대기'));assert(html.includes('마지막 평가 · 통과'));assert(!html.includes('사람 검토 후보')&&!html.includes('shadow-review'));
 d.generatedAt=uiNow+3600000;html=UI.render(d,version,uiNow+3600000);assert(!html.includes('사람 검토 후보'));
 html=UI.render(d,version,uiNow);assert(html.includes('검증 차단'));assert(!html.includes('사람 검토 후보'));
});
test('rejection, missing versions and global registry failures remain distinct',()=>{
 const d=copy(fresh);d.versions[0].status=d.versions[0].assessment.status='rejected';assert(UI.render(d,version,uiNow).includes('검증 기준 미충족'));
 d.versions=[];assert(UI.render(d,null,uiNow).includes('등록된 shadow 후보가 없습니다'));
 d.sourceIntegrity={passed:false,reason:'invalid registry'};assert(UI.render(d,null,uiNow).includes('후보 목록을 검증하지 못했습니다'));
});
test('forecast gates stay separate from paper performance and eligibility',()=>{
 const d=copy(fresh);d.forecastResearch={generatedAt:'fixture',horizons:{126:{chosen:'regimeBlend',passed:false,liveForecastChanged:false},252:{status:'insufficient',reason:'보정 후 독립 검증 시점 부족'}},usedForTrading:false};
 const html=UI.render(d,version,uiNow);assert(html.includes('별도 주가 예측 연구'));assert(html.includes('합산하지 않습니다'));assert(html.includes('독립 표본 부족'));assert(html.includes('변경 없음'));assert(!html.includes('사람 검토 후보'));
});
test('untrusted text is escaped and evidence links cannot address external URLs',()=>{
 const d=copy(fresh),v=d.versions[0];v.reason='<img src=x onerror=alert(1)>';v.integrityPassed=false;v.assessmentPath='javascript:alert(1)';
 const html=UI.render(d,version,uiNow);assert(!html.includes('<img'));assert(html.includes('&lt;img'));assert(!html.includes('href="javascript:'));
});

async function interactions(){
 const d=copy(fresh),second=copy(d.versions[0]);second.version='shadow-threshold-v1-1790847209064-aaaaaaaaaaaa';second.assessment.candidateVersion=second.version;second.status=second.assessment.status='rejected';d.versions.push(second);
 const select={value:version,addEventListener(name,fn){this.listener=fn;}};nodes.shadowVersion=select;
 const element={innerHTML:''};let calls=0;
 await UI.mount(element,async(url,options)=>{calls++;assert.equal(url,D.OUTPUT);assert.equal(options.cache,'no-store');return {ok:true,json:async()=>d};},()=>uiNow);
 assert.equal(calls,1);assert(element.innerHTML.includes('표본 부족'));
 select.value=second.version;select.listener();assert(element.innerHTML.includes('검증 기준 미충족'));assert.equal(calls,1);
 count++;console.log('PASS version switching is read-only and does not reset or refetch accounts');
 for(const fetcher of [async()=>({ok:false}),async()=>{throw Error('offline');},async()=>({ok:true,json:async()=>null})]){
  await UI.mount(element,fetcher,()=>uiNow);assert(element.innerHTML.includes('상태 자료 없음'));assert(!element.innerHTML.includes('사람 검토 후보'));
 }
 count++;console.log('PASS missing/invalid/network status leaves operating-account UI independent');
 let expiry,poll,at=uiNow,fetches=0;
 const timerNodes={},timerDocument={getElementById:()=>null},timers=vm.createContext({window:{},document:timerDocument,console,fetch:async()=>{throw Error('Unexpected fetch');},setTimeout:(fn)=>{expiry=fn;return 1;},clearTimeout(){},setInterval:(fn,ms)=>{assert.equal(ms,300000);poll=fn;return 2;},clearInterval(){}});
 vm.runInContext(fs.readFileSync(path.join(ROOT,'assets/shadow-status.js'),'utf8'),timers);
 const view={innerHTML:'',isConnected:true};
 await timers.window.ShadowStatus.mount(view,async()=>{fetches++;return {ok:true,json:async()=>passing()};},()=>at);
 assert(view.innerHTML.includes('사람 검토 후보'));at=uiNow+1800001;expiry();assert(!view.innerHTML.includes('사람 검토 후보'));assert(view.innerHTML.includes('평가 갱신 대기'));
 poll();await new Promise(resolve=>setImmediate(resolve));assert.equal(fetches,2);assert(!view.innerHTML.includes('사람 검토 후보'));
 count++;console.log('PASS open-page expiry and five-minute refresh stay read-only and hide stale eligibility');
 assert.deepEqual(files(ROOT),originalFiles);assert.deepEqual(S.runtimeHashes(ROOT),runtime);
 console.log('PASS '+count+' shadow status regression groups; original evidence and runtime unchanged.');
}
interactions().catch(e=>{console.error(e);process.exitCode=1;});
