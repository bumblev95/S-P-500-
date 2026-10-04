(function(root){
  'use strict';
  const technical=typeof module!=='undefined'?require('./technical-guide.js'):root.TechnicalGuide;
  const learnedGuide=typeof module!=='undefined'?require('./learned-guide.js'):root.LearnedGuide;
  const visuals=typeof module!=='undefined'?require('./market-visuals.js'):root.MarketVisuals;
  const finite=Number.isFinite;
  const label='단기 추세 점수';
  const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const money=x=>finite(x)?'$'+x.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2}):'—';
  const normalize=s=>String(s||'').trim().toUpperCase().replace(/\./g,'-');
  function entry(data,symbol){const key=normalize(symbol);return data?.stocks?.[key]||data?.stocks?.[key.replace(/-/g,'.')]||null;}

  function trend(score){
    if(!finite(score))return '산출 보류';
    if(score>=78)return '강한 상승 흐름';
    if(score>=60)return '상승 흐름';
    if(score>=46)return '혼조';
    if(score>=35)return '약한 하락 흐름';
    return '하락 흐름';
  }
  function color(score){return !finite(score)?'muted':score>=60?'good':score<35?'bad':'warn';}
  function format(score){return finite(score)?score+'/100':'산출 보류';}

  // Forecast prices, valuation assumptions and model accuracy never enter this score.
  // Keep observed-price, freshness and market gates. AI research is independent:
  // failing (or passing) its horizon-specific validation never changes this plan.
  function evaluate(entry,market,learned,horizon=126,now=Date.now()){
    const e=entry||{},h=horizon===252?252:126;
    const plan=technical.plan(e,null,market,now),ai=learnedGuide.inspect(learned,e,h,now);
    const age=(now-Date.parse(e.asOf))/86400000;
    const valid=!!normalize(e.symbol)&&finite(e.price)&&e.price>0&&['ready','missing'].includes(e.status)&&e.fresh&&finite(age)&&age>=0&&age<=5&&plan.indicators.rows.length>=60;
    const score=valid&&finite(plan.ts)?plan.ts:null;
    const blocks=[...plan.blocks];
    if(!valid&&!blocks.some(x=>/가격|종가/.test(x)))blocks.unshift('추세 자료 확인 필요');
    plan.blocks=[...new Set(blocks)];
    if(score===null){
      plan.action='판단 보류';plan.tone='wait';plan.code='unavailable';plan.reason=blocks[0]||'추세 자료 확인 필요';
      plan.next='최신 가격과 일별 종가 이력을 확인하세요.';
      for(const key of ['buyMid','buyLow','buyHigh','stop','target1','target2','rr','riskPct'])plan[key]=null;
      plan.holding={code:'unavailable',label:'판단 보류',tone:'muted',reason:'보유 대응에 필요한 가격 자료가 부족합니다.',level:null};
      plan.setups=plan.setups.map(s=>({...s,state:'unavailable',reason:plan.reason}));
    }
    const decision=plan.action,reason=plan.reason;
    const modelStatus=ai.eligible?'AI 성능 기준 통과':!ai.record?'AI 검증 자료 없음':
      !ai.performancePassed?(ai.performanceStatus===false?'AI 성능 기준 미통과':'AI 성능 검증 자료 확인 필요'):ai.record.status==='eligible'?'AI 기준일·자료 확인 필요':
      ai.researchForecast?'AI 성능 기준 미통과':'AI 검증 자료 확인 필요';
    return {symbol:e.symbol||'',asOf:e.asOf||'',price:finite(e.price)?e.price:null,horizon:h,
      label,score,trend:trend(score),color:color(score),decision,reason,modelStatus,decisionBasis:'technical-rules',plan,ai};
  }
  function all(data,market,learned,horizon=126,now=Date.now()){
    return Object.fromEntries(Object.entries(data?.stocks||{}).map(([symbol,e])=>{
      const key=normalize(symbol),matched=e&&normalize(e.symbol)===key;
      return [key,evaluate(matched?e:{symbol:key},market,learned,horizon,now)];
    }));
  }
  function rank(assessments,limit=10){
    return Object.values(assessments||{}).filter(a=>finite(a.score))
      .sort(compare).slice(0,limit);
  }
  function compare(a,b,dir=-1){
    const missing=!finite(a.score),otherMissing=!finite(b.score);
    if(missing!==otherMissing)return missing?1:-1;
    return (!missing?(a.score-b.score)*dir:0)||normalize(a.symbol).localeCompare(normalize(b.symbol));
  }
  // Explain observed conditions without changing scores, forecasts or gates.
  // Data/model limitations do not consume the slots for issuer price risks.
  function signals(entry,a,market,now=Date.now()){
    const e=entry||{},i=e.inputs||{},p=a.plan,positive=[],negative=[],limitations=[];
    const add=(list,id,title,detail)=>list.push({id,title,detail});
    const percent=x=>finite(x)?(100*x).toFixed(1)+'%':'—';
    const signed=x=>(x>0?'+':'')+percent(x);
    const minimum=p.market==='watch'?2:1.5;
    if(a.score!==null){
      if(finite(i.ma50)&&i.ma50>0){
        const above=e.price>=i.ma50;
        add(above?positive:negative,'ma50',above?'현재가가 50일선 위에 있음':'현재가가 50일선 아래에 있음',
          '종가 '+money(e.price)+' · 50일 평균 '+money(i.ma50)+' · 평균 대비 '+signed(e.price/i.ma50-1));
      }
      if(finite(i.ma50)&&finite(i.ma200)&&i.ma50>0&&i.ma200>0){
        const above=i.ma50>=i.ma200;
        add(above?positive:negative,'ma-order',above?'중기 이동평균 배열이 우호적':'중기 이동평균 배열이 약함',
          '50일 평균 '+money(i.ma50)+' · 200일 평균 '+money(i.ma200));
      }
      for(const [key,name] of [['return1m','1개월'],['return3m','3개월']])if(finite(i[key])){
        add(i[key]>=0?positive:negative,key,'최근 '+name+' 수익률 '+signed(i[key]),
          e.symbol+'의 실제 종가 변화입니다. 기준일 '+e.asOf);
      }
      if(p.strategy==='pullback'&&finite(p.rr)){
        const enough=p.rr>=minimum,up=(p.target1-p.buyHigh)/p.buyHigh,down=(p.buyHigh-p.stop)/p.buyHigh;
        add(enough?positive:negative,'reward-risk','눌림목 손익비 '+p.rr.toFixed(2)+'배'+(enough?'':' · 기준 미달'),
          '관심 구간 상단 '+money(p.buyHigh)+'에서 이전 55거래일 고점 '+money(p.target1)+'까지 '+percent(up)+
          ', 재평가 '+money(p.stop)+'까지 하락폭 '+percent(down)+'. 확인 기준 '+minimum.toFixed(1)+'배입니다.');
      }else if(p.strategy==='pullback'&&!p.target1&&finite(p.buyHigh)&&finite(p.stop)){
        add(negative,'resistance-missing','눌림목 목표까지의 보상 여유 확인 필요',
          '관심 구간 상단 '+money(p.buyHigh)+' 위에 이전 55거래일 고점 목표가 없습니다. 고점 돌파 전략은 별도로 평가합니다.');
      }
      if(p.strategy==='breakout'&&p.code==='buy')add(positive,'breakout','이전 고점 돌파 확인',
        '직전 55거래일 '+p.levelBasis+' 고점 '+money(p.breakoutLevel)+'. 고정 목표 대신 추세 이탈 기준을 사용합니다.');
      if(p.strategy==='breakout'&&p.code==='buy'&&(!finite(p.indicators.relativeVolume)||p.indicators.relativeVolume<1.2))add(negative,'volume-confirm','돌파 거래량 보강 없음',
        '상대 거래량 '+(finite(p.indicators.relativeVolume)?p.indicators.relativeVolume.toFixed(2)+'배':'자료 확인 필요')+'. 가격 돌파 조건과 거래량 동반 여부를 함께 확인하세요.');
      if(finite(p.riskPct)&&p.riskPct>(p.market==='watch'?.05:.08))add(negative,'entry-risk','손절까지의 위험 폭이 큼',
        '선택 전략의 계획 위험 폭 '+percent(p.riskPct)+' · 변동폭 기준 '+p.range.label);
      if(finite(p.exitLevel)&&e.price<p.exitLevel)add(negative,'support-break','이전 20거래일 지지 이탈',
        '이전 지지 '+money(p.exitLevel)+' · 종가 '+money(e.price)+'. 이탈한 지지는 현재가 아래의 다른 값으로 바꾸지 않습니다.');
      if(finite(i.volatility4m)&&i.volatility4m>.5){
        add(negative,'volatility','변동성이 높음 · 하루 환산 약 '+percent(p.sig),
          '최근 4개월 종가에서 계산한 연환산 변동성 '+percent(i.volatility4m)+
          '. 하루 환산치는 손실 상한이 아니며 실제 움직임은 더 클 수 있습니다.');
      }
      if(p.indicators.rsi>75||p.indicators.z>2.5){
        const values=[finite(p.indicators.rsi)?'RSI '+p.indicators.rsi.toFixed(1):'',
          finite(p.indicators.z)?'20일 가격 편차 '+p.indicators.z.toFixed(2):''].filter(Boolean).join(' · ');
        add(negative,'overheated',p.extended?'진입가 이격이 큼 · 추격 주의':'단기 상승 탄력이 높음 · 이격 확인',values+'. 강한 추세에서는 RSI가 높게 유지될 수 있습니다. 진입 제한은 실제 가격 이격으로 판단합니다.');
      }
    }
    if(a.score!==null&&a.score<60)add(limitations,'weak-trend','추세 점수 진입 기준 미달 · '+a.score+'/100',
      '신규 진입 검토 기준은 60점입니다. 가격 흐름의 점수이며 상승 확률이 아닙니다.');
    if(a.ai.eligible&&a.ai.forecast.direction==='down')add(limitations,'model-down',
      (a.horizon===252?'1년':'6개월')+' AI 전망이 하락 방향 · 별도 참고',
      '검증 조건을 통과한 연구 전망은 하락 방향입니다. 단기 기술 조건과 기간·계산 근거가 다른 참고 정보입니다. 하락을 보장하는 뜻은 아닙니다.');
    if(a.score===null||p.blocks.some(b=>/가격 데이터|종가|변동성·지지|추세 자료/.test(b))){
      add(limitations,'price-data','종목 가격 자료 확인 필요',
        '기준일 '+(e.asOf||'없음')+' · 확인된 일별 종가 '+p.indicators.rows.length+'개. '+
        p.blocks.filter(b=>/가격 데이터|종가|변동성·지지|추세 자료/.test(b)).join(' · '));
    }
    if(p.market==='unknown'){
      const names={NFCI:'금융여건',STLFSI4:'금융 스트레스',DRTSCILM:'대출 태도',FUNDING:'자금조달'};
      const needs=Object.entries(names).flatMap(([id,name])=>{
        const q=market?.indicators?.find(x=>x.id===id),days=q?(now-Date.parse(q.asOf))/86400000:NaN;
        const max=q?.maxAgeDays||(id==='DRTSCILM'?150:id==='FUNDING'?5:16);
        return q?.status==='ready'&&finite(days)&&days>=0&&days<=max?[]:[name+' '+(q?.asOf||'자료 없음')];
      });
      add(limitations,'market-data','시장 상태 확인 보류 · 모든 종목 공통',
        (needs.length?'갱신이 필요한 관측 자료: '+needs.join(' · '):'시장 자료의 수집 시점·상태를 다시 확인해야 합니다.')+
        '. 자료가 부족해 시장이 안전한지 판단하지 못한 상태입니다.');
    }else if(p.market==='risk'||p.market==='watch'){
      add(limitations,'market-warning',p.market==='risk'?'시장·신용 경고 · 모든 종목 공통':'시장·신용 주의 · 모든 종목 공통',
        p.market==='risk'?'공통 시장 지표의 경고로 신규 진입을 보류합니다. 위의 시장 위험 패널에서 근거를 확인하세요.':
        '눌림목 손익비는 2.0배 이상, 두 전략의 계획 위험 폭은 5% 이내로 확인합니다.');
    }
    if(!a.ai.eligible){
      const v=a.ai.record?.validation,metrics=[];
      if(finite(v?.mae)&&finite(v?.noChangeMae))metrics.push('이 종목 과거 가격오차 '+percent(v.mae)+' · 가격 유지 기준 '+percent(v.noChangeMae));
      if(finite(v?.directionAccuracy)&&finite(v?.alwaysUpAccuracy))metrics.push('방향 적중 '+percent(v.directionAccuracy)+' · 항상 상승 기준 '+percent(v.alwaysUpAccuracy));
      if(finite(v?.dates))metrics.push('독립 검증 '+v.dates+'개 시점');
      add(limitations,'ai-validation',(a.horizon===252?'1년':'6개월')+' AI 예측 활용 보류',
        [a.ai.reason,...metrics].filter(Boolean).join('. ')+'. 검증 결과가 부족해 신규 진입 판단에 활용하지 않습니다.');
    }
    // Assign every entry blocker to one visible explanation. New or unrenderable
    // blockers remain explicit in the status panel rather than disappearing.
    const destinations={
      '가격 데이터 갱신 필요':'price-data','실제 일별 종가 60개 이상 필요':'price-data',
      '변동성·지지 자료 부족':'price-data','추세 자료 확인 필요':'price-data',
      '시장 위험 데이터 확인 필요':'market-data','시장·신용 경고: 신규 진입 보류':'market-warning',
      '실제 저항선 기준 손익비 부족':negative.some(x=>x.id==='reward-risk')?'reward-risk':'resistance-missing',
      '단기 과열: 추격 주의':'overheated','AI 예측 검증 조건 미충족':'ai-validation',
      '학습 모델 하락 우세':'model-down','추세 점수가 진입 검토 기준 60에 못 미칩니다.':'weak-trend'
    };
    for(const [index,block] of [...new Set(p.blocks)].entries()){
      let row=[...negative,...limitations].find(x=>x.id===destinations[block]);
      if(!row){
        add(limitations,'entry-blocker-'+index,block,'이 진입 조건이 충족되지 않아 신규 진입을 보류합니다.');
        row=limitations.at(-1);
      }
      (row.blocks||(row.blocks=[])).push(block);
    }
    return {positive,negative,limitations,available:a.score!==null};
  }
  function signalPanels(entry,a,market,now=Date.now()){
    const s=signals(entry,a,market,now);
    const rows=(list,tone,icon)=>list.map(x=>'<details class="signal '+tone+'" data-signal="'+esc(x.id)+'"><summary><span class="signalIcon">'+icon+
      '</span><span class="sa-signal-copy"><strong>'+esc(x.title)+'</strong></span></summary><p class="sa-signal-detail">'+esc(x.detail)+'</p></details>').join('');
    const empty=s.available?'확인한 가격 지표에서 뚜렷한 위험이 감지되지 않았습니다.':'종목별 위험 판단에 필요한 가격 자료가 부족합니다.';
    return '<div class="explainGrid sa-signals" data-signals-symbol="'+esc(entry.symbol)+'">'+
      '<section class="panel signalPanel"><h3 class="goodText">지금 좋은 신호 · '+esc(entry.symbol)+'</h3><div class="signals">'+
      (rows(s.positive,'positive','✓')||'<p>확인한 가격 지표에서 뚜렷한 긍정 신호가 없습니다.</p>')+'</div></section>'+
      '<section class="panel signalPanel sa-specific-risks"><h3 class="badText">꼭 확인할 위험 · '+esc(entry.symbol)+'</h3><div class="signals">'+
      (rows(s.negative,'negative','!')||'<p>'+empty+' 기업 실적·회사 뉴스는 별도로 확인하세요.</p>')+'</div></section></div>'+
      (s.limitations.length?'<section class="panel signalPanel sa-limitations" aria-label="진입 조건·공통 상태"><h3>진입 조건·공통 상태</h3>'+
      '<p class="sa-limitations-note">시장·AI·자료 상태 · 눌러서 근거 보기</p><div class="signals">'+
      rows(s.limitations,'caution','i')+'</div></section>':'');
  }
  // Presentation only: expose the existing plan's separate entry conditions.
  // A favourable trend must never imply that price or risk checks passed.
  function entryChecks(a){
    const p=a.plan,known=a.score!==null,threshold=p.market==='watch'?2:1.5,cap=p.market==='watch'?.05:.08;
    const zone=known&&finite(a.price)&&finite(p.buyLow)&&finite(p.buyHigh);
    const inside=zone&&a.price>=p.buyLow&&a.price<=p.buyHigh;
    const location=!zone?'자료 확인':inside?'구간 안':a.price>p.buyHigh?'구간 위':'구간 아래';
    const follow=p.strategy==='breakout',balance=known&&(follow?finite(p.riskPct):finite(p.rr));
    const reward=balance&&(follow?p.riskPct<=cap:p.rr>=threshold&&p.riskPct<=cap);
    const marketKnown=['stable','watch','risk'].includes(p.market);
    const heatKnown=known&&finite(p.maExtension),hot=p.extended;
    return [
      {key:'trend',label:'최근 가격 흐름',state:!known?'확인 필요':a.trend,tone:!known?'muted':a.color,
        detail:known?'추세 '+format(a.score)+' · 50·200일선 배열 '+(p.upstream?'충족':'확인 필요'):'최신 가격·종가 이력 확인 필요'},
      {key:'price',label:'진입 가격',state:location,tone:!zone?'muted':inside?'good':'warn',
        detail:'관심 구간 '+money(p.buyLow)+'–'+money(p.buyHigh)+' · 종가 '+money(a.price)},
      {key:'balance',label:follow?'돌파 위험 관리':'눌림목 손익비',state:!balance?'확인 필요':reward?'충족':'부족',tone:!balance?'muted':reward?'good':'warn',
        detail:!balance?'선택 전략의 가격·변동폭 자료 확인 필요':follow?'계획 위험 '+(p.riskPct*100).toFixed(1)+'% / 상한 '+(cap*100)+'% · 고정 목표 대신 추세 이탈 청산':
          '손익비 '+p.rr.toFixed(2)+' / 기준 '+threshold+' 이상 · 이전 55거래일 고점 기준'},
      {key:'market',label:'시장 위험',state:!marketKnown?'확인 필요':p.market==='risk'?'경보':p.market==='watch'?'주의':'경고 없음',
        tone:!marketKnown?'muted':p.market==='risk'?'bad':p.market==='watch'?'warn':'good',
        detail:!marketKnown?'최신 시장 위험 자료 확인 필요':p.market==='risk'?'시장·신용 경고로 신규 진입 보류':p.market==='watch'?'계획 위험 폭 5% 이내 · 눌림목 손익비 2 이상':'관측 지표 기준'},
      {key:'heat',label:'진입가 이격',state:!heatKnown?'확인 필요':hot?'추격 주의':'허용 범위',tone:!heatKnown?'muted':hot?'warn':'good',
        detail:heatKnown?'20일선에서 변동폭 '+p.maExtension.toFixed(1)+'배 · RSI '+(finite(p.indicators.rsi)?p.indicators.rsi.toFixed(1):'확인 필요'):'최신 종가 이력 확인 필요'}
    ];
  }
  function aiReference(a){
    const down=a.ai.eligible&&a.ai.forecast?.direction==='down';
    return {label:(a.horizon===252?'1년':'6개월')+' AI 연구 · 별도 상태',
      state:down?'하락 전망':a.ai.eligible?'검증 기준 통과':a.modelStatus==='AI 성능 기준 미통과'?'검증 미통과':'자료 확인',
      tone:down?'warn':a.ai.eligible?'info':a.modelStatus==='AI 성능 기준 미통과'?'warn':'muted',detail:a.ai.reason};
  }
  function entryExplanation(a){
    const descriptions={
      '실제 저항선 기준 손익비 부족':'가까운 저항까지의 상승폭이 재평가 기준까지의 하락폭에 비해 작습니다.',
      '단기 과열: 추격 주의':'가격이 단기에 과열되어 추격 매수를 기다립니다.',
      '시장 위험 데이터 확인 필요':'최신 시장 위험 자료를 확인할 때까지 매수를 기다립니다.',
      '추세 점수가 진입 검토 기준 60에 못 미칩니다.':'최근 가격 흐름이 진입 검토 기준에 못 미칩니다.'
    };
    return descriptions[a.reason]||a.reason;
  }
  function setupPanels(a){
    const p=a.plan,names={ready:'조건 충족',wait:'조건 대기',blocked:'진입 차단',unavailable:'자료 확인'};
    return '<div class="sa-setup-grid" aria-label="두 가지 진입 전략">'+p.setups.map(s=>{
      const tone=s.state==='ready'?'good':s.state==='blocked'?'bad':s.state==='unavailable'?'muted':'warn';
      const valid=s.state!=='unavailable',follow=s.key==='breakout';
      return '<section class="sa-setup sa-setup-'+tone+'" data-setup="'+s.key+'" data-setup-state="'+s.state+'"><div class="sa-check-title"><h3>'+esc(s.label)+'</h3>'+visuals.badge(names[s.state],tone)+'</div><p>'+esc(s.reason)+'</p><dl>'+[
        ['관심 구간',valid?money(s.low)+'–'+money(s.high):'자료 확인'],
        ['무효화 기준',valid?money(s.stop):'자료 확인'],
        [follow?'청산 방식':'관측 고점 목표',valid?(follow?'추세 이탈 · '+money(p.exitLevel):money(s.target)):'자료 확인'],
        [follow?'거래량 보강':'손익비',valid?(follow?(finite(p.indicators.relativeVolume)?p.indicators.relativeVolume.toFixed(2)+'배 · 보강 1.2배':'자료 확인'):(finite(s.rr)?s.rr.toFixed(2)+'배 / 기준 '+(p.market==='watch'?2:1.5)+'배':'보상 여유 확인')):'자료 확인']
      ].map(([k,v])=>'<div><dt>'+esc(k)+'</dt><dd>'+esc(v)+'</dd></div>').join('')+'</dl></section>';
    }).join('')+'</div>';
  }
  function holdingPanel(a){
    const h=a.plan.holding;
    return '<section class="sa-holding" data-holding-state="'+h.code+'" aria-label="보유 중 대응"><div class="sa-check-title"><h3>이미 보유 중이라면</h3>'+(h.code==='unavailable'?visuals.badge('판단 보류','muted'):'')+'</div>'+visuals.steps([
      {key:'hold',label:'추세 유지',tone:'good'},{key:'protect',label:'이탈 주의',tone:'warn'},{key:'reduce',label:'축소 검토',tone:'bad'}
    ],h.code,'보유 중 대응')+(finite(h.level)?'<small>추세 이탈 기준 <b>'+money(h.level)+'</b> · 매수가 별도 확인</small>':'')+'</section>';
  }
  // Display categories, not a numeric buy probability. All nine real states
  // stay visible; native disclosures explain a state without changing it.
  const entryStates=Object.freeze([
    {key:'avoid',label:'진입 보류',tone:'bad',icon:'<circle cx="12" cy="12" r="8"/><path d="m6 18 12-12"/>',meaning:'하락 추세 또는 시장 경보. 신규 진입을 미룹니다.'},
    {key:'watch',label:'관망',tone:'warn',icon:'<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>',meaning:'상승·하락 신호가 섞여 방향을 더 확인합니다.'},
    {key:'buy',label:'진입 검토',tone:'good',icon:'<circle cx="12" cy="12" r="9"/><path d="m7 12 3 3 7-7"/>',meaning:'돌파 또는 눌림 반등과 위험 조건이 충족됐습니다.'},
    {key:'pullback',label:'눌림목 대기',tone:'warn',icon:'<path d="m3 6 7 10 10-10m-6 0h6v6"/>',meaning:'상승 추세에서 관심 가격까지 내려오기를 기다립니다.'},
    {key:'breakout',label:'돌파 대기',tone:'warn',icon:'<path d="M3 12h18M12 21V3m-5 5 5-5 5 5"/>',meaning:'이전 고점을 넘는 종가를 기다립니다.'},
    {key:'confirm',label:'지지 회복 대기',tone:'warn',icon:'<path d="M3 20h18M12 16V3m-5 5 5-5 5 5"/>',meaning:'이탈한 지지 가격 위로 회복하는지 확인합니다.'},
    {key:'overextended',label:'추격 주의',tone:'warn',icon:'<path d="m3 18 6-6 4 3 8-12m-6 0h6v6M5 3v4m0 3v.1"/>',meaning:'가격이 많이 올라 바로 따라 사기에는 이격이 큽니다.'},
    {key:'riskwait',label:'위험 조절 대기',tone:'warn',icon:'<path d="m12 2 8 4v6c0 5-8 10-8 10S4 17 4 12V6l8-4Zm0 5v6m0 3v.1"/>',meaning:'손절까지의 가격 폭이나 손익비가 기준에 맞지 않습니다.'},
    {key:'unavailable',label:'판단 보류',tone:'muted',icon:'<circle cx="12" cy="12" r="9"/><path d="M9 8a3 3 0 0 1 6 0c0 2-3 2-3 5m0 3v.1"/>',meaning:'가격 또는 시장 자료가 부족해 판단을 기다립니다.'}
  ].map(s=>Object.freeze(s)));
  function entryVisual(a){
    const code=a.plan.code,group=code==='buy'?'buy':code==='avoid'?'avoid':entryStates.some(s=>s.key===code&&s.tone==='warn')?'wait':null;
    const groups=[{key:'avoid',label:'진입 보류',tone:'bad'},{key:'wait',label:'조건 대기',tone:'warn'},{key:'buy',label:'진입 검토',tone:'good'}];
    const dial=visuals.gauge({title:'신규 진입 판단',states:groups,index:groups.findIndex(s=>s.key===group),value:a.decision})
      .replace('<strong ','<strong data-entry-state="'+esc(code)+'" ');
    return '<div class="sa-decision-visual"><div class="sa-decision-dial">'+dial+'</div><section class="sa-state-legend" aria-label="전체 판단 종류"><div class="sa-legend-heading"><b>9가지 판단</b><small>눌러서 뜻 보기</small></div><div class="sa-state-map">'+entryStates.map(s=>{
      const current=s.key===code;
      return '<details class="sa-state-card sa-state-'+s.tone+(current?' sa-state-current':'')+'" name="sa-states-'+esc(normalize(a.symbol))+'" data-state-option="'+s.key+'"><summary'+(current?' aria-current="true"':'')+' aria-label="'+esc(s.label+(current?' · 현재 판단':''))+'"><svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'+s.icon+'</svg><span>'+esc(s.label.replaceAll(' ',''))+'</span>'+(current?'<i aria-hidden="true">✓</i>':'')+'</summary><p>'+esc(s.meaning)+'</p></details>';
    }).join('')+'</div></section></div>';
  }
  function shortReason(a){
    const p=a.plan,cap=p.market==='watch'?5:8;
    if(p.code==='buy')return p.strategy==='breakout'?'고점 돌파 + 위험 조건 충족':'눌림 반등 + 위험 조건 충족';
    if(p.code==='avoid')return p.market==='risk'?'시장 위험 경보':'중기 하락 추세';
    if(p.code==='riskwait')return finite(p.riskPct)&&p.riskPct*100>cap?'손절 폭 '+(p.riskPct*100).toFixed(1)+'% · 기준 '+cap+'%':finite(p.rr)?'손익비 '+p.rr.toFixed(1)+'배 · 기준 '+(p.market==='watch'?2:1.5)+'배':'위험 조건 확인 필요';
    if(p.code==='unavailable')return a.score===null?'가격 자료 확인 필요':p.market==='unknown'?'시장 자료 확인 필요':'가격·변동폭 자료 확인 필요';
    return {watch:'상승·하락 신호가 섞임',pullback:'관심 가격까지 눌림 대기',breakout:'이전 고점 돌파 전',overextended:'가격이 많이 올라 추격 주의',confirm:'지지 가격 회복 전'}[p.code]||a.reason;
  }
  function panel(a){
    const p=a.plan,reference=aiReference(a);
    return '<section class="stockAssessment" data-decision-basis="technical-rules" aria-label="'+esc(a.symbol)+' 공통 평가">'+
      '<div class="sa-heading"><small>'+esc(a.symbol)+' · 매수 전 확인</small>'+
      '<span class="sa-date">종가 '+esc(a.asOf||'확인 필요')+'</span></div>'+
      entryVisual(a)+'<p class="sa-reason sa-short-reason">'+esc(shortReason(a))+'</p>'+
      '<div class="sa-context"><div><small>추세 점수</small>'+visuals.badge(a.trend.replace(' 흐름','').replaceAll(' ','')+(finite(a.score)?'·'+a.score:''),a.color)+'</div><div><small>진입 전략</small>'+visuals.badge(p.code==='unavailable'?'자료 확인':p.strategy==='breakout'?'고점 돌파':'눌림목 반등',p.code==='buy'?'good':p.code==='unavailable'?'muted':'info')+'</div></div>'+
      '<dl class="sa-price-strip">'+[['기준 가격',money(a.price)],['관심 가격',finite(p.buyLow)&&finite(p.buyHigh)?money(p.buyLow)+'–'+money(p.buyHigh):'—'],['손절 기준',money(p.stop)]].map(([k,v])=>'<div><dt>'+k+'</dt><dd>'+esc(v)+'</dd></div>').join('')+'</dl>'+holdingPanel(a)+
      '<details class="sa-condition-details"><summary>가격·판단 근거 자세히</summary><p class="sa-full-reason">'+esc(entryExplanation(a))+'</p><p class="sa-next"><b>다음 확인 조건</b><span>'+esc(p.next)+'</span></p>'+setupPanels(a)+'<div class="sa-entry-layout"><div class="sa-conditions"><ul class="sa-checks">'+entryChecks(a).map(c=>'<li data-entry-check="'+c.key+'"><div class="sa-check-title"><span>'+esc(c.label)+'</span>'+visuals.badge(c.state,c.tone)+'</div><p>'+esc(c.detail)+'</p></li>').join('')+'</ul></div></div><p class="sa-note">'+esc(p.holding.reason)+' 매수가·보유 비중·개인 손절 기준은 별도 확인하세요.</p><p class="sa-note">변동폭: '+esc(p.range.label)+'</p></details>'+
      '<details class="sa-ai-status" data-ai-reference="'+(a.ai.eligible?'eligible':'unavailable')+'" aria-label="AI 연구 참고 상태"><summary class="sa-check-title"><h3>'+esc(reference.label.replace(' · 별도 상태',''))+'</h3>'+visuals.badge(reference.state,reference.tone)+'</summary><p>'+esc(reference.detail)+'</p><p class="sa-note">위 진입 조건은 기술·가격 자료로 판단합니다. AI 연구는 추가 참고 정보로 확인하세요.</p></details>'+
      '<details class="sa-trend-details"><summary>추세 점수 · '+esc(format(a.score))+'</summary><p class="sa-note">최근 가격의 상승·하락 흐름을 평가한 점수입니다. 95점은 상승 확률 95%나 매수 추천 95점이라는 뜻이 아닙니다. 신규 매수는 위 진입 조건을 함께 확인하세요.</p><div class="sa-score" data-trend-symbol="'+esc(a.symbol)+'" data-trend-score="'+(a.score??'')+'">'+visuals.trendGauge(a.score,a.trend)+'</div></details>'+
      '<div class="sa-meta"><span>규칙 기반 · 매매 성과 미검증</span></div></section>';
  }
  async function load(fetcher=root.fetch.bind(root),decisionSupport=root.DecisionSupport){
    const urls=['forecasts/latest.json','market/latest.json','ml/latest.json'];
    const results=await Promise.allSettled(urls.map(async url=>{
      const r=await fetcher(url,{cache:'no-store'});if(!r.ok)throw Error(url);return r.json();
    }));
    const values=results.map(r=>r.status==='fulfilled'?r.value:null);
    // Reuse the existing prospective-promotion guard on every connected page.
    if(decisionSupport){await decisionSupport.load();values[2]=decisionSupport.applyStocks(values[2]);}
    return {data:values[0],market:values[1],learned:values[2],errors:results.flatMap((r,i)=>
      r.status==='rejected'?[['추세 자료 읽기 실패','시장 자료 읽기 실패','AI 검증 자료 읽기 실패'][i]]:[])};
  }
  const api={label,normalize,entry,trend,color,format,evaluate,all,rank,compare,entryChecks,aiReference,entryExplanation,entryStates,entryVisual,shortReason,panel,setupPanels,holdingPanel,signals,signalPanels,load};
  if(typeof module!=='undefined')module.exports=api;else root.StockAssessment=api;
})(typeof window!=='undefined'?window:globalThis);
