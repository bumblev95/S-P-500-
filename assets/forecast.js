(function () {
  'use strict';
  const root = document.getElementById('forecastPanel');
  if (!root) return;
  const bridge = window.forecastBridge;
  const labels = {21:'1개월',84:'4개월',252:'1년'};
  const directions = {up:'상승 우세',neutral:'방향 혼재',down:'하락 우세'};
  const esc = value => String(value == null ? '' : value).replace(/[&<>"']/g,
    ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const amount = value => Number.isFinite(value) ? value.toLocaleString('en-US',
    {minimumFractionDigits:2,maximumFractionDigits:2}) : '—';
  const percent = (value, signed=false) => Number.isFinite(value) ?
    (signed && value > 0 ? '+' : '') + (value*100).toFixed(1) + '%' : '—';
  const finite = Number.isFinite;
  const embedded=document.getElementById('forecastEmbeddedData');
  let data = null, error = '', loading = false, symbol = bridge.selected() || 'NVDA', horizon = 84;
  let lastBridgeSymbol = bridge.selected();
  try {
    const pref = JSON.parse(localStorage.getItem('sp500.forecast.preferences.v1') || '{}');
    if (!lastBridgeSymbol && pref.symbol) symbol = pref.symbol;
    if (labels[pref.horizon]) horizon = Number(pref.horizon);
  } catch (_) { /* Device preferences are optional. */ }

  function remember() {
    try { localStorage.setItem('sp500.forecast.preferences.v1',JSON.stringify({symbol,horizon})); }
    catch (_) { /* Forecast records are preserved by the scheduled data job. */ }
  }
  function badge(signal) {
    return '<span class="fc-badge fc-'+esc(signal)+'">'+esc(directions[signal] || signal)+'</span>';
  }
  function age(entry) {
    const t = Date.parse(entry.asOf + 'T00:00:00Z');
    return finite(t) ? Math.floor((Date.now()-t)/86400000) : Infinity;
  }
  function chart(entry, pred) {
    const history = (entry.history || []).slice(-63);
    const past = history.length > 1 ? history.length - 1 : 0;
    const steps = Array.from({length:25},(_,i)=>horizon*i/24);
    const future = steps.map(t => {
      const center = pred.dailyDrift*63*(1-Math.exp(-t/63));
      const spread = pred.volatility*Math.sqrt(t/252);
      return {t,base:pred.anchor*Math.exp(center),bear:pred.anchor*Math.exp(center-spread),
        bull:pred.anchor*Math.exp(center+spread)};
    });
    const values = history.map(p=>p.close).concat(future.flatMap(p=>[p.bear,p.bull]));
    let lo = Math.min(...values), hi = Math.max(...values);
    if (!(lo>0) || !finite(hi)) return '';
    const pad = Math.max((Math.log(hi)-Math.log(lo))*.1,.025);
    lo = Math.log(lo)-pad; hi = Math.log(hi)+pad;
    const mobile=window.innerWidth<600;
    const width=mobile?Math.max(230,root.clientWidth-40):650;
    const height=mobile?255:290,left=mobile?62:82,right=16,top=16,bottom=48;
    const x=t=>left+(t+past)/(horizon+past)*(width-left-right);
    const y=p=>top+(hi-Math.log(p))/(hi-lo)*(height-top-bottom);
    const point=(t,p)=>x(t).toFixed(2)+','+y(p).toFixed(2);
    let svg='<svg viewBox="0 0 '+width+' '+height+'" role="img" aria-labelledby="fcChartTitle fcChartDesc">';
    svg+='<title id="fcChartTitle">'+esc(symbol)+' '+labels[horizon]+' 가격 시나리오</title>';
    svg+='<desc id="fcChartDesc">기준 '+amount(pred.base)+', 약세 '+amount(pred.bear)+
      ', 강세 '+amount(pred.bull)+'. 가격은 로그 축으로 표시합니다. 범위는 확률 구간이 아닙니다.</desc>';
    for(let i=0;i<5;i++){
      const value=Math.exp(lo+(hi-lo)*i/4),yy=y(value);
      const tick=value>=1e6?(value/1e6).toFixed(1)+'M':value>=1e3?(value/1e3).toFixed(1)+'k':amount(value);
      svg+='<line x1="'+left+'" y1="'+yy+'" x2="'+(width-right)+'" y2="'+yy+
        '" stroke="#20344a"/><text x="'+(left-9)+'" y="'+(yy+5)+'" text-anchor="end">'+tick+'</text>';
    }
    const polygon = future.map(p=>point(p.t,p.bull)).concat(
      future.slice().reverse().map(p=>point(p.t,p.bear))).join(' ');
    svg+='<polygon points="'+polygon+'" fill="#124568" fill-opacity=".6"/>';
    for(const key of ['bear','bull']){
      svg+='<polyline points="'+future.map(p=>point(p.t,p[key])).join(' ')+
        '" fill="none" stroke="#507c9b" stroke-dasharray="4 5"/>';
    }
    if(history.length>1){
      svg+='<polyline points="'+history.map((p,i)=>point(i-past,p.close)).join(' ')+
        '" fill="none" stroke="#d0dce9" stroke-width="2.2"/>';
    }
    svg+='<polyline points="'+future.map(p=>point(p.t,p.base)).join(' ')+
      '" fill="none" stroke="#81d5fb" stroke-width="3" stroke-dasharray="7 4"/>';
    svg+='<line x1="'+x(0)+'" y1="'+top+'" x2="'+x(0)+'" y2="'+(height-bottom)+
      '" stroke="#859fb8" stroke-dasharray="3 5"/>';
    svg+='<circle cx="'+x(0)+'" cy="'+y(pred.anchor)+'" r="4" fill="#eff7ff"/>';
    svg+='<text x="'+x(0)+'" y="'+(height-23)+'" text-anchor="'+(past?'middle':'start')+
      '">기준일</text><text x="'+x(horizon)+'" y="'+(height-23)+'" text-anchor="end">+'+
      labels[horizon]+'</text>';
    if(past) svg+='<text x="'+left+'" y="'+(height-23)+'" text-anchor="start">'+
      esc(history[0].date.slice(5))+'</text>';
    return svg+'</svg><div class="fc-legend">'+(past?'<span class="fc-actual">과거 종가</span>':'')+
      '<span>기준 전망</span><span class="fc-band">변동성 시나리오</span></div>';
  }

  function reasons(entry) {
    const a=entry.inputs, positive=[],negative=[],context=[];
    const add=(condition,text)=> (condition?positive:negative).push(text);
    if(finite(a.return3m)) add(a.return3m>=0,'최근 3개월 수익률 '+percent(a.return3m,true));
    if(a.ma50>0) add(entry.price>=a.ma50,'50일 평균보다 '+percent(Math.abs(entry.price/a.ma50-1))+
      (entry.price>=a.ma50?' 위':' 아래'));
    if(a.ma50>0 && a.ma200>0) add(a.ma50>=a.ma200,'50일 평균이 200일 평균'+
      (a.ma50>=a.ma200?' 위에 있음':' 아래에 있음'));
    const market = data.stocks.SPY;
    if(symbol!=='SPY' && market && market.asOf===entry.asOf &&
       finite(market.inputs.return3m) && finite(a.return3m)){
      const relative=a.return3m-market.inputs.return3m;
      context.push('S&P 500 ETF 대비 3개월 수익률 '+percent(relative,true)+'p (보조 정보)');
    }
    if(a.avgVolume3m>0 && finite(a.volume))
      context.push('최근 거래량은 3개월 평균의 '+(a.volume/a.avgVolume3m).toFixed(2)+'배');
    return {positive,negative,context};
  }
  const list = (items, fallback) => '<ul>'+ (items.length?items:[fallback])
    .map(t=>'<li>'+esc(t)+'</li>').join('')+'</ul>';

  function stats(entry) {
    const check=entry.backtest[String(horizon)],live=entry.issued[String(horizon)];
    const enough=check.n>=8;
    const result=check.n ? (check.maePct<check.baselineMaePct?'기준모형보다 오차 작음':'기준모형보다 오차 큼') :
      '과거 검증 데이터 대기';
    let out='<details class="fc-validation"><summary>예측 성적 · '+esc(result)+
      (check.n?' · '+check.n+'건':'')+'</summary>';
    if(check.n){
      out+='<p class="fc-help">'+esc(check.firstDate)+' ~ '+esc(check.lastDate)+
        ' · 예측 기간이 겹치지 않는 과거 검증'+(enough?'':' · 표본이 적어 판단 보류')+'</p>'+
        '<div class="fc-statgrid"><div class="fc-stat"><span>평균 가격 오차</span><strong>'+
        percent(check.maePct)+'</strong></div><div class="fc-stat"><span>가격 유지 기준모형 오차</span><strong>'+
        percent(check.baselineMaePct)+'</strong></div><div class="fc-stat"><span>방향 일치율 · 3분류</span><strong>'+
        percent(check.directionAccuracy)+'</strong></div></div>'+
        '<p class="fc-help">범위 안에 실제 가격이 들어온 비율 '+percent(check.rangeCoverage)+
        '. 이 과거 비율은 다음 예측의 성공 확률이 아닙니다.</p>';
    }else{
      out+='<p class="fc-help">과거 종가가 쌓이면 같은 모델을 과거 시점부터 검증합니다. 확인되지 않은 정확도는 표시하지 않습니다.</p>';
    }
    out+='<h3 style="margin-top:18px">발행 후 실제 결과</h3><p class="fc-meta">평가 완료 '+
      live.n+'건 · 만기 대기 '+live.pending+'건'+(live.revised?' · 주가 수정으로 평가 제외 '+live.revised+'건':'')+'</p>';
    if(live.n) out+='<p class="fc-help">평균 가격 오차 '+percent(live.maePct)+' · 방향 일치율 '+
      percent(live.directionAccuracy)+' · 매일 발행한 예측은 평가 기간이 겹칠 수 있습니다.</p>';
    return out+'</details>';
  }

  function controls() {
    const names=new Map(bridge.stocks().map(s=>[s.symbol,s.name]));
    const symbols=data?Object.keys(data.stocks).sort():[];
    return '<header class="fc-header"><div><h2>가격·방향 전망</h2>'+
      '<div class="fc-caption">가격 기반 모델 · 실적·뉴스 미반영</div></div>'+
      '<div class="fc-controls"><label><span class="sr-only">전망 종목</span>'+
      '<select id="fcSymbol" aria-label="전망 종목">'+symbols.map(s=>'<option value="'+esc(s)+'"'+
        (s===symbol?' selected':'')+'>'+esc(s+' · '+(names.get(s)||s))+'</option>').join('')+
      '</select></label><div class="fc-periods" role="group" aria-label="예측 기간">'+
      Object.entries(labels).map(([h,label])=>'<button type="button" data-fc-horizon="'+h+
        '" aria-pressed="'+(Number(h)===horizon)+'">'+label+'</button>').join('')+
      '</div><button class="fc-refresh" type="button" data-fc-reload '+
      (loading?'disabled':'')+'>'+(loading?'불러오는 중…':embedded?'다시 보기':'새로고침')+'</button></div></header>';
  }

  function render() {
    if(!data){
      root.innerHTML='<div class="fc-empty" role="status"><strong>가격·방향 전망</strong><p class="'+
        (error?'fc-error':'')+'">'+esc(error||'전망 데이터를 불러오고 있습니다.')+
        '</p>'+(error?'<button class="fc-refresh" type="button" data-fc-reload>다시 불러오기</button>':'')+'</div>';
      return;
    }
    const entry=data.stocks[symbol];
    if(!entry){
      root.innerHTML=controls()+'<div class="fc-empty">이 종목의 예측 입력 데이터가 아직 없습니다. 다른 종목을 선택하세요.</div>';
      return;
    }
    const pred=entry.predictions[String(horizon)];
    const stale=entry.status==='stale'||age(entry)>5||age(entry)<0;
    let out=controls()+'<div class="fc-body"><div class="fc-topline"><span class="fc-ticker">'+esc(symbol)+
      '</span>'+(stale?'<span class="fc-badge fc-caution">기준 종가 갱신 필요</span>':pred?badge(pred.direction):
        '<span class="fc-badge">데이터 부족</span>')+'<span class="fc-meta">기준 종가 '+amount(entry.price)+
      ' · '+esc(entry.asOf)+'</span></div>';
    if(stale||!pred){
      out+='<div class="fc-empty">'+(stale?'최근 종가가 확인될 때까지 새 전망을 표시하지 않습니다.':
        '수익률 또는 변동성 자료가 부족해 이 종목의 전망을 계산하지 않았습니다.')+'</div>';
      root.innerHTML=out+'</div>';
      return;
    }
    out+='<div class="fc-main"><div class="fc-chart">'+chart(entry,pred)+
      '<p class="fc-help">로그 가격축 · '+horizon+'거래일 후 · 가격은 종목의 거래 통화 기준</p></div>'+
      '<div><div class="fc-scenarios">';
    for(const [key,label] of [['bear','약세 시나리오'],['base','기준 전망'],['bull','강세 시나리오']]){
      out+='<div class="fc-scenario fc-'+key+'"><span>'+label+'</span><strong>'+amount(pred[key])+
        '</strong><span class="fc-caption">기준 종가 대비 '+percent(pred[key]/pred.anchor-1,true)+'</span></div>';
    }
    out+='</div><p class="fc-help">범위는 과거 변동성을 적용한 조건별 시나리오입니다. 상승 확률이나 보장된 가격 구간을 뜻하지 않습니다.</p>';
    const previous=entry.previous[String(horizon)];
    if(previous) out+='<p class="fc-help">직전 전망 '+esc(previous.asOf)+' · '+esc(directions[previous.direction])+
      (previous.direction===pred.direction?' 유지':' → '+esc(directions[pred.direction]))+'</p>';
    out+='</div></div>';
    const why=reasons(entry);
    out+='<div class="fc-reasons"><div><h3>상승을 지지하는 신호</h3>'+
      list(why.positive,'뚜렷한 상승 신호가 없습니다.')+'</div><div><h3>하락을 지지하는 신호</h3>'+
      list(why.negative,'뚜렷한 하락 신호가 없습니다.')+'</div></div>';
    if(why.context.length) out+='<p class="fc-help">'+why.context.map(esc).join(' · ')+'</p>';
    const ma=entry.inputs.ma50;
    out+='<div class="fc-condition"><strong>전망 재검토 조건</strong><br>'+
      (ma>0?'종가가 50일 평균 '+amount(ma)+(entry.price>=ma?' 아래로 내려가거나':' 위로 올라가거나')+' ':'')+
      '최근 1개월 수익률의 부호가 바뀌면 추세를 다시 확인하세요.</div>'+stats(entry)+
      '<details class="fc-method"><summary>계산 방법과 데이터 기준</summary>'+
      '<p>1·3·6개월 과거 수익률을 가중 평균하고, 그 추세를 35%만 반영합니다. 추세 영향은 시간이 지날수록 약해집니다. '+
      '약세·강세 범위는 최근 84거래일의 변동성 1배를 기간에 맞춰 적용합니다.</p>'+
      '<p>방향은 기준 전망의 변화가 +2% 초과면 상승, −2% 미만이면 하락, 그 사이는 방향 혼재입니다. '+
      '모델과 가중치는 고정되어 있으며 아직 확률을 보정한 모델이 아닙니다.</p>'+
      '<p>기존 표의 적정가·EPS 가정과 독립된 종가 기반 전망입니다. 표의 수동 가격 변경은 이 전망에 반영하지 않습니다. '+
      '배당은 제외하며, 과거 종가는 제공처의 주식분할·수정에 따라 바뀔 수 있습니다.</p>'+
      '<p>출처: '+esc(entry.source)+' · 자료 기준 '+esc(entry.asOf)+' · 계산 '+
      esc(data.generatedAt)+' · 모델 '+esc(data.model)+'</p></details></div>';
    root.innerHTML=out;
  }

  async function reload() {
    if(loading) return;
    loading=true;error='';render();
    try {
      let incoming;
      if(embedded){
        incoming=JSON.parse(embedded.textContent);
      }else{
        const response=await fetch('forecasts/latest.json',{cache:'no-store'});
        if(!response.ok) throw new Error('HTTP '+response.status);
        incoming=await response.json();
      }
      if(incoming.schemaVersion!==1 || !incoming.stocks || !Object.keys(incoming.stocks).length)
        throw new Error('invalid data');
      data=incoming;
      if(!data.stocks[symbol] && !bridge.selected()) symbol=Object.keys(data.stocks)[0];
    }catch(_){
      error='전망 데이터를 불러오지 못했습니다. 연결 상태와 최근 데이터 갱신을 확인하세요.';
      data=null;
    }finally{loading=false;render();}
  }
  root.addEventListener('click',event=>{
    const period=event.target.closest('[data-fc-horizon]');
    if(period){horizon=Number(period.dataset.fcHorizon);remember();render();}
    if(event.target.closest('[data-fc-reload]')) reload();
  });
  root.addEventListener('change',event=>{
    if(event.target.id==='fcSymbol'){
      symbol=event.target.value;lastBridgeSymbol=symbol;remember();
      bridge.select(symbol);render();
    }
  });
  window.StockForecast={
    refresh(){
      const selected=bridge.selected();
      if(selected && selected!==lastBridgeSymbol){symbol=selected;lastBridgeSymbol=selected;remember();}
      render();
    }
  };
  let resizeTimer;
  window.addEventListener('resize',()=>{
    clearTimeout(resizeTimer);resizeTimer=setTimeout(render,150);
  });
  reload();
}());
