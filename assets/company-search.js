(function(root){
'use strict';
const names=typeof module!=='undefined'?require('./company-names.js'):(root.CompanyNames||{});
const symbol=value=>String(value||'').trim().toUpperCase().replace(/\./g,'-');
const normalize=value=>String(value||'').normalize('NFKC').toLowerCase().replace(/[^\p{L}\p{N}]/gu,'');
const record=value=>Object.hasOwn(names,symbol(value))?names[symbol(value)]:null;
function koreanName(value){return record(value)?.[0]||'';}
function englishName(value,fallback=''){return fallback||record(value)?.[1]||'';}
function name(value,fallback=''){return koreanName(value)||englishName(value,fallback)||String(value||'');}
function terms(item){
 const data=record(item.symbol),english=englishName(item.symbol,item.name),display=name(item.symbol,item.name);
 return [...new Set([item.symbol,display,english,...(data?.slice(2)||[]),display+' '+item.symbol,item.symbol+' '+display,english+' '+item.symbol,item.symbol+' '+english].map(normalize).filter(Boolean))];
}
function score(item,query){
 const q=normalize(query);if(!q)return Infinity;
 if(normalize(item.symbol)===q)return 0;
 const values=terms(item);if(values.includes(q))return 1;
 if(values.some(value=>value.startsWith(q)))return 2;
 return values.some(value=>value.includes(q))?3:Infinity;
}
function matches(item,query){return !String(query||'').trim()||Number.isFinite(score(item,query));}
function search(items,query,limit=8){
 const seen=new Set();
 return (items||[]).filter(item=>{
  const key=symbol(item?.symbol);if(!key||seen.has(key))return false;seen.add(key);return true;
 }).map(item=>({item,score:score(item,query)})).filter(row=>Number.isFinite(row.score))
  .sort((a,b)=>a.score-b.score||symbol(a.item.symbol).localeCompare(symbol(b.item.symbol),'en'))
  .slice(0,Math.max(0,limit)).map(row=>row.item);
}
function resolve(items,query){
 const found=search(items,query,Infinity),exact=found.filter(item=>score(item,query)<=1);
 const ticker=found.find(item=>score(item,query)===0);if(ticker)return ticker;
 return exact.length===1?exact[0]:exact.length>1?null:found.length===1?found[0]:null;
}
function mount({input,host,items=[],onSelect}){
 const menu=host.querySelector('[data-company-menu]'),options=host.querySelector('[data-company-options]'),status=host.querySelector('[data-company-status]');
 const doc=input.ownerDocument;let results=[],active=-1,selected=null,composing=false,blurTimer=null;
 input.setAttribute('role','combobox');input.setAttribute('aria-autocomplete','list');
 input.setAttribute('aria-haspopup','listbox');input.setAttribute('aria-controls',options.id);input.setAttribute('aria-expanded','false');
 function close(){menu.hidden=true;input.setAttribute('aria-expanded','false');input.removeAttribute('aria-activedescendant');active=-1;}
 function highlight(index){
  active=index;Array.from(options.children).forEach((option,i)=>option.setAttribute('aria-selected',String(i===index)));
  if(index<0)input.removeAttribute('aria-activedescendant');else{
   input.setAttribute('aria-activedescendant',options.children[index].id);options.children[index].scrollIntoView({block:'nearest'});
  }
 }
 function choose(item){
  if(blurTimer)clearTimeout(blurTimer);selected=item;input.value=name(item.symbol,item.name)+' · '+item.symbol;close();onSelect(item.symbol);
 }
 function render(){
  if(composing)return;const query=input.value;
  if(!query.trim()){close();return;}
  const all=search(items,query,Infinity);results=all.slice(0,8);active=-1;options.replaceChildren();input.removeAttribute('aria-activedescendant');
  for(const [i,item] of results.entries()){
   const option=doc.createElement('button');option.type='button';option.className='cs-option';option.id=options.id+'-'+i;option.tabIndex=-1;
   option.setAttribute('role','option');option.setAttribute('aria-selected','false');
   const label=doc.createElement('span');label.className='cs-name';label.textContent=name(item.symbol,item.name);
   const ticker=doc.createElement('b');ticker.className='cs-symbol';ticker.textContent=item.symbol;option.append(label,ticker);
   option.addEventListener('mousedown',event=>event.preventDefault());option.addEventListener('click',()=>choose(item));options.append(option);
  }
  status.textContent=all.length>8?'8개 표시 · 검색어를 더 입력하세요':all.length?'검색 결과 '+all.length+'개':'일치하는 종목이 없어요';
  menu.hidden=false;input.setAttribute('aria-expanded','true');
 }
 input.addEventListener('compositionstart',()=>{composing=true;close();});
 input.addEventListener('compositionend',()=>{composing=false;render();});
 input.addEventListener('input',event=>{if(!event.isComposing&&!composing)render();});
 input.addEventListener('focus',()=>{if(blurTimer)clearTimeout(blurTimer);if(selected&&input.value===name(selected.symbol,selected.name)+' · '+selected.symbol)input.select();});
 input.addEventListener('blur',()=>{blurTimer=setTimeout(close,150);});
 input.addEventListener('keydown',event=>{
  if(event.isComposing||composing||event.keyCode===229)return;
  if(event.key==='Escape'){event.preventDefault();if(selected)input.value=name(selected.symbol,selected.name)+' · '+selected.symbol;close();}
  else if(event.key==='Tab')close();
  else if(event.key==='ArrowDown'||event.key==='ArrowUp'){
   event.preventDefault();if(menu.hidden)render();if(results.length)highlight(active<0?(event.key==='ArrowDown'?0:results.length-1):(active+(event.key==='ArrowDown'?1:-1)+results.length)%results.length);
  }else if(event.key==='Enter'){
   event.preventDefault();const match=active>=0&&!menu.hidden?results[active]:resolve(items,input.value);
   if(match){if(blurTimer)clearTimeout(blurTimer);choose(match);input.blur();}
   else{render();if(results.length>1)status.textContent='여러 종목이 있어요 · 목록에서 선택하세요';}
  }
 });
 const api={
  setItems(next){items=next||[];input.disabled=!items.length;close();},
  setSelection(value){const item=items.find(row=>symbol(row.symbol)===symbol(value));if(item){selected=item;input.value=name(item.symbol,item.name)+' · '+item.symbol;}close();}
 };
 api.setItems(items);return api;
}
const api={symbol,normalize,koreanName,englishName,name,matches,search,resolve,mount};
if(typeof module!=='undefined')module.exports=api;else root.CompanySearch=api;
})(typeof window!=='undefined'?window:globalThis);
