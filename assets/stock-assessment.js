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
  const api={label,normalize,entry,trend,color,format,evaluate,all,rank,compare,entryChecks,entryExplanation,panel,load};
  if(typeof module!=='undefined')module.exports=api;else root.StockAssessment=api;
})(typeof window!=='undefined'?window:globalThis);
