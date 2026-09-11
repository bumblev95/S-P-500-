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
const api={bars,supplyParts,supply,rsi};if(typeof module!=='undefined')module.exports=api;else root.MarketVisuals=api;
})(typeof window!=='undefined'?window:globalThis);
