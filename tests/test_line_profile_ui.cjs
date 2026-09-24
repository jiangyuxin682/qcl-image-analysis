const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../ui/static_processing/app.js'),'utf8');
function setup(){
  const nodes=new Map();const $=s=>{if(!nodes.has(s))nodes.set(s,{value:s.includes('pattern')?'pattern0':'1658'});return nodes.get(s)};
  const context={$, $$:()=>[],lineProfile:{start:null,end:null,result:null,revision:0},
    state:{step:8,viewEpoch:1,mode:null,canvases:[],cnr:[{cnr:5}],rois:{background:{x_min:0},target:{x_min:10}}},
    drawAll:()=>{},api:async()=>{throw Error('unused')}};
  vm.createContext(context);vm.runInContext(fs.readFileSync(require('node:path').join(__dirname,'../ui/static_processing/line_profile.js'),'utf8'),context);vm.runInContext(source.slice(source.indexOf('// Section 8 line inspection')),context);
  return context;
}
test('endpoints can be selected across images without changing CNR; clear removes line',()=>{
  const c=setup();let requests=0;c.refreshLineProfile=()=>requests++;
  const before=JSON.stringify({cnr:c.state.cnr,rois:c.state.rois});
  c.$('#profile-select').onclick();
  c.selectProfilePoint({data:{width:20,height:10}},{x:2.3,y:1.2});
  c.selectProfilePoint({data:{width:20,height:10}},{x:20,y:10});
  assert.equal(JSON.stringify(c.lineProfile.start),'{"x":2,"y":1}');
  assert.equal(JSON.stringify(c.lineProfile.end),'{"x":19,"y":1}');
  assert.equal(requests,1);assert.equal(c.state.mode,null);
  assert.equal(JSON.stringify({cnr:c.state.cnr,rois:c.state.rois}),before);
  c.$('#profile-clear').onclick();assert.equal(c.lineProfile.start,null);assert.equal(c.lineProfile.end,null);
});
test('clearing while a profile is loading discards its response',async()=>{
  const c=setup();c.lineProfile.start={x:0,y:0};c.lineProfile.end={x:2,y:2};
  let resolve;c.api=()=>new Promise(r=>resolve=r);
  const pending=c.refreshLineProfile();c.clearLineProfile();resolve({profiles:{raw:[1,2]}});await pending;
  assert.equal(c.lineProfile.result,null);
});

test('vertical selection locks x; same-axis endpoint is rejected',()=>{
  const c=setup();let requests=0;c.refreshLineProfile=()=>requests++;
  c.$('#profile-direction').value='vertical';c.$('#profile-select').onclick();
  const view={data:{width:20,height:10}};
  c.selectProfilePoint(view,{x:2,y:1});c.selectProfilePoint(view,{x:8,y:1});
  assert.equal(c.lineProfile.end,null);assert.equal(requests,0);
  c.selectProfilePoint(view,{x:8,y:7});
  assert.equal(JSON.stringify(c.lineProfile.end),'{"x":2,"y":7}');assert.equal(requests,1);
  c.$('#profile-direction').onchange();assert.equal(c.lineProfile.start,null);
});
function comparisonSetup(){
  function el(tag,text){return {tag,text,children:[],style:{},value:'',append(...nodes){this.children.push(...nodes)},setAttribute(){},querySelector(){return null},getBoundingClientRect(){return {left:0,top:0,width:100,height:50}}};}
  const calls=[],plots=[];let resolve;
  const context={QCLImages:{eventPoint:e=>e},el,revision:1,datasets:[],URLSearchParams,api:(url,payload)=>{calls.push({url,payload});return new Promise(r=>resolve=r)}};
  vm.createContext(context);vm.runInContext(fs.readFileSync(require('node:path').join(__dirname,'../ui/static_processing/line_profile.js'),'utf8'),context);
  context.QCLLine.drawLine=()=>{};context.QCLLine.renderPlot=(...args)=>plots.push(args);
  const compare=fs.readFileSync(require('node:path').join(__dirname,'../ui/static_processing/compare.js'),'utf8');
  vm.runInContext(compare.slice(compare.indexOf('function attachComparisonProfile(')),context);
  const choice={pattern:'pattern3'},card=el('div'),img=el('img');
  const options={card,img,overlay:el('svg'),data:{width:20,height:10},dataset:{id:'folder-b',name:'B',has_gold:false},choice,kind:'raw',wn:1658,current:1};
  context.attachComparisonProfile(options);
  const click=(x,y)=>img.onpointerdown({button:0,clientX:x,clientY:y,preventDefault(){}});
  return {context,options,choice,card,img,calls,plots,click,resolve:result=>resolve(result)};
}
test('comparison profile targets the correct folder, snaps horizontal, and ignores a cleared response',async()=>{
  const c=comparisonSetup();const toolbar=c.card.children[0];
  toolbar.children[1].onclick();c.click(10,10);c.click(80,40);
  assert.equal(c.calls.length,1);assert.match(c.calls[0].url,/dataset=folder-b/);
  assert.equal(JSON.stringify(c.calls[0].payload),JSON.stringify({pattern:'pattern3',wavenumber:1658,start:{x:2,y:2},end:{x:16,y:2}}));
  toolbar.children[2].onclick();c.resolve({});await new Promise(r=>setImmediate(r));
  assert.equal(c.plots.length,0);assert.equal(c.choice.line.end,null);
});
test('comparison vertical profile renders the current stage and survives refresh',async()=>{
  const c=comparisonSetup(),toolbar=c.card.children[0],direction=toolbar.children[0].children[0];
  direction.value='vertical';direction.onchange();toolbar.children[1].onclick();c.click(10,10);c.click(80,40);
  assert.equal(JSON.stringify(c.calls[0].payload.end),'{"x":2,"y":8}');
  c.resolve({start:{x:2,y:2},end:{x:2,y:8},distance:[0,6]});await new Promise(r=>setImmediate(r));
  assert.equal(c.plots.length,1);assert.equal(c.plots[0][1],'raw');
  c.context.attachComparisonProfile({...c.options,kind:'fourier'});assert.equal(c.calls.length,2);
  c.resolve({start:{x:2,y:2},end:{x:2,y:8},distance:[0,6]});await new Promise(r=>setImmediate(r));
  assert.equal(c.plots[1][1],'fourier');
});
