'use strict';

// Fixed before inspecting this experiment's results.  Every method uses the
// same 14-day momentum direction and signal timestamps; only exits differ.
const METHODS=Object.freeze([
 {id:'baseline',name:'기존 2.5 ATR 추적',trailAtr:2.5,holdDays:30,reverse:true},
 {id:'trail2',name:'빠른 2 ATR 추적',trailAtr:2,holdDays:30,reverse:true},
 {id:'trail3',name:'느린 3 ATR 추적',trailAtr:3,holdDays:30,reverse:true},
 {id:'trail35',name:'넓은 3.5 ATR 추적',trailAtr:3.5,holdDays:30,reverse:true},
 {id:'target4',name:'4 ATR 목표 + 추적',trailAtr:2.5,targetAtr:4,holdDays:30,reverse:true},
 {id:'target6',name:'6 ATR 목표 + 추적',trailAtr:2.5,targetAtr:6,holdDays:30,reverse:true},
 {id:'fixed2r',name:'고정 2R 목표',trailAtr:2.5,targetAtr:5,trailing:false,holdDays:30,reverse:true},
 {id:'hold14',name:'최대 14일 + 추적',trailAtr:2.5,holdDays:14,reverse:true},
 {id:'trailOnly',name:'반전 청산 없음 + 추적',trailAtr:2.5,holdDays:30,reverse:false}
]);

function apply(method,q){
 if(!method||!Number.isFinite(q?.atr)||!Number.isFinite(q?.price))return q||{side:null};
 const direction=q.side==='long'?1:q.side==='short'?-1:0,d=method.trailAtr*q.atr;
 const out={...q,holdBars:method.holdDays*96,exitLong:method.reverse?q.exitLong:false,exitShort:method.reverse?q.exitShort:false};
 if(direction)out.stop=q.price-direction*d;
 out.trailLong=method.trailing===false?null:q.price-d;
 out.trailShort=method.trailing===false?null:q.price+d;
 out.target=direction&&method.targetAtr?q.price+direction*method.targetAtr*q.atr:null;
 return out;
}

module.exports={METHODS,apply};
