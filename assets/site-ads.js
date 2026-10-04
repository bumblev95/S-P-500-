(function(root){
  'use strict';
  const PROVIDER='https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js';
  const LOAD_TIMEOUT=15000;
  let providerPromise;

  function adSettings(config,name){
    if(!config||config.enabled!==true)return null;
    const publisherId=config.publisherId,slot=config.slots?.[name];
    if(typeof publisherId!=='string'||!/^ca-pub-\d{16}$/.test(publisherId))return null;
    if(['ca-pub-0000000000000000','ca-pub-1234567890123456'].includes(publisherId))return null;
    if(typeof slot!=='string'||!/^\d{1,20}$/.test(slot)||/^0+$/.test(slot))return null;
    return {publisherId,slot};
  }

  function loadProvider(doc,publisherId){
    if(providerPromise)return providerPromise;
    providerPromise=new Promise((resolve,reject)=>{
      const script=doc.createElement('script');
      script.async=true;
      script.crossOrigin='anonymous';
      script.src=PROVIDER+'?client='+encodeURIComponent(publisherId);
      script.setAttribute('data-site-ads-provider','adsense');
      const timer=root.setTimeout(()=>reject(Error('Ad provider unavailable')),LOAD_TIMEOUT);
      script.onload=()=>{root.clearTimeout(timer);resolve();};
      script.onerror=()=>{root.clearTimeout(timer);reject(Error('Ad provider unavailable'));};
      doc.head.appendChild(script);
    });
    return providerPromise;
  }

  async function mount(wrapper,settings){
    if(wrapper.dataset.adState)return;
    wrapper.dataset.adState='loading';
    try{
      await loadProvider(wrapper.ownerDocument,settings.publisherId);
      const body=wrapper.querySelector('[data-site-ad-body]');
      if(!body)throw Error('Missing ad container');
      const ins=wrapper.ownerDocument.createElement('ins');
      ins.className='adsbygoogle SiteAd_'+wrapper.dataset.siteAd;
      ins.style.display='block';
      ins.setAttribute('data-ad-client',settings.publisherId);
      ins.setAttribute('data-ad-slot',settings.slot);
      body.appendChild(ins);
      wrapper.hidden=false;
      await new Promise(resolve=>root.requestAnimationFrame(resolve));
      if(body.getBoundingClientRect().width<200)throw Error('Ad container too narrow');
      const observer=new root.MutationObserver(()=>{
        const status=ins.getAttribute('data-ad-status');
        if(['filled','unfilled','unfill-optimized'].includes(status)){
          // Only collapse a confirmed empty unit; don't hide a pending or filled ad.
          // Google manages the content of an optimized empty unit itself.
          wrapper.hidden=status==='unfilled';
          wrapper.dataset.adState=status;
          observer.disconnect();
        }
      });
      observer.observe(ins,{attributes:true,attributeFilter:['data-ad-status']});
      try{
        root.adsbygoogle=root.adsbygoogle||[];
        root.adsbygoogle.push({});
      }catch(error){observer.disconnect();throw error;}
    }catch(_){
      wrapper.hidden=true;
      wrapper.dataset.adState='unavailable';
    }
  }

  function init(){
    if(typeof document==='undefined')return;
    document.querySelectorAll('[data-site-ad]').forEach(wrapper=>{
      const settings=adSettings(root.SiteAdsConfig,wrapper.dataset.siteAd);
      if(!settings||wrapper.dataset.adState)return;
      // Defer provider loading until the user approaches this part of the page.
      if(typeof root.IntersectionObserver==='function'){
        // A hidden ad has no geometry: observe its visible, stable anchor instead.
        const anchor=wrapper.previousElementSibling||wrapper.parentElement;
        wrapper.dataset.adState='scheduled';
        const observer=new root.IntersectionObserver(entries=>{
          if(entries.some(entry=>entry.isIntersecting)){
            observer.disconnect();
            delete wrapper.dataset.adState;
            mount(wrapper,settings);
          }
        },{rootMargin:'200px 0px'});
        observer.observe(anchor);
      }else mount(wrapper,settings);
    });
  }

  const api={adSettings,init};
  if(typeof module!=='undefined')module.exports=api;
  else root.SiteAds=api;
  if(typeof document!=='undefined'){
    if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});
    else init();
  }
})(typeof window!=='undefined'?window:globalThis);
