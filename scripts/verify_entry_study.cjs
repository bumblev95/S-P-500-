'use strict';
const fs=require('node:fs'),path=require('node:path'),cp=require('node:child_process');
const Study=require('./entry_study.cjs'),Builder=require('./build_entry_study.cjs');
function verify(root=path.resolve(__dirname,'..'),base=null){
 const folder=path.join(root,'simulation/entry-study');let count=0;
 if(base){
  const changed=cp.execFileSync('git',['diff','--name-status','--no-renames',base,'--','simulation/entry-study'],{cwd:root,encoding:'utf8'});
  for(const row of changed.trim().split('\n').filter(Boolean)){
   const [status,file]=row.split('\t');
   if((file.endsWith('/manifest.json')||file.includes('/ledger/'))&&status!=='A')throw Error('Append-only study file changed/deleted: '+file);
  }
 }
 if(fs.existsSync(folder))for(const version of fs.readdirSync(folder)){
  const dir=path.join(folder,version);if(!fs.statSync(dir).isDirectory())continue;
  const loaded=Builder.load(dir,{checkCode:version===Study.VERSION});
  if(loaded)count+=loaded.files.length;
 }
 console.log('Entry forward study: '+count+' immutable records verified; no automatic promotion.');
 return count;
}
if(require.main===module){
 const args=process.argv.slice(2),i=args.indexOf('--base');
 if(args.length&&!(i===0&&args.length===2))throw Error('Usage: node scripts/verify_entry_study.cjs [--base git-ref]');
 verify(undefined,i===0?args[1]:null);
}
module.exports={verify};
