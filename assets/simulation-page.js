(function(){
'use strict';
const $=id=>document.getElementById(id),N=Number.isFinite,esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money=x=>N(x)?'$'+x.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2}):'—',pct=x=>N(x)?(100*x).toFixed(2)+'%':'—',num=x=>N(x)?x.toLocaleString('en-US',{maximumFractionDigits:6}):'—';
const date=x=>N(x)?new Date(x).toLocaleDateString('ko-KR',{timeZone:'UTC',year:'2-digit',month:'2-digit',day:'2-digit'}):'—',time=x=>N(x)?new Date(x).toISOString().slice(0,16).replace('T',' '):'—';
const names={retest:'돌파 후 재확인',candle:'지지·저항 + 캔들',falseBreak:'가짜 돌파 후 복귀',portfolioTrend:'추세 포트폴리오'},eventNames={signal:'신호 확인 · 주문 대기',entry:'가상 진입',exit:'가상 청산',cancel:'주문 취소'};
const query=new URLSearchParams(location.search);let asset=query.get('asset')==='stocks'?'stocks':'crypto',mode=query.get('mode')==='replay'?'replay':'forward',data=null,page=0,selectedTrade=null,selectedSymbol=null;
const tone=x=>x>=0?'positive':'negative',side=x=>x==='long'?'롱':'숏';
function panel(title,body,small=''){return '<section class="sim-panel"><div class="panel-head"><h2>'+title+'</h2><small>'+small+'</small></div>'+body+'</section>'}
function equityChart(a){
 const rows=a.curve||[];if(!rows.length)return '<div class="empty">첫 평가액을 기다리고 있습니다.</div>';
 if(rows.length===1)return '<svg viewBox="0 0 1000 210" role="img" aria-label="가상 계좌 시작 금액 1만 달러"><line x1="65" y1="110" x2="950" y2="110" stroke="#274356"/><circle cx="65" cy="110" r="6" fill="#7bf1cb"/><text x="90" y="102" fill="#eaf3fc" font-size="22">$10,000.00</text><text x="90" y="134" fill="#9bb1c7" font-size="15">첫 기록부터 실제 시장 변화에 따라 쌓입니다.</text></svg>';
 const step=Math.max(1,Math.ceil(rows.length/550)),points=rows.filter((r,i)=>i%step===0||i===rows.length-1),v=points.flatMap(r=>[r.equity,r.benchmark]).filter(N),lo=Math.min(...v,10000)*.97,hi=Math.max(...v,10000)*1.03,W=1000,H=300,L=70,R=25,T=20,B=38;
 const first=rows[0].at,last=rows.at(-1).at,x=t=>L+(t-first)/(last-first)*(W-L-R),y=n=>T+(hi-n)/(hi-lo)*(H-T-B),line=k=>points.map(r=>x(r.at).toFixed(1)+','+y(r[k]).toFixed(1)).join(' ');
 let s='<svg viewBox="0 0 1000 300" role="img" aria-label="가상 계좌 평가액과 단순 보유 비교"><defs><linearGradient id="equityFill" x1="0" y1="0" x2="0" y2="1"><stop stop-color="#7bf1cb" stop-opacity=".14"/><stop offset="1" stop-color="#7bf1cb" stop-opacity="0"/></linearGradient></defs>';
 for(let i=0;i<4;i++){const n=lo+(hi-lo)*i/3,yy=y(n);s+='<line x1="70" y1="'+yy+'" x2="975" y2="'+yy+'" stroke="#20374a"/><text x="59" y="'+(yy+4)+'" text-anchor="end" fill="#9bb1c7" font-size="12">$'+Math.round(n).toLocaleString('en-US')+'</text>';}
 s+='<polygon points="'+L+','+(H-B)+' '+line('equity')+' '+(W-R)+','+(H-B)+'" fill="url(#equityFill)"/><polyline points="'+line('benchmark')+'" fill="none" stroke="#f1cd88" stroke-width="1.8" stroke-dasharray="6 5"/><polyline points="'+line('equity')+'" fill="none" stroke="#7bf1cb" stroke-width="2.8"/>';
 for(let i=0;i<4;i++){const t=first+(last-first)*i/3;s+='<text x="'+x(t)+'" y="291" text-anchor="'+(i===0?'start':i===3?'end':'middle')+'" fill="#9bb1c7" font-size="12">'+date(t)+'</text>';}
 return s+'</svg>';
}
function candleChart(rows,trade){
 if(!rows?.length)return '<div class="empty">가격 자료를 준비 중입니다.</div>';
 const levels=trade?[trade.entry,trade.exit,trade.stop,trade.target].filter(N):[],values=rows.flatMap(r=>[r.low,r.high]).concat(levels),min=Math.min(...values),max=Math.max(...values),pad=(max-min)*.15||min*.01,lo=min-pad,hi=max+pad;
 const W=1000,H=340,L=72,R=30,T=22,B=42,dx=(W-L-R)/rows.length,x=i=>L+(i+.5)*dx,y=p=>T+(hi-p)/(hi-lo)*(H-T-B);
 let s='<svg viewBox="0 0 1000 340" role="img" aria-label="실제 과거 캔들과 모의 진입 청산 위치">';
 for(let i=0;i<3;i++){const p=lo+(hi-lo)*(i+.5)/3,yy=y(p);s+='<line x1="72" x2="970" y1="'+yy+'" y2="'+yy+'" stroke="#20374a"/><text x="63" y="'+(yy+4)+'" text-anchor="end" fill="#9bb1c7" font-size="12">'+money(p)+'</text>';}
 rows.forEach((r,i)=>{const c=r.close>=r.open?'#7bf1cb':'#ff9da8',xx=x(i),top=y(Math.max(r.open,r.close)),height=Math.max(1,Math.abs(y(r.open)-y(r.close))),width=Math.max(1,dx*.65);s+='<g><title>'+time(r.t)+' UTC · O '+money(r.open)+' H '+money(r.high)+' L '+money(r.low)+' C '+money(r.close)+'</title><line x1="'+xx+'" x2="'+xx+'" y1="'+y(r.high)+'" y2="'+y(r.low)+'" stroke="'+c+'"/><rect x="'+(xx-width/2)+'" y="'+top+'" width="'+width+'" height="'+height+'" fill="'+c+'"/></g>';});
 if(trade){for(const [value,label,color] of [[trade.stop,'손절','#ff9da8'],[trade.target,'2R 익절','#f1cd88']])if(N(value))s+='<line x1="72" x2="970" y1="'+y(value)+'" y2="'+y(value)+'" stroke="'+color+'" opacity=".6" stroke-dasharray="4 5"/><text x="966" y="'+(y(value)-5)+'" text-anchor="end" fill="'+color+'" font-size="11">'+label+'</text>';
  for(const [at,p,label,c] of [[trade.entryAt,trade.entry,asset==='stocks'?'매수':side(trade.side)+' 진입','#73d5fb'],[trade.exitAt,trade.exit,'청산','#f1cd88']]){if(!N(at)||!N(p))continue;const index=rows.findIndex(r=>r.t<=at&&r.end>=at);if(index<0)continue;const xx=x(index),yy=y(p);s+='<circle cx="'+xx+'" cy="'+yy+'" r="5" fill="'+c+'" stroke="#08121f" stroke-width="2"/><text x="'+Math.max(90,Math.min(920,xx))+'" y="'+(yy+(label==='청산'?-13:22))+'" text-anchor="middle" fill="'+c+'" font-weight="700" font-size="13">'+label+'</text>';}
 }
 s+='<text x="72" y="330" fill="#9bb1c7" font-size="12">'+date(rows[0].t)+'</text><text x="970" y="330" text-anchor="end" fill="#9bb1c7" font-size="12">'+date(rows.at(-1).t)+'</text></svg>';return s;
}
function positions(a){
 const exposure=a.positions.reduce((s,p)=>s+p.margin,0),width=Math.min(100,exposure/Math.max(1,a.equity)*100);
 let body='<div class="allocation"><i style="width:'+width+'%"></i></div><div class="allocation-label"><span>투입 원금 '+money(exposure)+'</span><span>가용 현금 '+money(a.cash)+'</span></div>';
 if(!a.positions.length)body+='<div class="empty">현재 보유 포지션이 없습니다.<br>진입 조건이 없으면 현금을 유지합니다.</div>';
 else body+='<div class="table-wrap"><table><thead><tr><th>종목</th><th>수량</th><th>진입 / 현재</th><th>미실현 손익</th></tr></thead><tbody>'+a.positions.map(p=>'<tr><td><b>'+esc(p.symbol)+'</b><small>'+ (asset==='stocks'?esc(p.sector):side(p.side)+' · 1배')+'</small></td><td>'+num(p.qty)+'</td><td>'+money(p.entry)+'<small>'+money(p.mark)+'</small></td><td class="'+tone(p.unrealized)+'">'+money(p.unrealized)+'<small>손절 '+money(p.stop)+' / 익절 '+money(p.target)+'</small></td></tr>').join('')+'</tbody></table></div>';
 body+='<p class="muted">미실현 손익은 가격 차이 기준입니다. 계좌 평가액에는 이미 지급한 수수료·펀딩을 반영합니다.</p>';
 if(a.pending.length)body+='<h3 style="font-size:13px">다음 진입 대기</h3>'+a.pending.slice(0,5).map(p=>'<div class="event"><strong>'+esc(p.symbol)+' '+(asset==='crypto'?side(p.side):'매수')+'</strong><div>'+esc(p.reason)+'<p>관심가 '+money(p.price)+' · 손절 '+money(p.stop)+' · 익절 '+money(p.target)+'</p><p>신호 이후 다음 가용 시가 · 가격·자금 조건 재확인</p></div></div>').join('');
 return panel(asset==='stocks'?'가상 포트폴리오':'현재 가상 포지션',body,a.positions.length+' / '+data.config[asset].maxPositions+'개 보유');
}
function activity(a){
 const entries=[...(a.events||[])].reverse().slice(0,12);
 const body=entries.length?'<div class="event-list">'+entries.map(e=>'<div class="event"><time>'+time(e.at)+' UTC</time><div><strong>'+esc(e.symbol||'')+' · '+esc(eventNames[e.type]||e.type)+'</strong><p>'+esc(e.reason||'')+'</p>'+(N(e.price)?'<span>'+money(e.price)+(N(e.net)?' · <span class="'+tone(e.net)+'">'+money(e.net)+'</span>':'')+'</span>':'')+'</div></div>').join('')+'</div>':'<div class="empty">운용을 시작했습니다.<br>첫 신호를 기다리고 있습니다.</div>';
 return panel('매매 기록 타임라인',body,'UTC · '+(mode==='forward'?'발표 후 기록':'과거 재현 기록'));
}
function tradeTable(a){
 const all=[...a.trades].reverse(),pages=Math.max(1,Math.ceil(all.length/10));page=Math.min(page,pages-1);const rows=all.slice(page*10,page*10+10);
 let body='<div class="table-toolbar"><span>총 '+all.length+'건 · 종목을 누르면 진입·청산 캔들 확인</span><div class="pagination"><button id="previousTrades" '+(page===0?'disabled':'')+'>이전</button><span> '+(page+1)+' / '+pages+' </span><button id="nextTrades" '+(page===pages-1?'disabled':'')+'>다음</button></div></div>';
 body+=rows.length?'<div class="table-wrap"><table><thead><tr><th>종목 / 방향</th><th>진입 → 청산</th><th>진입가 → 청산가</th><th>순손익</th><th>신호 / 종료 이유</th></tr></thead><tbody>'+rows.map(t=>'<tr><td><button class="trade-button" data-trade="'+esc(t.id)+'">'+esc(t.symbol)+'</button><small class="side">'+(asset==='crypto'?side(t.side):'매수')+'</small></td><td>'+time(t.entryAt)+'<small>'+time(t.exitAt)+' UTC</small></td><td>'+money(t.entry)+'<small>'+money(t.exit)+'</small></td><td class="'+tone(t.net)+'">'+money(t.net)+'<small>수수료 '+money(t.entryFee+t.exitFee)+' · 펀딩 '+money(t.funding)+'</small></td><td class="reason">'+esc(names[t.pattern]||t.pattern)+'<small>'+esc(t.exitReason)+'</small></td></tr>').join('')+'</tbody></table></div>':'<div class="empty">아직 종료된 거래가 없습니다. 승률은 거래가 끝난 뒤 계산합니다.</div>';
 return panel('종료된 거래 · 비용 반영',body,'순손익에 진입·청산 비용과 펀딩 포함');
}
function render(){
 if(!data)return;const a=data[mode]?.accounts?.[asset];
 document.querySelectorAll('[data-asset]').forEach(b=>b.setAttribute('aria-selected',String(b.dataset.asset===asset)));document.querySelectorAll('[data-mode]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.mode===mode)));
 if(!a){$('simulationApp').innerHTML='<section class="sim-panel empty">해당 계좌 자료를 준비 중입니다.</section>';return;}
 const past=data.replay?.accounts?.[asset],cfg=data.config[asset],elapsed=Math.max(0,(a.marketAsOf-a.startedAt)/86400000),benchmark=a.curve?.at(-1)?.benchmark;
 let notice=mode==='forward'?'<b>지금부터 모의운용 · '+date(a.startedAt)+' 시작</b>실제로 저장한 신호 이후의 봉으로만 가상 체결합니다. 과거 재현의 잔액을 가져오지 않습니다.':'<b>과거 재현 · 탐색 실험</b>'+date(a.startedAt)+'–'+date(a.marketAsOf)+' 자료를 오늘 정한 규칙으로 재현했습니다. 발표 당시의 실제 모의운용 성적이 아닙니다.';
 if(mode==='forward'&&!a.trades.length&&past)notice+='<br><button id="showReplay">과거 재현에서 매매 흐름 보기 · '+money(past.equity)+'</button>';
 notice+='<small>가격 기준 '+time(a.marketAsOf)+' UTC · 화면 자료 생성 '+time(data.generatedAt)+' UTC</small>';
 let html='<div class="notice '+(mode==='replay'?'replay':'')+'">'+notice+'</div>';
 if(a.warnings.length)html+='<div class="warning">'+a.warnings.map(esc).join(' · ')+(a.estimatedFundingHours?' · 가정 적용 '+a.estimatedFundingHours+'시간':'')+'</div>';
 if(data.errors?.length&&mode==='forward')html+='<div class="warning">일부 시장 자료 수집이 지연되었습니다. 기준 시각과 신호의 보류 사유를 확인하세요.</div>';
 html+='<section class="stats-grid" aria-label="계좌 성적"><div class="stat primary"><span class="stat-label">총 가상 자산</span><strong>'+money(a.equity)+'</strong><small class="'+tone(a.return)+'">'+pct(a.return)+' · 시작 $10,000</small></div><div class="stat"><span class="stat-label">최대 낙폭</span><strong class="negative">'+pct(a.maxDrawdown)+'</strong><small>고점 대비 평가액 하락</small></div><div class="stat"><span class="stat-label">종료 거래 승률</span><strong>'+pct(a.winRate)+'</strong><small>'+a.trades.length+'건 · 이번 거래 확률 아님</small></div><div class="stat"><span class="stat-label">단순 보유 비교</span><strong>'+money(benchmark)+'</strong><small>'+esc(a.benchmark?.symbol||'')+' · 같은 시작 자금</small></div></section>';
 html+=panel('가상 자산의 변화','<div class="chart">'+equityChart(a)+'</div><div class="legend"><span><i></i>모의 계좌</span><span><i class="benchmark"></i>'+esc(a.benchmark?.symbol||'')+' 단순 보유</span></div><div class="metrics-row"><div><span>종료 거래 순손익</span><b class="'+tone(a.realized)+'">'+money(a.realized)+'</b></div><div><span>누적 수수료</span><b>'+money(a.fees)+'</b></div><div><span>펀딩 순지급</span><b>'+money(a.funding)+'</b></div><div><span>거래당 평균 순손익</span><b>'+money(a.averageTrade)+'</b></div></div><p class="muted">비교 계좌도 최초 매수 수수료·슬리피지를 적용합니다. 보유 중 청산 비용은 미차감입니다. 최대 낙폭은 봉 마감 평가액 기준으로, 장중 최대 손실은 더 클 수 있습니다.</p>',Math.floor(elapsed)+'일 관측 · '+(asset==='crypto'?'15분봉':'일봉'));
 html+='<div class="two-cols">'+positions(a)+activity(a)+'</div>';
 let trade=selectedTrade?a.trades.find(t=>t.id===selectedTrade):a.trades.at(-1);
 const syms=Object.keys(data.preview?.[asset]||{}).filter(s=>asset==='crypto'||s!=='SPY');
 const symbol=selectedSymbol&&syms.includes(selectedSymbol)?selectedSymbol:trade?.symbol||a.positions[0]?.symbol||a.pending[0]?.symbol||syms[0];
 if(trade&&trade.symbol!==symbol)trade=null;
 const window=trade&&data.tradeWindows?.[trade.id],chartRows=window||data.preview?.[asset]?.[symbol];
 html+=panel('가격과 모의 진입·청산','<div class="panel-head"><select id="chartSymbol" aria-label="가격 차트 종목">'+syms.map(s=>'<option '+(s===symbol?'selected':'')+'>'+esc(s)+'</option>').join('')+'</select><small>'+esc(symbol||'')+' · '+(asset==='crypto'?'실제 15분 캔들':'실제 일별 캔들')+'</small></div><div class="chart">'+candleChart(chartRows,window?trade:null)+'</div><p class="chart-detail">'+(window?esc(trade.reason)+' · '+esc(trade.exitReason)+' · 순손익 '+money(trade.net):'최근 완료 봉입니다. 종료 거래를 선택하면 해당 진입과 청산 위치를 표시합니다. 최근 30개 종료 거래에 상세 캔들을 제공합니다.')+'</p>');
 if(asset==='crypto')html+=panel('세 가지 패턴의 성적','<div class="scenario-summary">'+['retest','candle','falseBreak'].map(k=>{const p=a.patternResults[k];return '<div><b>'+names[k]+'</b><strong class="'+tone(p?.net||0)+'">'+money(p?.net||0)+'</strong><span>'+(p?p.trades+'건 · 승률 '+pct(p.wins/p.trades):'완료 거래 없음')+'</span></div>'}).join('')+'</div><p class="muted">하나의 $10,000 계좌 안에서 발생한 거래별 집계입니다. 패턴마다 별도 자금을 준 성적이 아닙니다.</p>');
 const sigs=a.signals.filter(s=>s.symbol!=='SPY');html+=panel('현재 실험 신호','<div class="table-wrap"><table><thead><tr><th>종목</th><th>판단</th><th>근거</th><th>봉 기준 시각</th></tr></thead><tbody>'+sigs.map(s=>'<tr><td>'+esc(s.symbol)+'</td><td class="'+(s.side==='long'?'positive':s.side==='short'?'negative':'')+'">'+(s.side?(asset==='stocks'?'매수 대기':side(s.side)+' 진입 대기'):'관망')+'</td><td class="reason">'+esc(s.reason)+'</td><td>'+time(s.at)+' UTC</td></tr>').join('')+'</tbody></table></div><p class="muted">'+(mode==='replay'?'과거 재현이 끝난 시점의 신호입니다.':'신호가 나와도 다음 봉의 가격, 남은 현금, 보유 한도에 따라 주문이 취소될 수 있습니다.')+'</p>');
 html+=tradeTable(a);
 html+='<section class="sim-panel method"><h2 style="font-size:17px">계좌를 움직이는 고정 규칙</h2><details open><summary>진입·청산·자금 관리</summary><p>'+ (asset==='crypto'?'BTC·ETH·SOL · 15분봉 신호 + 완료된 1시간봉 흐름. 돌파 재확인, 지지·저항의 장악형/핀바, 횡보의 가짜 돌파를 시험합니다. 최대 3포지션, 코인당 원금 약 33%, 진입 시 1배 증거금.':'미리 고른 20종목에서 SPY 200일선, 종목 추세, RSI, 눌림 반등·돌파를 확인합니다. 최대 5종목, 종목당 원금 20%, 같은 업종 최대 2종목입니다.')+'</p><p>거래당 손절 위험 예산 '+pct(cfg.risk)+' · 원래 손절 폭의 2배를 가상 익절 목표로 사용합니다. 비용 반영 손익비 1.3 미만 또는 진입 시 가격이 신호에서 0.5 ATR 이상 벌어지면 취소합니다. 손절 예산은 실제 최대 손실 보장이 아닙니다.</p><p>'+(asset==='crypto'?'최대 8봉(2시간) 보유 후 종료합니다.':'최대 84거래일 보유, 50일 EMA 아래에서 마감하면 다음 시가에 정리합니다.')+' 동일 봉에서 손절·익절 모두 닿으면 손절 우선, 손절선 밖으로 갭이 나면 불리한 시가를 적용합니다.</p></details><details><summary>비용·자료·검증 한계</summary><p>편도 수수료 '+pct(cfg.fee)+' · 편도 슬리피지 '+pct(cfg.slip)+'. '+(asset==='crypto'?'과거 펀딩률을 쓰되 금액 계산에는 봉 가격을 대용합니다. 누락은 시간당 0.01% 지급 가정이며, 청산 봉의 불확실한 펀딩 수취는 인정하지 않습니다.':'배당·세금·환전 비용은 포함하지 않습니다. 현재 선택한 종목을 과거에 적용한 선택·생존편향이 남습니다.')+'</p><ul>'+data.notes.map(n=>'<li>'+esc(n)+'</li>').join('')+'</ul><p>실험 '+esc(data.version)+' · <a href="simulation/README.md">전체 규칙과 검증</a> · <a href="simulation/state.json">진행 중 계좌 원본</a> · <a href="simulation/replay.json">고정 과거 재현 원본</a></p></details></section>';
 $('simulationApp').innerHTML=html;
 $('showReplay')?.addEventListener('click',()=>change(asset,'replay'));
 $('chartSymbol')?.addEventListener('change',e=>{selectedSymbol=e.target.value;selectedTrade=null;render()});
 $('previousTrades')?.addEventListener('click',()=>{page--;render()});$('nextTrades')?.addEventListener('click',()=>{page++;render()});
 document.querySelectorAll('[data-trade]').forEach(b=>b.addEventListener('click',()=>{selectedTrade=b.dataset.trade;selectedSymbol=a.trades.find(t=>t.id===selectedTrade)?.symbol;render();$('chartSymbol')?.scrollIntoView({behavior:'smooth',block:'center'})}));
}
function change(nextAsset,nextMode){asset=nextAsset;mode=nextMode;page=0;selectedTrade=null;selectedSymbol=null;history.replaceState(null,'','?asset='+asset+'&mode='+mode);render();}
document.querySelectorAll('[data-asset]').forEach(b=>b.addEventListener('click',()=>change(b.dataset.asset,mode)));document.querySelectorAll('[data-mode]').forEach(b=>b.addEventListener('click',()=>change(asset,b.dataset.mode)));
fetch('simulation/latest.json',{cache:'no-store'}).then(r=>{if(!r.ok)throw Error('Unavailable');return r.json()}).then(d=>{data=d;render()}).catch(()=>{$('simulationApp').innerHTML='<section class="sim-panel empty">모의운용 자료를 아직 불러오지 못했습니다. 첫 자동 계산이 끝난 뒤 새로고침해 주세요.</section>'});
})();
