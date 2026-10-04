(function(root){
  'use strict';
  // Use the identifiers from your own approved AdSense account.
  // Keep disabled until site approval, hosting and Privacy & messaging are ready.
  const config=Object.freeze({
    enabled:false,
    publisherId:'',
    slots:Object.freeze({home:'',stocks:''})
  });
  if(typeof module!=='undefined')module.exports=config;
  else root.SiteAdsConfig=config;
})(typeof window!=='undefined'?window:globalThis);
