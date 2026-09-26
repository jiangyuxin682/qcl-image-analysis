const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('ui/static_processing/compare.js','utf8');
function setup(){
  const nodes=new Map(),requests=[];
  const $=s=>{if(!nodes.has(s))nodes.set(s,{replaceChildren(){this.cleared=true;}});return nodes.get(s);};
  const datasets=['a','b'].map(id=>({id,name:id,frame:{title:id,remove(){this.removed=true;}},committed:{normalization:{fields:{'has-gold':id}}}}));
  const c={$,datasets,info:datasets.slice(),selections:new Map([['a',{}],['b',{}]]),sharing:{normalization:true},firstCommitted:{normalization:'a'},shared:{},active:'a',desiredStep:8,revision:0,automaticColorLimits:false,managing:false,importing:false,
    tabs(){},broadcastPolicy(){},select:id=>c.active=id,loadComparison:async()=>{},groupSettings:s=>s,mergeSettings:(a,b)=>({...a,...b}),
    window:{prompt:()=> 'New name',confirm:()=>true},api:async(url,payload)=>{requests.push({url,payload});return {id:payload.id,name:payload.name,removed:true};}};
  vm.createContext(c);vm.runInContext(source.slice(source.indexOf('async function renameDataset('),source.indexOf('function select(id)')),c);
  return {c,$,requests};
}
test('renaming changes the server name and iframe title without replacing the dataset',async()=>{
  const {c,requests}=setup(),d=c.datasets[0];await c.renameDataset(d);
  assert.equal(d.name,'New name');assert.equal(d.frame.title,'New name');assert.equal(c.datasets[0],d);
  assert.equal(requests[0].url,'/api/datasets/rename');assert.equal(c.managing,false);
});
test('removal clears selection and changes the sharing source; last removal opens import',async()=>{
  const {c,$}=setup(),removed=c.datasets[0];await c.removeDataset(removed);
  assert.equal(removed.frame.removed,true);assert.equal(c.selections.has('a'),false);
  assert.equal(c.active,'b');assert.equal(c.firstCommitted.normalization,'b');assert.equal(c.shared.fields['has-gold'],'b');
  assert.equal(c.automaticColorLimits,true);assert.equal(c.info.length,1);
  await c.removeDataset(c.datasets[0]);assert.equal(c.datasets.length,0);assert.equal(c.active,null);
  assert.equal($('#import-folders').open,true);assert.equal(c.shared,null);
});
test('failed or cancelled removal leaves tabs and selection intact; busy tabs cannot be managed',async()=>{
  const {c,requests}=setup(),d=c.datasets[0];c.window.confirm=()=>false;await c.removeDataset(d);assert.equal(requests.length,0);
  c.window.confirm=()=>true;c.api=async()=>{throw Error('busy');};await c.removeDataset(d);
  assert.equal(c.datasets.length,2);assert.equal(c.selections.has('a'),true);assert.equal(d.frame.removed,undefined);
  d.busy=true;c.window.prompt=()=>{throw Error('must not prompt');};await c.renameDataset(d);await c.removeDataset(d);
});

test('tab buttons survive refreshes so double-click rename works; remove uses ×',()=>{
  const c={datasets:[{id:'a',name:'Dataset A',step:2}],active:'a',managing:false,importing:false,$$:()=>[],select(){},renameDataset:d=>c.renamed=d.id,removeDataset:d=>c.removed=d.id};
  const nodes=new Map();c.$=s=>{if(!nodes.has(s))nodes.set(s,c.el('div'));return nodes.get(s);};
  c.el=(tag,text)=>({tag,textContent:text,children:[],append(...items){this.children.push(...items);},insertBefore(item){this.children.unshift(item);},setAttribute(){}});
  vm.createContext(c);vm.runInContext(source.slice(source.indexOf('let comparisonTab='),source.indexOf('async function renameDataset(')),c);
  c.tabs();const button=c.datasets[0].tab.button;c.tabs();
  assert.equal(c.datasets[0].tab.button,button);button.ondblclick();assert.equal(c.renamed,'a');
  assert.equal(c.datasets[0].tab.remove.textContent,'×');c.datasets[0].tab.remove.onclick();assert.equal(c.removed,'a');
  assert.equal(c.datasets[0].tab.group.children.length,2);
});
