(function(root){
  'use strict';
  const finite=Number.isFinite, clamp=(x,a,b)=>Math.max(a,Math.min(b,x));
  const age=(d,now)=> (now-Date.parse(d))/86400000;
  const fresh=(d,n,now)=>finite(age(d,now))&&age(d,now)>=0&&age(d,now)<=n;
  function history(e){
    const rows=Array.from(new Map((e.history||[]).filter(q=>finite(q.close)&&q.close>0&&/^\d{4}-\d{2}-\d{2}$/.test(q.date)&&q.date<=e.asOf).map(q=>[q.date,q])).values()).sort((a,b)=>a.date.localeCompare(b.date));
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
  function plan(e,p,m,now=Date.now()){
    const a=e.inputs||{},px=e.price,i=indicators(e),sig=finite(a.volatility4m)&&a.volatility4m>0?a.volatility4m/Math.sqrt(252):null;
    const parts=[];for(const [ma,w] of [['ma20',10],['ma50',15],['ma200',20]])if(a[ma]>0)parts.push([px>=a[ma]?1:-1,w]);
    if(a.ma50>0&&a.ma200>0)parts.push([a.ma50>=a.ma200?1:-1,15]);
    for(const k of ['return1m','return3m'])if(finite(a[k]))parts.push([clamp(a[k]/.1,-1,1),10]);
    if(i.rsi!==null)parts.push([clamp((i.rsi-50)/20,-1,1),10]);if(i.macd!==null)parts.push([Math.sign(i.macd),10]);
    const total=parts.reduce((s,q)=>s+q[1],0),ts=total?Math.round(50+50*parts.reduce((s,q)=>s+q[0]*q[1],0)/total):50;
    const pivots=[];for(let j=2;j<i.rows.length-2;j++){const x=i.rows[j].close,w=i.rows.slice(j-2,j+3).map(q=>q.close);if(x===Math.min(...w)||x===Math.max(...w))pivots.push(x);}
    const levels=[a.ma20,a.ma50,a.ma200,...pivots.slice(-40)].filter(x=>finite(x)&&x>0),support=Math.max(0,...levels.filter(x=>x<=px));
    const width=sig?clamp(sig*.5,.004,.025):null,buyMid=support||null,buyLow=support&&width?support*(1-width):null,buyHigh=support&&width?support*(1+width):null,stop=buyLow&&sig?Math.max(.01,buyLow-1.5*sig*px):null;
    const targets=[...new Set(levels.filter(x=>buyHigh&&x>buyHigh))].sort((a,b)=>a-b),target1=targets[0]||null,target2=targets.find(x=>x>target1*1.01)||null,rr=target1&&stop&&buyHigh>stop?(target1-buyHigh)/(buyHigh-stop):null;
    const state=marketState(m,now),blocks=[];
    if(!e.fresh||!fresh(e.asOf,5,now))blocks.push('가격 데이터 갱신 필요');if(i.rows.length<60)blocks.push('실제 일별 종가 60개 이상 필요');if(!sig||!support)blocks.push('변동성·지지 자료 부족');if(state==='unknown')blocks.push('시장 위험 데이터 확인 필요');if(state==='risk')blocks.push('시장·신용 경고: 신규 진입 보류');if(rr===null||rr<(state==='watch'?2:1.5))blocks.push('실제 저항선 기준 손익비 부족');if(i.rsi>75||i.z>2.5)blocks.push('단기 과열: 추격 주의');
    let action='조건 확인 · 관망',tone='wait',code='watch';if(ts<35||state==='risk'){action='신규 진입 보류';tone='avoid';code='avoid';}else if(!blocks.length&&ts>=60){if(px>=buyLow&&px<=buyHigh){action='분할 진입 검토';tone='buy';code='buy';}else if(px>buyHigh){action='눌림목 대기';code='pullback';}else{action='지지 회복 확인';code='confirm';}}
    return {ts,support,buyMid,buyLow,buyHigh,stop,target1,target2,rr,action,tone,code,sig,riskPct:stop?(px-stop)/px:null,indicators:i,blocks,market:state};
  }
  const api={plan,indicators,history,marketState};if(typeof module!=='undefined')module.exports=api;else root.TechnicalGuide=api;
})(typeof window!=='undefined'?window:globalThis);
