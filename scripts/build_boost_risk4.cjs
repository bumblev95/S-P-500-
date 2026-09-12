'use strict';
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),F=require('./boost_risk4_forward.cjs');
const sha=x=>crypto.createHash('sha256').update(JSON.stringify(x)).digest('hex');
function build(market,now,root){
 const dir=path.join(root,'boost-risk4'),file=path.join(dir,'state.json');let state;
 try{state=JSON.parse(fs.readFileSync(file));}catch(e){if(e.code!=='ENOENT')throw e;if(fs.existsSync(path.join(dir,'experiment.json')))throw Error('Missing existing risk4 state; restore it rather than reset');}
 const study=JSON.parse(fs.readFileSync(path.join(root,'leverage-lab/latest.json'))),r=study.fixed.find(r=>r.method==='boost_swing'&&r.policy==='risk4'&&r.leverage===5);
 if(!r?.researchScreen||r.trades!==212)throw Error('Selected research identity missing');
 state=state||{createdAt:now,ledgerHash:null,account:F.create(now)};
 if(state.createdAt!==state.account.createdAt)throw Error('Forward account start changed');
 const experiment={createdAt:state.createdAt,profileVersion:F.CONFIG.profileVersion,config:F.CONFIG,selected:{method:r.method,policy:r.policy,leverage:r.leverage,return:r.return,maxDrawdown:r.maxDrawdown},historicalMarket:'Binance USD-M futures',forwardMarket:'Hyperliquid public perpetual OHLC and hourly funding',execution:'Only posted observations can create future orders or stop updates; delayed jobs never invent missed past signals.'};
 const experimentFile=path.join(dir,'experiment.json');if(fs.existsSync(experimentFile)&&JSON.stringify(JSON.parse(fs.readFileSync(experimentFile)))!==JSON.stringify(experiment))throw Error('Frozen forward experiment changed');
 const prior=state.account,next=F.run(prior,market,now);
 if(next.lastProcessed===null)throw Error('New account requires completed market context');
 if(JSON.stringify(next.trades.slice(0,prior.trades.length))!==JSON.stringify(prior.trades))throw Error('Closed trades changed');
 const write=(name,value)=>{const dest=path.join(dir,name);fs.mkdirSync(path.dirname(dest),{recursive:true});fs.writeFileSync(dest+'.tmp',JSON.stringify(value));fs.renameSync(dest+'.tmp',dest);};
 const events=next.events.slice(prior.events.length);
 if(events.length||!state.ledgerHash){const record={profileVersion:F.CONFIG.profileVersion,recordedAt:now,previousHash:state.ledgerHash,events,equity:F.equity(next)},hash=sha(record);write('ledger/'+now+'-'+hash.slice(0,12)+'.json',{...record,hash});state.ledgerHash=hash;}
 state.account=next;state.updatedAt=now;write('state.json',state);
 write('experiment.json',experiment);
 const account=F.report(next);account.events=account.events.slice(-60);
 return {config:F.CONFIG,experiment,forward:{createdAt:state.createdAt,accounts:{crypto:account}},research:{start:study.start,end:study.end,result:r}};
}
module.exports={build};
