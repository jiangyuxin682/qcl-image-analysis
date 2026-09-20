// Run with node --test tests/test_processing_sharing.cjs.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../ui/static_processing/compare.js'),'utf8');
function workspace(){
  const datasets=['a','b'].map(id=>({id,frame:{contentWindow:{}},messages:[]}));
  let listener;
  const context={datasets,shared:null,active:'a',desiredStep:2,revision:0,location:{origin:'local'},
    tell:(d,m)=>d.messages.push(structuredClone(m)),tabs:()=>{},$:()=>({replaceChildren(){}}),
    window:{addEventListener:(type,fn)=>listener=fn}};
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('const sharing='),source.indexOf('function fill(')),context);
  vm.runInContext(source.slice(source.indexOf('function stable('),source.indexOf('async function loadComparison(')),context);
  return {datasets,context,send:(id,data)=>listener({origin:'local',source:datasets.find(d=>d.id===id).frame.contentWindow,data:{dataset:id,...data}})};
}
function settings(radius=30){return {mapping:{1658:[1601,1702]},fields:{'has-gold':'yes','reference-pixels':'100','rb-radius':String(radius),'r0-method':'brightest','r0-count':'5'}};}
test('all groups default shared; new folders inherit current settings',()=>{
  const w=workspace();w.send('a',{type:'shared',settings:settings()});
  w.send('b',{type:'ready'});
  const messages=w.datasets[1].messages;
  const policy=messages.find(m=>m.type==='sharing-policy');
  assert.equal(policy.multiple,true);assert.deepEqual(Object.values(policy.sharing),[true,true,true,true]);
  assert.deepEqual(messages.filter(m=>m.type==='shared').at(-1).settings,settings());
});
test('disabled group remains independent; re-enabling uses first committed folder, not tab order or last editor',()=>{
  const w=workspace();w.send('a',{type:'shared',settings:settings(30)});
  w.send('b',{type:'shared-commit',group:'processing',settings:settings(40)});
  w.send('a',{type:'shared-commit',group:'processing',settings:settings(50)});
  w.send('a',{type:'sharing-toggle',group:'processing',enabled:false});
  w.send('b',{type:'shared',settings:settings(90)});
  assert.equal(w.datasets[0].messages.filter(m=>m.type==='shared').at(-1).settings.fields['rb-radius'],undefined);
  w.send('a',{type:'sharing-toggle',group:'processing',enabled:true});
  for(const d of w.datasets){const patch=d.messages.filter(m=>m.type==='shared').at(-1).settings;
    assert.deepEqual(patch,{fields:{'rb-radius':'40'}});
  }
});
test('comparison enforces only enabled groups',()=>{
  const w=workspace();const a={mapping:{1:[0,2]},parameters:{fourier:{enabled:true}},has_gold:true,n_pixels:100,qc_settings:{},r0_selection:{method:'roi'}};
  const b={...a,mapping:{3:[2,4]},parameters:{fourier:{enabled:false}},has_gold:false,r0_selection:{method:'darkest',count:5}};
  assert.notEqual(w.context.signature(a),w.context.signature(b));
  for(const group of ['spectral','normalization','processing','analyte'])w.send('a',{type:'sharing-toggle',group,enabled:false});
  assert.equal(w.context.signature(a),w.context.signature(b));
});
test('turning off spectral sharing never sends a mapping to another folder',()=>{
  const w=workspace();w.send('a',{type:'shared',settings:settings()});
  w.send('a',{type:'sharing-toggle',group:'spectral',enabled:false});
  const different=settings();different.mapping={1700:[1600,1800]};
  w.send('b',{type:'shared',settings:different});
  assert.equal(w.datasets[0].messages.filter(m=>m.type==='shared').at(-1).settings.mapping,undefined);
});
test('applying a partial shared group preserves independent mapping and fields',()=>{
  const app=fs.readFileSync(require('node:path').join(__dirname,'../ui/static_processing/app.js'),'utf8');
  const nodes=new Map(Object.entries({'rb-radius':{value:'30'},'r0-method':{value:'darkest'},'r0-count':{value:'12'},'r0-restrict':{checked:true}}));
  const $=s=>{const id=s.slice(1);if(!nodes.has(id))nodes.set(id,{});return nodes.get(id)};
  const invalidated=[];
  const context={$,state:{discovery:{},mapping:{1750:[1700,1800]},step:5,maxStep:8},applyingShared:false,
    sharedFieldIds:['rb-radius','r0-method','r0-count'],sharedGroups:{normalization:['has-gold']},
    sharedSnapshot:()=>({mapping:{1750:[1700,1800]},fields:{'rb-radius':'30','r0-method':'darkest','r0-count':'12'}}),
    invalidateFrom:n=>invalidated.push(n),filterMode:()=>{},go:()=>{},notify:()=>{},normalizationControls:()=>{}};
  vm.createContext(context);
  vm.runInContext(app.slice(app.indexOf('function applyShared('),app.indexOf("window.addEventListener('message',event=>")),context);
  context.applyShared({fields:{'rb-radius':'40'}});
  assert.deepEqual(context.state.mapping,{1750:[1700,1800]});assert.deepEqual(invalidated,[6]);
  assert.equal($('#r0-method').value,'darkest');assert.equal($('#r0-count').value,'12');
  assert.equal($('#rb-radius').value,'40');
});
test('imported ZIP keeps committed settings instead of being overwritten by workspace defaults',()=>{
  const w=workspace();w.send('a',{type:'shared',settings:settings(30)});
  w.send('a',{type:'shared-commit',group:'processing',settings:settings(30)});
  w.datasets[1].messages=[];
  w.send('b',{type:'ready',reproduced:true,settings:settings(50)});
  assert.equal(w.datasets[1].messages.some(m=>m.type==='shared'||m.type==='request-shared'),false);
  assert.equal(w.datasets[1].committed.processing.fields['rb-radius'],'50');
  assert.equal(w.datasets[0].messages.some(m=>m.type==='shared'&&m.settings.fields['rb-radius']==='50'),false);
});

test('first imported processed folder becomes the parameter source for unprocessed tabs',()=>{
  const w=workspace();w.send('a',{type:'shared',settings:settings(30)});
  w.send('b',{type:'ready',reproduced:true,settings:settings(50)});
  assert.equal(w.context.shared.fields['rb-radius'],'50');
  assert.equal(w.datasets[0].messages.some(m=>m.type==='shared'&&m.settings.fields['rb-radius']==='50'),true);
});
