(function(root){
  'use strict';
  const finite=Number.isFinite, clamp=(x,a,b)=>Math.max(a,Math.min(b,x));
  const validDate=d=>/^\d{4}-\d{2}-\d{2}$/.test(d)&&finite(Date.parse(d))&&new Date(d).toISOString().slice(0,10)===d;
  const age=(d,now)=> (now-Date.parse(d))/86400000;
  const fresh=(d,n,now)=>finite(age(d,now))&&age(d,now)>=0&&age(d,now)<=n;
  function history(e){
    const rows=Array.from(new Map((Array.isArray(e.history)?e.history:[]).filter(q=>q&&finite(q.close)&&q.close>0&&validDate(q.date)&&q.date<=e.asOf).map(q=>[q.date,q])).values()).sort((a,b)=>a.date.localeCompare(b.date));
    return rows.length&&rows.at(-1).date===e.asOf&&Math.abs(rows.at(-1).close/e.price-1)<.001?rows:[];
  }
  function ema(v,n){let out=[],s=0;v.forEach((x,i)=>{s=i<n?s+x:s;if(i===n-1)out.push(s/n);else if(i>=n)out.push(x*2/(n+1)+out.at(-1)*(1-2/(n+1)));});return out;}
  function indicators(e){
    const rows=history(e),v=rows.map(q=>q.close);let rsi=null,macd=null,z=null;
    if(v.length>=15){let gain=0,loss=0;for(let i=1;i<v.length;i++){const d=v[i]-v[i-1];if(i<=14){gain+=Math.max(d,0)/14;loss+=Math.max(-d,0)/14;}else{gain=(gain*13+Math.max(d,0))/14;loss=(loss*13+Math.max(-d,0))/14;}}rsi=loss===0?(gain===0?50:100):100-100/(1+gain/loss);}
    if(v.length>=35){const a=ema(v,12).slice(14),b=ema(v,26),m=b.map((x,i)=>a[i]-x);macd=m.at(-1)-ema(m,9).at(-1);}
    if(v.length>=20){const w=v.slice(-20),mean=w.reduce((a,b)=>a+b)/20,sd=Math.sqrt(w.reduce((a,b)=>a+(b-mean)**2,0)/20);z=sd?(v.at(-1)-mean)/sd:0;}
    return {rows,rsi,macd,z,relativeVolume:e.inputs?.avgVolume3m>0&&finite(e.inputs?.volume)?e.inputs.volume/e.inputs.avgVolume3m:null};
  }
  function marketState(m,now=Date.now()){
    if(!m||!fresh(m.generatedAt,3,now))return 'unknown';
    const ids=['NFCI','STLFSI4','DRTSCILM','FUNDING'];
    const valid=ids.every(id=>{const q=(m.indicators||[]).find(x=>x.id===id);return q?.status==='ready'&&fresh(q.asOf,q.maxAgeDays|| (id==='DRTSCILM'?150:id==='FUNDING'?5:16),now);});
    return valid?m.credit?.status||'unknown':m.credit?.status==='risk'?'risk':'unknown';
  }
  const POLICY=Object.freeze({version:'entry-context-v1',minScore:60,breakoutDays:55,exitDays:20,
    volumeMinimum:1.2,maximumExtension:1,maximumMA20Extension:3,stopRanges:2,
    rewardMinimum:1.5,watchRewardMinimum:2,riskMaximum:.08,watchRiskMaximum:.05});
  const mean=v=>v.length?v.reduce((a,b)=>a+b,0)/v.length:null;
  const average=(v,n)=>v.length>=n?mean(v.slice(-n)):null;
  const high=q=>finite(q.high)&&q.high>=q.close?q.high:q.close;
  const low=q=>finite(q.low)&&q.low>0&&q.low<=q.close?q.low:q.close;
  function priceRange(rows,sig,px){
    // An ATR is calculated only from complete, consistently adjusted OHLC bars.
    // Old snapshots explicitly use close-return volatility, never a fake ATR.
    const recent=rows.slice(-21);
    if(recent.length===21&&recent.every(q=>finite(q.high)&&finite(q.low)&&q.low>0&&q.low<=q.close&&q.high>=q.close)){
      const ranges=recent.slice(1).map((q,j)=>Math.max(q.high-q.low,Math.abs(q.high-recent[j].close),Math.abs(q.low-recent[j].close)));
      return {value:mean(ranges),basis:'atr20',label:'20일 평균 실제 변동폭'};
    }
    return {value:sig&&px>0?sig*px:null,basis:'close-volatility',label:'종가 수익률의 일변동폭'};
  }
  function plan(e,p,m,now=Date.now()){
    const a=e.inputs||{},px=e.price,i=indicators(e),sig=finite(a.volatility4m)&&a.volatility4m>0?a.volatility4m/Math.sqrt(252):null;
    const parts=[];for(const [ma,w] of [['ma20',10],['ma50',15],['ma200',20]])if(a[ma]>0)parts.push([px>=a[ma]?1:-1,w]);
    if(a.ma50>0&&a.ma200>0)parts.push([a.ma50>=a.ma200?1:-1,15]);
    for(const k of ['return1m','return3m'])if(finite(a[k]))parts.push([clamp(a[k]/.1,-1,1),10]);
    if(i.rsi!==null)parts.push([clamp((i.rsi-50)/20,-1,1),10]);if(i.macd!==null)parts.push([Math.sign(i.macd),10]);
    const total=parts.reduce((s,q)=>s+q[1],0),ts=total?Math.round(50+50*parts.reduce((s,q)=>s+q[0]*q[1],0)/total):50;
    // All structural levels are frozen using bars strictly before this close.
    // A broken support cannot disappear by choosing a lower level below today.
    const prior=i.rows.slice(0,-1),v=prior.map(q=>q.close),yesterday=v.at(-1),ma20=average(v,20),ma50=average(v,50);
    const prior55=prior.slice(-POLICY.breakoutDays),prior20=prior.slice(-POLICY.exitDays);
    const complete=prior55.length===POLICY.breakoutDays;
    const observedHL=complete&&prior55.every(q=>finite(q.high)&&finite(q.low)&&q.low>0&&q.low<=q.close&&q.high>=q.close);
    const breakoutLevel=complete?Math.max(...prior55.map(q=>observedHL?q.high:q.close)):null;
    const exitLevel=prior20.length===POLICY.exitDays?Math.min(...prior20.map(q=>observedHL?q.low:q.close)):null;
    const range=priceRange(i.rows,sig,px),unit=range.value;
    const state=marketState(m,now),minimum=state==='watch'?POLICY.watchRewardMinimum:POLICY.rewardMinimum;
    const riskMaximum=state==='watch'?POLICY.watchRiskMaximum:POLICY.riskMaximum;
    const upstream=ts>=POLICY.minScore&&a.ma50>0&&a.ma200>0&&px>=a.ma50&&a.ma50>=a.ma200;
    const downstream=a.ma50>0&&a.ma200>0&&px<a.ma50&&a.ma50<a.ma200&&a.return1m<0;
    const extension=unit&&breakoutLevel?(px-breakoutLevel)/unit:null;
    const maExtension=unit&&ma20?(px-ma20)/unit:null;
    const extended=maExtension>POLICY.maximumMA20Extension||(px>breakoutLevel&&extension>POLICY.maximumExtension);
    const volHistory=prior.slice(-50).map(q=>q.volume).filter(x=>finite(x)&&x>0);
    const volume=finite(i.rows.at(-1)?.volume)?i.rows.at(-1).volume:a.volume;
    const baseline=volHistory.length>=20?mean(volHistory):a.avgVolume3m;
    i.relativeVolume=baseline>0&&finite(volume)&&volume>0?volume/baseline:null;
    const levelBasis=observedHL?'일별 고가·저가':'종가';
    const levels=[ma20,ma50].filter(x=>finite(x)&&x>0);
    const support=levels.filter(x=>unit&&px>=x-unit*.5).sort((x,y)=>Math.abs(px-x)-Math.abs(px-y))[0]||ma20||null;
    const recentLow=prior.slice(-5).length?Math.min(...prior.slice(-5).map(low)):null;
    const pullLow=support&&unit?Math.max(.01,support-unit*.5):null,pullHigh=support&&unit?support+unit*.5:null;
    const pullStop=pullLow&&unit?Math.max(.01,Math.min(pullLow-unit*1.5,recentLow-unit*.25)):null;
    const target=breakoutLevel&&pullHigh&&breakoutLevel>pullHigh?breakoutLevel:null;
    const rr=target&&pullStop&&pullHigh>pullStop?(target-pullHigh)/(pullHigh-pullStop):null;
    const pullRisk=pullHigh&&pullStop?(pullHigh-pullStop)/pullHigh:null;
    const near=unit&&support&&px>=pullLow&&px<=pullHigh;
    const touched=unit&&support&&prior.slice(-3).some(q=>low(q)<=pullHigh&&low(q)>=support-unit*2);
    const rebound=near&&touched&&px>yesterday&&px>=support;
    const breakout=complete&&px>breakoutLevel;
    const breakStop=unit?Math.max(.01,px-POLICY.stopRanges*unit):null,breakRisk=unit?POLICY.stopRanges*unit/px:null;
    const limit=unit&&breakoutLevel?breakoutLevel+POLICY.maximumExtension*unit:null;
    const pullReady=upstream&&rebound&&rr>=minimum&&pullRisk<=riskMaximum&&!extended;
    // Turtle entries use price, not a mandatory volume gate. Volume is a
    // separately displayed confirmation, never substituted for missing prices.
    const breakReady=upstream&&breakout&&breakRisk<=riskMaximum&&!extended;
    const setups=[
      {key:'pullback',label:'눌림목 반등',state:pullReady?'ready':'wait',trigger:support,low:pullLow,high:pullHigh,stop:pullStop,target,rr,riskPct:pullRisk,
        reason:!upstream?'상승 추세 조건 대기':!near?'관심 구간까지 눌림 대기':!rebound?'지지 구간의 반등 종가 대기':!finite(rr)?'관측 고점까지 보상 여유 확인':rr<minimum?'관측 고점 기준 손익비 부족':pullRisk>riskMaximum?'손절까지의 위험 폭이 큼':extended?'진입가 이격이 큼':'지지 반등·손익비·위험 조건 충족'},
      {key:'breakout',label:observedHL?'55일 고점 돌파':'55일 종가 돌파',state:breakReady?'ready':'wait',trigger:breakoutLevel,low:breakoutLevel,high:limit,stop:breakStop,target:null,rr:null,riskPct:breakRisk,
        reason:!upstream?'상승 추세 조건 대기':!breakout?'직전 55거래일 고점 돌파 대기':extended?'돌파 기준에서 진입가 이격이 큼':breakRisk>riskMaximum?'변동성 손절의 위험 폭이 큼':!finite(i.relativeVolume)?'가격 돌파·위험 조건 충족 · 거래량 자료 확인':i.relativeVolume>=POLICY.volumeMinimum?'가격 돌파·위험 조건 충족 · 거래량 동반':'가격 돌파·위험 조건 충족 · 거래량 보강 없음'}
    ];
    const blocks=[];
    if(!e.fresh||!fresh(e.asOf,5,now))blocks.push('가격 데이터 갱신 필요');
    if(i.rows.length<60||!finite(px)||px<=0)blocks.push('실제 일별 종가 60개 이상 필요');
    if(!unit||!complete||!support)blocks.push('변동성·지지 자료 부족');
    const dataBlocks=[...blocks];
    let code='watch',tone='wait',reason='방향이 뚜렷해질 때까지 관찰합니다.',next='50일선 위 회복과 중기 추세 개선을 확인하세요.';
    let chosen=breakout?setups[1]:setups[0];
    if(dataBlocks.length){code='unavailable';reason=dataBlocks[0];next='최신 가격 이력과 변동폭 자료를 확인하세요.';}
    else if(state==='unknown'){code='unavailable';reason='시장 위험 데이터 확인 필요';next='시장·신용 자료가 갱신되면 다시 판단합니다.';blocks.push(reason);}
    else if(state==='risk'){code='avoid';tone='avoid';reason='시장·신용 경고: 신규 진입 보류';next='시장 위험 경고가 완화되는지 확인하세요.';blocks.push(reason);}
    else if(downstream){code='avoid';tone='avoid';reason='중기 하락 추세: 신규 진입 보류';next='50일선 회복과 중기 이동평균 배열 개선을 확인하세요.';blocks.push(reason);}
    else if(exitLevel&&px<exitLevel){code='confirm';reason='이전 20거래일 지지 이탈';next='이탈한 지지 '+exitLevel.toFixed(2)+' 위로 종가가 회복되는지 확인하세요.';blocks.push(reason);}
    else if(extended&&upstream){code='overextended';reason='진입 기준 대비 가격 이격이 큼';next='돌파 기준 또는 20일선 부근으로 가격이 안정되는지 확인하세요.';blocks.push(reason);}
    else if(breakReady||pullReady){code='buy';tone='buy';chosen=breakReady?setups[1]:setups[0];reason=chosen.reason;next='진입 구간 '+chosen.low.toFixed(2)+'–'+chosen.high.toFixed(2)+'와 무효화 기준 '+chosen.stop.toFixed(2)+'를 확인하세요.';}
    else if(upstream&&breakout){code='riskwait';chosen=setups[1];reason=chosen.reason;next='계획 위험 폭 '+(breakRisk*100).toFixed(1)+'%가 '+(riskMaximum*100)+'% 이내로 줄어드는지 확인하세요.';blocks.push(reason);}
    else if(upstream&&breakoutLevel-px<=unit){code='breakout';chosen=setups[1];reason='직전 55거래일 고점 돌파 확인 대기';next='종가가 '+breakoutLevel.toFixed(2)+' 위로 돌파하고 진입 상한 '+limit.toFixed(2)+' 이내인지 확인하세요.';blocks.push(reason);}
    else if(upstream&&px>pullHigh){code='pullback';reason='상승 추세지만 눌림목 반등 조건 대기';next='관심 구간 '+pullLow.toFixed(2)+'–'+pullHigh.toFixed(2)+'의 반등 또는 '+breakoutLevel.toFixed(2)+' 돌파를 확인하세요.';blocks.push(reason);}
    else if(upstream){code=px<pullLow?'confirm':rebound?'riskwait':'pullback';reason=chosen.reason;next='지지 '+support.toFixed(2)+'의 반등과 '+breakoutLevel.toFixed(2)+' 돌파를 확인하세요.';blocks.push(reason);}
    else{reason='상승 추세 조건이 아직 부족합니다.';blocks.push(ts<POLICY.minScore?'추세 점수가 진입 검토 기준 60에 못 미칩니다.':'중기 상승 추세 조건 미충족');}
    if(['avoid','unavailable'].includes(code))for(const setup of setups){setup.state=code==='unavailable'?'unavailable':'blocked';setup.reason=reason;}
    const holding=dataBlocks.length?{code:'unavailable',label:'판단 보류',tone:'muted',reason:'최신 종가·변동폭 자료를 확인하세요.',level:null}:
      downstream||(exitLevel&&px<exitLevel&&px<a.ma50)?{code:'reduce',label:'축소 검토',tone:'bad',reason:'중기 하락 또는 이전 지지 이탈이 확인됐습니다.',level:exitLevel}:
      px<ma20||px<a.ma50||a.ma50<a.ma200||(exitLevel&&px<exitLevel)?{code:'protect',label:'이탈 주의',tone:'warn',reason:'가격 추세가 약해져 보유 비중과 손절 기준을 확인할 구간입니다.',level:exitLevel}:
      {code:'hold',label:'추세 유지',tone:'good',reason:'가격 추세가 유지되고 있습니다. 추세 이탈 기준을 함께 확인하세요.',level:exitLevel};
    const actions={buy:'진입 검토',pullback:'눌림목 대기',breakout:'돌파 대기',riskwait:'위험 조절 대기',overextended:'추격 주의',confirm:'지지 회복 대기',avoid:'진입 보류',unavailable:'판단 보류',watch:'관망'};
    return {ts,support,buyMid:chosen.trigger,buyLow:chosen.low,buyHigh:chosen.high,stop:chosen.stop,
      target1:chosen.target,target2:null,rr:chosen.rr,action:actions[code],tone,code,sig,
      riskPct:chosen.riskPct,indicators:i,blocks,market:state,reason,next,strategy:chosen.key,setups,holding,
      breakoutLevel,exitLevel,levelBasis,range,extension,maExtension,upstream,downstream,extended,policy:POLICY.version};
  }
  const api={plan,indicators,history,marketState,POLICY};if(typeof module!=='undefined')module.exports=api;else root.TechnicalGuide=api;
})(typeof window!=='undefined'?window:globalThis);
