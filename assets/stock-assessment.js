(function(root){
  'use strict';
  const technical=typeof module!=='undefined'?require('./technical-guide.js'):root.TechnicalGuide;
  const learnedGuide=typeof module!=='undefined'?require('./learned-guide.js'):root.LearnedGuide;
  const visuals=typeof module!=='undefined'?require('./market-visuals.js'):root.MarketVisuals;
  const finite=Number.isFinite;
  const label='단기 추세 점수';
  const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const money=x=>finite(x)?'$'+x.toLocaleString('en-US',{maximumFractionDigits:2}):'—';
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
  // Keep the established technical calculation and its conservative entry gates.
  function evaluate(entry,market,learned,horizon=126,now=Date.now()){
    const e=entry||{},h=horizon===252?252:126;
    const plan=technical.plan(e,null,market,now),ai=learnedGuide.inspect(learned,e,h,now);
    const age=(now-Date.parse(e.asOf))/86400000;
    const valid=!!normalize(e.symbol)&&e.status==='ready'&&e.fresh&&finite(age)&&age>=0&&age<=5&&plan.indicators.rows.length>=60;
    const score=valid&&finite(plan.ts)?plan.ts:null;
    const blocks=[...plan.blocks];
    if(!valid&&!blocks.some(x=>/가격|종가/.test(x)))blocks.unshift('추세 자료 확인 필요');
    if(!ai.eligible)blocks.push('AI 예측 검증 조건 미충족');
    const down=ai.eligible&&ai.forecast.direction==='down';
    if(down)blocks.unshift('학습 모델 하락 우세');
    if(score!==null&&score<60)blocks.push('추세 점수가 진입 검토 기준 60에 못 미칩니다.');
    plan.blocks=[...new Set(blocks)];
    if(score===null){plan.action='자료 확인 · 판단 보류';plan.tone='wait';plan.code='unavailable';}
    else if(plan.tone==='avoid'||down){plan.action='신규 진입 보류';plan.tone='avoid';plan.code='avoid';}
    else if(plan.blocks.length){plan.action='조건 확인 · 관망';plan.tone='wait';plan.code='watch';}
    const decision=plan.code==='unavailable'?'판단 보류':plan.code==='avoid'?'진입 보류':plan.code==='buy'?'진입 검토':'관망';
    const reason=plan.code==='avoid'&&plan.market==='risk'?'시장·신용 경고: 신규 진입 보류':
      plan.code==='avoid'&&score<35?'하락 흐름: 신규 진입 보류':
      plan.blocks[0]|| (plan.code==='pullback'?'관심 가격대까지 눌림을 기다립니다.':
        plan.code==='confirm'?'관심 구간 위로 지지가 회복되는지 확인하세요.':'관심 가격대의 지지 유지와 최신 공시를 확인하세요.');
    const modelStatus=ai.eligible?'AI 성능 기준 통과':!ai.record?'AI 검증 자료 없음':
      !ai.performancePassed?(ai.performanceStatus===false?'AI 성능 기준 미통과':'AI 성능 검증 자료 확인 필요'):ai.record.status==='eligible'?'AI 기준일·자료 확인 필요':
      ai.researchForecast?'AI 성능 기준 미통과':'AI 검증 자료 확인 필요';
    return {symbol:e.symbol||'',asOf:e.asOf||'',price:finite(e.price)?e.price:null,horizon:h,
      label,score,trend:trend(score),color:color(score),decision,reason,modelStatus,plan,ai};
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
      if(finite(p.rr)){
        const enough=p.rr>=minimum,up=(p.target1-p.buyHigh)/p.buyHigh,down=(p.buyHigh-p.stop)/p.buyHigh;
        add(enough?positive:negative,'reward-risk','관측 저항선 손익비 '+p.rr.toFixed(2)+'배'+(enough?'':' · 기준 미달'),
          '관심 구간 상단 '+money(p.buyHigh)+'에서 저항 '+money(p.target1)+'까지 '+percent(up)+
          ', 재평가 '+money(p.stop)+'까지 하락폭 '+percent(down)+'. 확인 기준 '+minimum.toFixed(1)+'배입니다.');
      }else if(!p.target1&&finite(p.buyHigh)&&finite(p.stop)){
        add(negative,'resistance-missing','위쪽 관측 저항이 없어 손익비 계산 불가',
          '관심 구간 상단 '+money(p.buyHigh)+' · 재평가 '+money(p.stop)+
          '. 수익 목표를 정할 저항선이 확보되지 않았습니다. 추가 상승을 보장하는 뜻이 아닙니다.');
      }
      if(finite(i.volatility4m)&&i.volatility4m>.5){
        add(negative,'volatility','변동성이 높음 · 하루 환산 약 '+percent(p.sig),
          '최근 4개월 종가에서 계산한 연환산 변동성 '+percent(i.volatility4m)+
          '. 하루 환산치는 손실 상한이 아니며 실제 움직임은 더 클 수 있습니다.');
      }
      if(p.indicators.rsi>75||p.indicators.z>2.5){
        const values=[finite(p.indicators.rsi)?'RSI '+p.indicators.rsi.toFixed(1):'',
          finite(p.indicators.z)?'20일 가격 편차 '+p.indicators.z.toFixed(2):''].filter(Boolean).join(' · ');
        add(negative,'overheated','단기 과열 · 추격 주의',values+'. RSI 75 또는 가격 편차 2.5를 넘어 단기 되돌림에 주의할 구간입니다.');
      }
    }
    if(a.score!==null&&a.score<60)add(limitations,'weak-trend','추세 점수 진입 기준 미달 · '+a.score+'/100',
      '신규 진입 검토 기준은 60점입니다. 가격 흐름의 점수이며 상승 확률이 아닙니다.');
    if(a.ai.eligible&&a.ai.forecast.direction==='down')add(limitations,'model-down',
      (a.horizon===252?'1년':'6개월')+' AI 전망이 하락 방향 · 신규 진입 보류',
      '검증 조건을 통과한 연구 전망이 하락 방향이어서 신규 진입을 보류합니다. 하락을 보장하는 뜻은 아닙니다.');
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
        '공통 시장 지표가 주의 상태라 최소 손익비를 2.0배로 높여 확인합니다.');
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
    const rows=(list,tone,icon)=>list.map(x=>'<div class="signal '+tone+'" data-signal="'+esc(x.id)+'"><span class="signalIcon">'+icon+
      '</span><span class="sa-signal-copy"><strong>'+esc(x.title)+'</strong><small>'+esc(x.detail)+'</small></span></div>').join('');
    const empty=s.available?'확인한 가격 지표에서 뚜렷한 위험이 감지되지 않았습니다.':'종목별 위험 판단에 필요한 가격 자료가 부족합니다.';
    return '<div class="explainGrid sa-signals" data-signals-symbol="'+esc(entry.symbol)+'">'+
      '<section class="panel signalPanel"><h3 class="goodText">지금 좋은 신호 · '+esc(entry.symbol)+'</h3><div class="signals">'+
      (rows(s.positive,'positive','✓')||'<p>확인한 가격 지표에서 뚜렷한 긍정 신호가 없습니다.</p>')+'</div></section>'+
      '<section class="panel signalPanel sa-specific-risks"><h3 class="badText">꼭 확인할 위험 · '+esc(entry.symbol)+'</h3><div class="signals">'+
      (rows(s.negative,'negative','!')||'<p>'+empty+' 기업 실적·회사 뉴스는 별도로 확인하세요.</p>')+'</div></section></div>'+
      (s.limitations.length?'<section class="panel signalPanel sa-limitations" aria-label="진입 조건·공통 상태"><h3>진입 조건·공통 상태</h3>'+
      '<p class="sa-limitations-note">현재 판단: '+esc(a.decision)+'. 시장 상태·자료 갱신·AI 검증·추세 점수 조건을 함께 확인하세요.</p><div class="signals">'+
      rows(s.limitations,'caution','i')+'</div></section>':'');
  }
  // Presentation only: expose the existing plan's separate entry conditions.
  // A favourable trend must never imply that price, risk or AI checks passed.
  function entryChecks(a){
    const p=a.plan,known=a.score!==null,threshold=p.market==='watch'?2:1.5;
    const zone=known&&finite(a.price)&&finite(p.buyLow)&&finite(p.buyHigh);
    const inside=zone&&a.price>=p.buyLow&&a.price<=p.buyHigh;
    const location=!zone?'자료 확인':inside?'구간 안':a.price>p.buyHigh?'구간 위':'구간 아래';
    const balance=known&&finite(p.rr),reward=balance&&p.rr>=threshold;
    const marketKnown=['stable','watch','risk'].includes(p.market);
    const down=a.ai.eligible&&a.ai.forecast?.direction==='down';
    const heatKnown=known&&finite(p.indicators.rsi)&&finite(p.indicators.z);
    const hot=p.blocks.some(x=>x.startsWith('단기 과열'));
    return [
      {key:'trend',label:'최근 가격 흐름',state:!known?'확인 필요':a.trend,tone:!known?'muted':a.color,
        detail:known?'추세 '+format(a.score)+' · 진입 검토 기준 60 이상':'최신 가격·종가 이력 확인 필요'},
      {key:'price',label:'진입 가격',state:location,tone:!zone?'muted':inside?'good':'warn',
        detail:'관심 구간 '+money(p.buyLow)+'–'+money(p.buyHigh)+' · 종가 '+money(a.price)},
      {key:'balance',label:'수익·위험 균형',state:!balance?'확인 필요':reward?'충족':'부족',tone:!balance?'muted':reward?'good':'warn',
        detail:balance?'손익비 '+p.rr.toFixed(2)+' / 기준 '+threshold+' 이상 · 관심 구간 상단 기준':'변동성·지지·관측 저항 자료 확인 필요'},
      {key:'market',label:'시장 위험',state:!marketKnown?'확인 필요':p.market==='risk'?'경보':p.market==='watch'?'주의':'경고 없음',
        tone:!marketKnown?'muted':p.market==='risk'?'bad':p.market==='watch'?'warn':'good',
        detail:!marketKnown?'최신 시장 위험 자료 확인 필요':p.market==='risk'?'시장·신용 경고로 신규 진입 보류':p.market==='watch'?'손익비 기준을 2 이상으로 강화':'관측 지표 기준'},
      {key:'heat',label:'단기 과열',state:!heatKnown?'확인 필요':hot?'추격 주의':'신호 없음',tone:!heatKnown?'muted':hot?'warn':'good',
        detail:heatKnown?'RSI '+p.indicators.rsi.toFixed(1)+' · 가격 z-score '+p.indicators.z.toFixed(2):'최신 종가 이력 확인 필요'},
      {key:'ai',label:(a.horizon===252?'1년':'6개월')+' AI 검증',state:down?'하락 우세':a.ai.eligible?'통과':a.modelStatus==='AI 성능 기준 미통과'?'미통과':'확인 필요',
        tone:down?'bad':a.ai.eligible?'good':a.modelStatus==='AI 성능 기준 미통과'?'warn':'muted',detail:a.ai.reason}
    ];
  }
  function entryExplanation(a){
    const descriptions={
      '실제 저항선 기준 손익비 부족':'가까운 저항까지의 상승폭이 재평가 기준까지의 하락폭에 비해 작습니다.',
      'AI 예측 검증 조건 미충족':'선택 기간의 AI 검증 조건이 충족되지 않았습니다.',
      '단기 과열: 추격 주의':'가격이 단기에 과열되어 추격 매수를 기다립니다.',
      '시장 위험 데이터 확인 필요':'최신 시장 위험 자료를 확인할 때까지 매수를 기다립니다.',
      '추세 점수가 진입 검토 기준 60에 못 미칩니다.':'최근 가격 흐름이 진입 검토 기준에 못 미칩니다.'
    };
    return descriptions[a.reason]||a.reason;
  }
  function panel(a){
    const p=a.plan;
    return '<section class="stockAssessment" aria-label="'+esc(a.symbol)+' 공통 평가">'+
      '<div class="sa-heading"><div><small>'+esc(a.symbol)+' · 신규 진입 판단 · '+(a.horizon===252?'1년':'6개월')+' 검증 조건</small><strong class="sa-'+(a.score===null?'muted':p.tone==='avoid'?'bad':p.tone==='buy'?'good':'warn')+'">'+esc(a.decision)+'</strong></div>'+
      '<span class="sa-date">종가 '+esc(a.asOf||'확인 필요')+'</span></div>'+
      '<p class="sa-reason"><b>'+(p.code==='buy'?'진입 검토 이유':a.score===null?'판단 보류 이유':a.decision+' 이유')+'</b> '+esc(entryExplanation(a))+'</p>'+
      '<div class="sa-entry-layout">'+visuals.entryGauge(p.code,a.decision)+'<div class="sa-conditions"><h3>지금 진입하려면?</h3><p class="sa-condition-note">가격 흐름과 아래 조건을 함께 확인합니다.</p><ul class="sa-checks">'+entryChecks(a).map(c=>'<li data-entry-check="'+c.key+'"><div class="sa-check-title"><span>'+esc(c.label)+'</span>'+visuals.badge(c.state,c.tone)+'</div><p>'+esc(c.detail)+'</p></li>').join('')+'</ul></div></div>'+
      '<details class="sa-trend-details"><summary>단기 추세 점수 자세히 · '+esc(format(a.score))+'</summary><p class="sa-note">최근 가격의 상승·하락 흐름을 평가한 점수입니다. 95점은 상승 확률 95%나 매수 추천 95점이라는 뜻이 아닙니다. 신규 매수는 위 진입 조건을 함께 확인하세요.</p><div class="sa-score" data-trend-symbol="'+esc(a.symbol)+'" data-trend-score="'+(a.score??'')+'">'+visuals.trendGauge(a.score,a.trend)+'</div></details>'+
      '<div class="sa-meta"><span>기준 종가 '+money(a.price)+'</span><span>'+esc(a.modelStatus)+'</span></div>'+
      '<details><summary>진입 조건·가격 기준</summary>'+visuals.table([['관심 구간',money(p.buyLow)+'–'+money(p.buyHigh)],['재평가 기준',money(p.stop)],['관측 저항',money(p.target1)]],'진입 가격 기준')+
      '<p>'+esc(p.blocks.join(' · ')||p.action)+'</p><p>추세 점수는 상승 확률이나 기업가치 점수가 아닙니다. 6개월·1년 AI 전망과 가치 시나리오는 별도로 확인하세요.</p></details></section>';
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
  const api={label,normalize,entry,trend,color,format,evaluate,all,rank,compare,entryChecks,entryExplanation,panel,signals,signalPanels,load};
  if(typeof module!=='undefined')module.exports=api;else root.StockAssessment=api;
})(typeof window!=='undefined'?window:globalThis);
