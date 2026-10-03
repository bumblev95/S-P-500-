(function(root){
'use strict';
const finite=Number.isFinite,esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),clamp=v=>Math.max(0,Math.min(100,v));
const count=x=>x.toLocaleString('ko-KR',{maximumFractionDigits:2}),compact=x=>new Intl.NumberFormat('en-US',{notation:'compact',maximumFractionDigits:2}).format(x);
function bars(rows,{max=100,signed=false,caption=''}={}){
 const scale=finite(max)&&max>0?max:1;
 return '<div class="visualBars">'+rows.map(r=>{const valid=finite(r.value),width=valid?clamp(Math.abs(r.value)/scale*100)/(signed?2:1):0,color=r.color||(signed&&r.value<0?'#ff93a3':'#7bf1cb'),label=valid?(r.text??String(r.value)):'자료 없음',left=signed?(r.value<0?50-width:50):0;
 return '<div class="visualRow"><div class="visualLabel"><span>'+esc(r.label)+'</span><b>'+esc(label)+'</b></div><div class="visualTrack '+(signed?'signed ':'')+(!valid?'missing':'')+'" role="img" aria-label="'+esc(r.label+': '+label)+'"><i style="left:'+left+'%;width:'+width+'%;background:'+color+'"></i></div></div>';}).join('')+(caption?'<p class="visualCaption">'+esc(caption)+'</p>':'')+'</div>';
}
function supplyParts(s){
 const c=s?.circulating,t=s?.total,m=s?.maximum;
 if(!finite(c)||!finite(t)||c<0||t<=0||c>t*1.0001)return null;
 const circ=Math.min(c,t),hasMax=finite(m)&&m>0&&m>=t/1.0001,total=hasMax?Math.max(m,t):t;
 return {total,circulating:circ,basis:hasMax?'최대 발행량 대비':'현재 총발행량 대비',hasMax,segments:[{label:'유통 중',value:circ,color:'#7bf1cb'},{label:'발행됐지만 미유통',value:t-circ,color:'#b69cff'},...(hasMax?[{label:'아직 미발행',value:total-t,color:'#35506a'}]:[])]};
}
function supply(s){
 const parts=supplyParts(s);if(!parts)return '<div class="visualEmpty">유통량 자료 확인 필요</div>';
 let offset=0;const pct=parts.circulating/parts.total*100,aria=parts.basis+' 유통 '+pct.toFixed(1)+'%. '+parts.segments.map(r=>r.label+' '+count(r.value)+'개').join(', ');
 const rings=parts.segments.map(r=>{const length=r.value/parts.total*100,start=offset;offset+=length;return length>0?'<circle cx="100" cy="100" r="72" pathLength="100" fill="none" stroke="'+r.color+'" stroke-width="23" stroke-dasharray="'+length+' '+(100-length)+'" stroke-dashoffset="'+(-start)+'" transform="rotate(-90 100 100)"><title>'+esc(r.label)+' '+count(r.value)+'개</title></circle>':'';}).join('');
 return '<div class="supplyVisual"><svg viewBox="0 0 200 200" role="img" aria-label="'+esc(aria)+'">'+rings+'<text x="100" y="98" text-anchor="middle" fill="#ecf3fa" font-size="30" font-weight="750">'+pct.toFixed(1)+'%</text><text x="100" y="121" text-anchor="middle" fill="#9aacc1" font-size="14">유통 중</text></svg><p class="visualCaption">'+parts.basis+'</p><div class="supplyLegend">'+parts.segments.map(r=>'<div title="'+count(r.value)+'개"><span><i style="background:'+r.color+'"></i>'+esc(r.label)+'</span><b>'+compact(r.value)+' <small>'+((r.value/parts.total)*100).toFixed(1)+'%</small></b></div>').join('')+'</div></div>';
}
function rsi(value){
 if(!finite(value))return '<div class="visualEmpty">RSI 자료 없음</div>';
 return '<div class="rsiVisual"><div class="visualLabel"><span>RSI · 과열 확인</span><b>'+value.toFixed(1)+'</b></div><div class="rsiTrack" role="img" aria-label="RSI '+value.toFixed(1)+', 30 미만 과매도, 70 초과 과매수"><i style="left:'+clamp(value)+'%"></i></div><div class="rsiLabels"><span>과매도 &lt;30</span><span>중간</span><span>과매수 &gt;70</span></div></div>';
}
const tones={good:'#6ee7b7',warn:'#f9cf6b',bad:'#ff7f91',info:'#69d9f8',muted:'#71879b'};
function badge(label,tone='muted'){
 return '<span class="vi-badge vi-'+(Object.hasOwn(tones,tone)?tone:'muted')+'">'+esc(label)+'</span>';
}
// A discrete state uses its segment centre, never an invented probability.
// Missing/unknown values have no pointer and no highlighted segment.
function gauge({title,states,index=null,value='',description='',position=null}){
 const known=Number.isInteger(index)&&index>=0&&index<states.length;
 const current=known?states[index]:null,selected=known?(finite(position)?Math.max(0,Math.min(1,position)):(index+.5)/states.length):null;
 const point=p=>{const a=(180-180*p)*Math.PI/180;return [120+84*Math.cos(a),108-84*Math.sin(a)].map(v=>v.toFixed(2)).join(' ')};
 const paths=states.map((s,i)=>{const start=(s.from??i/states.length)+.008,end=(s.to??(i+1)/states.length)-.008,color=known?tones[s.tone]||tones.info:tones.muted;
  return '<path d="M '+point(start)+' A 84 84 0 0 1 '+point(end)+'" fill="none" stroke="'+color+'" stroke-width="17" stroke-linecap="round" opacity="'+(known&&i===index?'1':'.36')+'"/>';
 }).join('');
 const pointer=known?'<g class="vi-pointer" transform="rotate('+(-90+180*selected).toFixed(2)+' 120 108)"><path d="M 116 108 L 120 42 L 124 108 Z" fill="#edf6ff"/><circle cx="120" cy="108" r="7" fill="'+(tones[current.tone]||tones.info)+'" stroke="#edf6ff" stroke-width="2"/></g>':'';
 const text=value||current?.label||'판단 보류';
 return '<div class="vi-gauge '+(known?'':'vi-unknown')+'" data-indicator="'+esc(title)+'" data-state="'+esc(current?.key||'unknown')+'"><div class="vi-title">'+esc(title)+'</div><svg viewBox="0 0 240 126" role="img" aria-label="'+esc(title+': '+text+(known?'':' · 자료 확인 필요'))+'">'+paths+pointer+'</svg><strong class="vi-value vi-'+(current?.tone||'muted')+'">'+esc(text)+'</strong><div class="vi-scale" aria-hidden="true">'+states.map((s,i)=>'<span class="'+(known&&i===index?'vi-active vi-'+s.tone:'')+'">'+esc(s.label)+'</span>').join('')+'</div>'+(description?'<p class="vi-caption">'+esc(description)+'</p>':'')+'</div>';
}
function riskGauge(status){
 const states=[{key:'stable',label:'원활',tone:'good'},{key:'watch',label:'주의',tone:'warn'},{key:'risk',label:'경보',tone:'bad'}];
 return gauge({title:'시장 위험 상태',states,index:states.findIndex(s=>s.key===status),description:'관측된 지표 기준 · 위기 확률 아님'});
}
function entryGauge(code,value,options={}){
 const states=[{key:'avoid',label:'진입 보류',tone:'bad'},{key:'watch',label:'관망',tone:'warn'},{key:'buy',label:'진입 검토',tone:'good'}];
 const key=['pullback','confirm'].includes(code)?'watch':code;
 return gauge({title:options.title||'신규 진입 판단',states,index:states.findIndex(s=>s.key===key),value,description:'신규 진입 기준 · 보유 자산 매도와 별도'});
}
function entrySteps(code){
 const key=['pullback','confirm'].includes(code)?'watch':code;
 return steps([{key:'avoid',label:'진입 보류',tone:'bad'},{key:'watch',label:'관망',tone:'warn'},{key:'buy',label:'진입 검토',tone:'good'}],key,'신규 진입 판단');
}
function entryBadge(code,value){
 const key=['pullback','confirm'].includes(code)?'watch':code;
 return badge(value,{avoid:'bad',watch:'warn',buy:'good'}[key]||'muted');
}
function trendGauge(score,label){
 const ranges=[0,.35,.46,.60,.78,1],labels=['하락','약한 하락','혼조','상승','강한 상승'],colors=['bad','warn','warn','good','good'];
 const states=labels.map((s,i)=>({key:String(i),label:s,tone:colors[i],from:ranges[i],to:ranges[i+1]}));
 const valid=finite(score)&&score>=0&&score<=100,index=valid?(score>=78?4:score>=60?3:score>=46?2:score>=35?1:0):null;
 return gauge({title:'단기 추세 점수',states,index,position:valid?score/100:null,value:valid?score+'/100':'산출 보류',description:valid?label:'가격 이력 확인 필요'});
}
function directionGauge(side,value){
 const states=[{key:'short',label:'숏 검토',tone:'bad'},{key:'neutral',label:'관망',tone:'warn'},{key:'long',label:'롱 검토',tone:'good'}];
 return gauge({title:'단기 선물 진입',states,index:states.findIndex(s=>s.key===side),value,description:'방향 우세와 진입 조건을 함께 확인'});
}
function steps(states,key,title){
 const known=states.some(s=>s.key===key);
 return '<div class="vi-steps" role="group" aria-label="'+esc(title)+'">'+states.map(s=>'<span class="'+(known&&s.key===key?'vi-active vi-'+s.tone:'')+'"'+(known&&s.key===key?' aria-current="step"':'')+'>'+esc(s.label)+'</span>').join('')+'</div>';
}
function table(rows,caption='요약'){
 return '<table class="vi-summary"><caption>'+esc(caption)+'</caption><tbody>'+rows.map(([k,v])=>'<tr><th scope="row">'+esc(k)+'</th><td>'+esc(v??'자료 없음')+'</td></tr>').join('')+'</tbody></table>';
}
const api={bars,supplyParts,supply,rsi,badge,gauge,riskGauge,entryGauge,entrySteps,entryBadge,trendGauge,directionGauge,steps,table};if(typeof module!=='undefined')module.exports=api;else root.MarketVisuals=api;
})(typeof window!=='undefined'?window:globalThis);
