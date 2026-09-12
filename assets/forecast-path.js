(function(root){
  'use strict';
  function random(seed){let state=2166136261;for(const c of seed)state=Math.imul(state^c.charCodeAt(0),16777619);return()=>{state+=0x6D2B79F5;let t=state;t=Math.imul(t^t>>>15,t|1);t^=t+Math.imul(t^t>>>7,t|61);return((t^t>>>14)>>>0)/4294967296;};}
  function build(e,p,h,mode='sample',forecasts=null){
    const history=Array.from(new Map((e.history||[]).filter(q=>q.date<=e.asOf&&Number.isFinite(q.close)&&q.close>0).map(q=>[q.date,q])).values()).sort((a,b)=>a.date.localeCompare(b.date)).slice(-126);
    const aligned=history.at(-1)?.date===e.asOf&&Math.abs(history.at(-1)?.close/e.price-1)<.001;
    const returns=history.slice(1).map((q,i)=>Math.log(q.close/history[i].close));
    const sampled=mode==='sample'&&aligned&&returns.length>=20;
    if(forecasts&&[21,84,252].every(k=>forecasts[k]&&[forecasts[k].base,forecasts[k].bear,forecasts[k].bull].every(v=>Number.isFinite(v)&&v>0))){
      const knots=[{t:0,base:e.price,bear:e.price,bull:e.price},...[21,84,252].map(t=>({t,...forecasts[t]}))];
      const rng=random(e.symbol+'|'+e.asOf+'|shared-path-v2'),shock=[0];
      const mean=returns.length?returns.reduce((a,b)=>a+b,0)/returns.length:0;let start=0;
      for(let t=0;t<252;t++){
        if(sampled&&t%5===0)start=Math.floor(rng()*Math.max(1,returns.length-4));
        shock.push(shock.at(-1)+(sampled?returns[(start+t%5)%returns.length]-mean:0));
      }
      const points=Array.from({length:h+1},(_,t)=>{
        if(t===0)return {t,base:e.price,bear:e.price,bull:e.price};
        const i=knots.findIndex(q=>q.t>=t),a=knots[i-1],b=knots[i],r=(t-a.t)/(b.t-a.t);
        const bridge=sampled?shock[t]:0;
        const center=(1-r)*Math.log(a.base)+r*Math.log(b.base);
        const width=side=>Math.sqrt((1-r)*Math.log(a[side]/a.base)**2+r*Math.log(b[side]/b.base)**2);
        return {t,base:t===b.t&&!sampled?b.base:Math.exp(center+bridge),bear:t===b.t?b.bear:Math.exp(center-width('bear')),bull:t===b.t?b.bull:Math.exp(center+width('bull'))};
      });
      return {points,sampled,shared:true};
    }
    const shocks=[0],rng=random(e.symbol+'|'+e.asOf+'|'+h+'|path-v1');
    if(sampled){
      const mean=returns.reduce((a,b)=>a+b,0)/returns.length;
      let start=0;
      for(let i=0;i<h;i++){
        if(i%5===0)start=Math.floor(rng()*Math.max(1,returns.length-4));
        shocks.push(shocks.at(-1)+returns[(start+i%5)%returns.length]-mean);
      }
    }
    const points=Array.from({length:h+1},(_,t)=>{
      const ratio=t/h,center=p.learned?p.logReturn*ratio:p.dailyDrift*63*(1-Math.exp(-t/63));
      const lo=p.learned?center+(p.lowLogReturn-p.logReturn)*Math.sqrt(ratio):center-p.volatility*Math.sqrt(t/252);
      const hi=p.learned?center+(p.highLogReturn-p.logReturn)*Math.sqrt(ratio):center+p.volatility*Math.sqrt(t/252);
      // Unconditioned illustration, not a daily forecast. Its endpoint is not forced to the AI target.
      const bridge=sampled?shocks[t]:0;
      return {t,base:p.anchor*Math.exp(center+bridge),bear:p.anchor*Math.exp(lo),bull:p.anchor*Math.exp(hi)};
    });
    return {points,sampled};
  }
  const api={build};if(typeof module!=='undefined')module.exports=api;else root.ForecastPath=api;
})(typeof window!=='undefined'?window:globalThis);
