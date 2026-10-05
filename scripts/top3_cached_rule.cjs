'use strict';
// Exact runtime cache for repeated date validation, not a changed trading rule.
// Every date is passed through the original predicate on first use.
const fs=require('node:fs'),Module=require('node:module'),path=require('node:path');
function loadCachedRule(filename){
 const source=fs.readFileSync(filename,'utf8');
 const target="const validDate=d=>/^\\d{4}-\\d{2}-\\d{2}$/.test(d)&&finite(Date.parse(d))&&new Date(d).toISOString().slice(0,10)===d;";
 if(!source.includes(target))throw Error('Date predicate changed; review cache adapter');
 const replacement=target.replace('const validDate=','const originalValidDate=')+
  "\n  const dateValidationCache=new Map();\n  const validDate=d=>{if(!dateValidationCache.has(d))dateValidationCache.set(d,originalValidDate(d));return dateValidationCache.get(d);};";
 const adapted=source.replace(target,replacement),m=new Module(filename+'-research-cache',module);
 m.filename=filename;m.paths=Module._nodeModulePaths(path.dirname(filename));m._compile(adapted,filename);
 return m.exports;
}
module.exports={loadCachedRule};
