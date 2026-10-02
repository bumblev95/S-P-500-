(function(root){
  'use strict';
  const technical=typeof module!=='undefined'?require('./technical-guide.js'):root.TechnicalGuide;
  const learnedGuide=typeof module!=='undefined'?require('./learned-guide.js'):root.LearnedGuide;
  const finite=Number.isFinite;
  const label='단기 추세 점수';
  const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const money=x=>finite(x)?'$'+x.toLocaleString('en-US',{maximumFractionDigits:2}):'—';
  const normalize=s=>String(s||'').trim().toUpperCase().replace(/\./g,'-');

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
    const valid=e.status==='ready'&&e.fresh&&finite(age)&&age>=0&&age<=5&&plan.indicators.rows.length>=60;
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
    const modelStatus=ai.eligible?'AI 성능 기준 통과':
      !ai.record?'AI 검증 자료 없음':ai.record.status==='eligible'?'AI 기준일·자료 확인 필요':
      ai.researchForecast?'AI 성능 기준 미통과':'AI 검증 자료 확인 필요';
    return {symbol:e.symbol||'',asOf:e.asOf||'',price:finite(e.price)?e.price:null,horizon:h,
      label,score,trend:trend(score),color:color(score),decision,reason,modelStatus,plan,ai};
  }
  function all(data,market,learned,horizon=126,now=Date.now()){
    return Object.fromEntries(Object.entries(data?.stocks||{}).map(([symbol,e])=>
      [normalize(symbol),evaluate(e,market,learned,horizon,now)]));
  }
  function rank(assessments,limit=10){
    return Object.values(assessments||{}).filter(a=>finite(a.score))
      .sort((a,b)=>b.score-a.score||a.symbol.localeCompare(b.symbol)).slice(0,limit);
  }
  function panel(a){
    const p=a.plan;
    return '<section class="stockAssessment" aria-label="'+esc(a.symbol)+' 공통 평가">'+
      '<div class="sa-heading"><div><small>'+esc(a.symbol)+' · 신규 진입 판단 · '+(a.horizon===252?'1년':'6개월')+' 검증 조건</small><strong class="sa-'+(p.tone==='avoid'?'bad':p.tone==='buy'?'good':'warn')+'">'+esc(a.decision)+'</strong></div>'+
      '<div class="sa-score" data-trend-symbol="'+esc(a.symbol)+'" data-trend-score="'+(a.score??'')+'"><small>'+label+'</small><b class="sa-'+a.color+'">'+format(a.score)+'</b><small>'+a.trend+'</small></div></div>'+
      '<p class="sa-reason">'+esc(a.reason)+'</p><div class="sa-meta"><span>종가 기준 '+esc(a.asOf||'확인 필요')+'</span><span>'+esc(a.modelStatus)+'</span></div>'+
      '<p class="sa-note">추세 점수는 가격 흐름을 평가합니다. 높은 점수도 진입 조건을 자동 통과하지 않습니다.</p>'+
      '<details><summary>진입 조건·가격 기준</summary><p>관심 구간 '+money(p.buyLow)+'–'+money(p.buyHigh)+' · 재평가 '+money(p.stop)+' · 관측 저항 '+money(p.target1)+'</p>'+
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
  const api={label,normalize,trend,color,format,evaluate,all,rank,panel,load};
  if(typeof module!=='undefined')module.exports=api;else root.StockAssessment=api;
})(typeof window!=='undefined'?window:globalThis);
