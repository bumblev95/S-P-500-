(function(root){
'use strict';
const MS={'5m':300000,'15m':900000,'1h':3600000,'1d':86400000},HIGHER={'5m':'15m','15m':'1h','1d':'1d'};
const finite=Number.isFinite,mean=a=>a.reduce((x,y)=>x+y,0)/a.length,clamp=(v,a=0,b=100)=>Math.max(a,Math.min(b,v));
function candles(raw,interval,now=Date.now(),symbol){
 const step=MS[interval],out=new Map();if(!step||!Array.isArray(raw))return [];
 for(const r of raw){if(['t','T','o','h','l','c','v'].some(k=>r[k]===null||r[k]===''))continue;const q={t:Number(r.t),end:Number(r.T),open:Number(r.o),high:Number(r.h),low:Number(r.l),close:Number(r.c),volume:Number(r.v)};
  if(symbol&&r.s!==symbol||r.i!==interval||!Object.values(q).every(finite)||q.t%step!==0||q.end!==q.t+step-1||q.end>=now||q.volume<0||q.low<=0||q.low>Math.min(q.open,q.close)||q.high<Math.max(q.open,q.close))continue;
  out.set(q.t,q);
 }return [...out.values()].sort((a,b)=>a.t-b.t);
}
function ema(p,n){let v=p[0];return p.map(x=>(v+=(x-v)*2/(n+1)))}
function indicators(rows,interval){
 if(rows.length<60)return null;
 const p=rows.map(r=>r.close),last=rows.at(-1),e20=ema(p,20),e50=ema(p,50),e26=ema(p,26),macd=ema(p,12).map((v,i)=>v-e26[i]);
 const delta=p.slice(1).map((v,i)=>v-p[i]),g=delta.map(v=>Math.max(v,0)),l=delta.map(v=>Math.max(-v,0));let gain=mean(g.slice(0,14)),loss=mean(l.slice(0,14));
 for(let i=14;i<g.length;i++){gain=(gain*13+g[i])/14;loss=(loss*13+l[i])/14;}
 const tr=rows.slice(1).map((r,i)=>Math.max(r.high-r.low,Math.abs(r.high-p[i]),Math.abs(r.low-p[i])));let atr=mean(tr.slice(0,14));for(const v of tr.slice(14))atr=(atr*13+v)/14;
 const session=interval==='1d'?rows.slice(-20):rows.filter(r=>Math.floor(r.t/86400000)===Math.floor(last.t/86400000)),volume=session.reduce((s,r)=>s+r.volume,0),avgVolume=mean(rows.slice(-21,-1).map(r=>r.volume));
 const vwap=volume?session.reduce((s,r)=>s+(r.high+r.low+r.close)/3*r.volume,0)/volume:null;
 const travel=delta.slice(-20).reduce((s,v)=>s+Math.abs(v),0),efficiency=travel?Math.abs(p.at(-1)-p.at(-21))/travel:0;
 return {ema20:e20.at(-1),previousEma20:e20.at(-2),ema50:e50.at(-1),rsi:gain+loss===0?50:loss===0?100:100-100/(1+gain/loss),macd:macd.at(-1)-ema(macd,9).at(-1),atr,vwap,relativeVolume:avgVolume>0?last.volume/avgVolume:null,efficiency,bias:e20.at(-1)>e50.at(-1)&&last.close>e50.at(-1)?'long':e20.at(-1)<e50.at(-1)&&last.close<e50.at(-1)?'short':'neutral'};
}
function detect(rows,ind){
 const last=rows.at(-1),prev=rows.at(-2),prior=rows.slice(-21,-1),high=Math.max(...prior.map(r=>r.high)),low=Math.min(...prior.map(r=>r.low)),active=ind.relativeVolume>=1.3;
 if(last.close>high)return {name:active?'거래량 동반 상단 돌파':'상단 돌파 · 거래량 확인 대기',side:'long',confirmed:active,kind:'breakout',high,low};
 if(last.close<low)return {name:active?'거래량 동반 하단 이탈':'하단 이탈 · 거래량 확인 대기',side:'short',confirmed:active,kind:'breakout',high,low};
 const bullish=last.close>last.open&&prev.close<prev.open&&last.open<=prev.close&&last.close>=prev.open;
 const bearish=last.close<last.open&&prev.close>prev.open&&last.open>=prev.close&&last.close<=prev.open;
 if(ind.bias==='long'&&last.low<=ind.ema20+.25*ind.atr&&last.close>ind.ema20&&last.close>last.open&&(prev.close<=ind.previousEma20+.3*ind.atr||bullish))return {name:bullish?'상승 추세 · 상승 장악형':'상승 추세 · 눌림목 반등',side:'long',confirmed:ind.relativeVolume>=.8,kind:'pullback',high,low};
 if(ind.bias==='short'&&last.high>=ind.ema20-.25*ind.atr&&last.close<ind.ema20&&last.close<last.open&&(prev.close>=ind.previousEma20-.3*ind.atr||bearish))return {name:bearish?'하락 추세 · 하락 장악형':'하락 추세 · 반등 후 저항',side:'short',confirmed:ind.relativeVolume>=.8,kind:'pullback',high,low};
 return {name:ind.efficiency<.25?'횡보 · 방향 확인 대기':'추세 진행 · 진입 패턴 대기',side:null,confirmed:false,kind:'none',high,low};
}
function levels(rows,ind,pattern,side,funding,step){
 const px=rows.at(-1).close,atr=ind.atr,lowEntry=px-.15*atr,highEntry=px+.15*atr,entry=side==='long'?highEntry:lowEntry,highs=[],lows=[];
 for(let i=Math.max(2,rows.length-160);i<rows.length-2;i++){const q=rows[i],near=rows.slice(i-2,i+3);if(near.every(r=>q.high>=r.high))highs.push(q.high);if(near.every(r=>q.low<=r.low))lows.push(q.low);}
 const support=Math.max(pattern.low,...lows.filter(v=>v<lowEntry)),resistance=Math.min(pattern.high,...highs.filter(v=>v>highEntry));
 let stop=side==='long'?support-.25*atr:resistance+.25*atr,target=side==='long'?Math.min(...highs.filter(v=>v>highEntry)):Math.max(...lows.filter(v=>v<lowEntry));
 let targetKind='확인된 이전 고점·저점';
 if(!finite(target)&&pattern.kind==='breakout'&&pattern.side===side){target=side==='long'?pattern.high+(pattern.high-pattern.low):pattern.low-(pattern.high-pattern.low);targetKind='직전 박스 폭을 투영한 가정';}
 if(!finite(target)||target<=0)target=null;
 const risk=side==='long'?entry-stop:stop-entry,reward=target===null?null:side==='long'?target-entry:entry-target;
 // Six bars is a cost assumption, not a promised holding duration. Funding receipts never boost the score.
 const hours=Math.ceil(6*step/3600000),fundingCost=finite(funding)?Math.max(side==='long'?funding:-funding,0)*hours:null;
 const costRate=.00045*2+.0002*2+(fundingCost||0),cost=entry*costRate;
 const rr=risk>0&&reward!==null&&reward>cost?(reward-cost)/(risk+cost):null;
 return {lowEntry,highEntry,entry,stop:stop>0?stop:null,target,targetKind,rr,costRate,hours,valid:risk>0&&risk<=5*atr&&stop>0&&finite(rr)};
}
function analyze(snapshot,interval,now=Date.now()){
 const step=MS[interval],rows=snapshot.frames?.[interval]||[],higher=HIGHER[interval],context=snapshot.frames?.[higher]||[],ind=indicators(rows,interval),hi=indicators(context,higher),blocks=[];
 const age=t=>now-t,goodTime=t=>finite(t)&&age(t)>=0&&age(t)<=90000;
 if(!goodTime(snapshot.quoteAt)||!goodTime(snapshot.bookAt)||!goodTime(snapshot.receivedAt))blocks.push('가격·호가 갱신이 90초를 넘었거나 시각 확인 필요');
 if(snapshot.error)blocks.push('최근 데이터 요청 실패 · 새 신호 보류');
 function check(series,tf){const tail=series.slice(-200),latest=tail.at(-1);if(tail.length<60||!latest||now<latest.end||now-latest.end>MS[tf]+15000||tail.some((r,i)=>i&&r.t-tail[i-1].t!==MS[tf]))blocks.push(tf+' 완료 봉 부족·누락·지연');}
 if(!step)return {action:'관망',blocks:['지원하지 않는 봉 주기'],ind:null};check(rows,interval);if(higher!==interval)check(context,higher);
 if(!ind||!hi)return {action:'관망',blocks,ind:null};
 const q=snapshot.quote||{},book=snapshot.book||{},mark=q.mark;
 if(!finite(mark)||mark<=0||q.delisted)blocks.push('선물 가격·상장 상태 확인 필요');
 if(!finite(q.volume24h)||q.volume24h<1e7||!finite(q.oiUSD)||q.oiUSD<1e6)blocks.push('거래대금 또는 미결제약정 부족');
 if(!finite(book.spread)||book.spread<0||book.spread>.001)blocks.push('호가 간격이 넓거나 호가 자료 없음');
 if(!finite(q.funding)||!finite(q.premium)||Math.abs(q.premium)>.01)blocks.push('펀딩비·가격 괴리 확인 필요');
 if(!(ind.atr>0)||ind.atr/rows.at(-1).close>.05)blocks.push('변동폭 부족 또는 과도한 봉 변동성');
 const pattern=detect(rows,ind),base=50+(ind.ema20>ind.ema50?15:-15)+(rows.at(-1).close>ind.ema50?10:-10)+(ind.macd>0?8:ind.macd<0?-8:0)+(ind.rsi>50?5:ind.rsi<50?-5:0)+(ind.vwap===null?0:rows.at(-1).close>ind.vwap?5:-5);
 const costs=finite(q.premium)?Math.abs(q.premium)*1000:0,ls=clamp(base+(pattern.side==='long'&&pattern.confirmed?10:0)+(hi.bias==='long'?7:hi.bias==='short'?-7:0)-Math.max(q.funding||0,0)*24*3000-costs),ss=clamp(100-base+(pattern.side==='short'&&pattern.confirmed?10:0)+(hi.bias==='short'?7:hi.bias==='long'?-7:0)-Math.max(-(q.funding||0),0)*24*3000-costs);
 const bias=ls-ss>=12?'long':ss-ls>=12?'short':'neutral',long=levels(rows,ind,pattern,'long',q.funding,step),short=levels(rows,ind,pattern,'short',q.funding,step),side=pattern.side||bias,plan=side==='long'?long:side==='short'?short:null;
 if(!pattern.confirmed)blocks.push('거래량을 동반한 진입 패턴이 아직 확인되지 않음');
 if(side==='neutral'||hi.bias!==side||ind.bias!==side)blocks.push('선택 봉과 '+higher+' 흐름이 일치하지 않음');
 if(ind.efficiency<.25)blocks.push('최근 20봉이 횡보에 가까움');
 if(side==='long'&&ind.rsi>75||side==='short'&&ind.rsi<25)blocks.push('단기 과열 · 추격 진입 대기');
 if(!plan?.valid||plan.rr<1.5)blocks.push('비용 반영 손익비 1.5 이상인 목표가 없음');
 if(!plan||!finite(mark)||mark<plan.lowEntry||mark>plan.highEntry)blocks.push('현재가가 확인 봉의 진입 관심 구간 밖에 있음');
 if((side==='long'?ls:ss)<65)blocks.push('방향 조건 점수 부족');
 const action=blocks.length?'관망':side==='long'?'롱 조건 충족':'숏 조건 충족';
 return {action,blocks,ind,hi,higher,pattern,bias,longScore:Math.round(ls),shortScore:Math.round(ss),long,short,side,signalAt:rows.at(-1).end,expiresAt:rows.at(-1).end+step+15000,rows};
}
const HORIZONS={'5m':[12,36,72],'15m':[8,24,48],'1d':[3,7,14]};
function projection(rows,ind,interval,bars){
 if(!HORIZONS[interval]?.includes(bars)||!rows?.length||!ind||!finite(ind.atr)||ind.atr<0)return [];
 const price=rows.at(-1).close;if(!finite(price)||price<=0)return [];
 const drift=clamp((ind.ema20-ind.ema50)/20,-.25*ind.atr,.25*ind.atr)/price,tau=interval==='1d'?5:24,sigma=ind.atr/price*.8;
 // Horizon only truncates this shared, uncalibrated trend scenario; it never changes entry rules.
 return Array.from({length:bars+1},(_,t)=>{const c=drift*tau*(1-Math.exp(-t/tau)),w=sigma*Math.sqrt(t);return {t,v:price*Math.exp(c),low:price*Math.exp(c-w),high:price*Math.exp(c+w)};});
}
const api={MS,HIGHER,HORIZONS,projection,candles,indicators,detect,levels,analyze};if(typeof module!=='undefined')module.exports=api;else root.PerpEngine=api;
})(typeof window!=='undefined'?window:globalThis);
