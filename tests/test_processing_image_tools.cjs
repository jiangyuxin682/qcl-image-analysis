const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
function setup(comparison=false){
  const elements=[],draws=[],texts=[],scales=[],properties={};
  const ctx={measureText:text=>({width:text.length*8}),fillText:(...args)=>texts.push(args),drawImage:(...args)=>draws.push(args),scale:(...args)=>scales.push(args),beginPath(){},moveTo(){},lineTo(){},stroke(){},rotate(){},fillRect(){},save(){},restore(){},translate(){},createLinearGradient:()=>({addColorStop(){}})};
  const element=tag=>{const node={tag,style:{},children:[],append(...nodes){this.children.push(...nodes)},getContext:()=>ctx,toBlob:fn=>fn({}),click(){this.clicked=true;}};elements.push(node);return node;};
  const section={style:{setProperty:(name,value)=>properties[name]=value}},controls=element('div');
  const document={createElement:element,createTextNode:text=>text,head:element('head'),querySelector:selector=>selector===(comparison?'#comparison':'section[data-step="8"]')?section:selector===(comparison?'#compare-flip-controls':'#cnr-flip-controls')?controls:selector==='#profile-status'?{textContent:'Start (1, 2) → End (10, 2) · 10 samples'}:null};
  const window={};const context=vm.createContext({window,document,Image:class{async decode(){}},XMLSerializer:class{serializeToString(){return '<svg/>';}},getComputedStyle:()=>({backgroundImage:'linear-gradient(to top,rgb(0,0,0),rgb(255,255,255))'}),URL:{createObjectURL:()=>'',revokeObjectURL(){}},setTimeout:()=>{}});
  vm.runInContext(fs.readFileSync('ui/static_processing/pixel_axes.js','utf8'),context);
  vm.runInContext(fs.readFileSync('ui/static_processing/image_tools.js','utf8'),context);
  return {tools:window.QCLImages,elements,properties,draws,texts,scales};
}
test('flip controls apply only to Section 8 and preserve selection coordinates elsewhere',()=>{
  const {tools,elements,properties}=setup();
  const image={closest:()=>({}),getBoundingClientRect:()=>({left:10,right:210,top:20,bottom:120})};
  const event={clientX:35,clientY:40};
  assert.equal(tools.eventPoint(event,image).clientX,35);
  const horizontal=elements.find(e=>e.id==='flip-horizontal');horizontal.checked=true;horizontal.onchange();
  assert.equal(tools.eventPoint(event,image).clientX,185);
  assert.equal(tools.eventPoint(event,image).clientY,40);
  const vertical=elements.find(e=>e.id==='flip-vertical');vertical.checked=true;vertical.onchange();
  assert.equal(tools.eventPoint(event,image).clientY,100);
  assert.equal(properties['--image-flip-x'],'-1');
  const otherSection={...image,closest:()=>null};
  assert.equal(tools.eventPoint(event,otherSection).clientX,35);
  assert.equal(tools.eventPoint(event,otherSection).clientY,40);
  horizontal.checked=false;horizontal.onchange();
  assert.equal(tools.eventPoint(event,image).clientX,35);
  assert.deepEqual(event,{clientX:35,clientY:40});
});
for(const hasProfile of [false,true])test(`PNG includes parameters and ${hasProfile?'the line profile':'no empty profile panel'}`,async()=>{
  const {tools,elements,draws,texts,scales}=setup();
  const svg={cloneNode:()=>({style:{},setAttribute(){}})};
  const textNode=text=>({cloneNode:()=>({textContent:text,querySelectorAll:()=>[]})});
  const parameters=['CNR: 12 · Unadjusted CNR: 11','A_bg: 0.012 · sigma_bg: 0.002','Background pixels: 25 · Excluded: 0'];
  const card={querySelector:selector=>({'.cnr-parameters':{children:parameters.map(textNode)},'input[type="checkbox"]':{checked:true},'.line-profile-plot':hasProfile?svg:null,'.roi-overlay':svg,'.strip':{}}[selector])};
  tools.orientation.horizontal=true;
  await tools.download({tag:'image'},{width:100,height:80,vmin:0,vmax:1},'pattern0 · 1658 cm⁻¹ · Absorbance after baseline','result',card);
  const output=elements.find(e=>e.tag==='canvas');
  const rendered=texts.map(row=>row[0]).join('\n');
  parameters.forEach(text=>assert.ok(rendered.includes(text)));
  assert.ok(rendered.includes('Lower limit set to 0: yes'));
  assert.ok(rendered.includes('pattern0'));
  assert.ok(rendered.includes('X (pixel)'));assert.ok(rendered.includes('Y (pixel)'));
  assert.equal(draws.length,hasProfile?3:2);
  assert.equal(rendered.includes('Line profile'),hasProfile);
  assert.equal(rendered.includes('Start (1, 2)'),hasProfile);
  assert.equal(scales.length,1);assert.deepEqual(scales[0],[-1,1]);
  const last=draws.at(-1);assert.ok(last[2]+last[4]<output.height);
  assert.ok(elements.find(e=>e.tag==='a'&&e.clicked&&e.download==='result.png'));
});

test('Final comparison has independent flip controls and maps pixels back correctly',()=>{
  const {tools,elements,properties}=setup(true);
  const horizontal=elements.find(e=>e.id==='flip-horizontal');horizontal.checked=true;horizontal.onchange();
  const image={closest:selector=>selector.includes('#comparison-grid')?{}:null,getBoundingClientRect:()=>({left:10,right:110,top:20,bottom:70})};
  assert.equal(tools.eventPoint({clientX:30,clientY:40},image).clientX,90);
  assert.equal(properties['--image-flip-x'],'-1');
  assert.equal(setup().tools.orientation.horizontal,false);
});
test('comparison PNG retains dataset details and the card-specific line profile',async()=>{
  const {tools,texts,elements}=setup(true);
  const svg={cloneNode:()=>({style:{},setAttribute(){}})};
  const card={querySelector:selector=>({'.line-profile-plot':svg,'.roi-overlay':svg,'.strip':{}}[selector])};
  await tools.download({}, {width:10,height:20,vmin:-.01,vmax:.25},'Dataset B · pattern3 · Absorbance','B/result',card,
    {profileStatus:'Start (3, 4) → End (3, 19)',information:['Background pixels: 25','Color map: Black → blue · Shared colorbar limits']});
  const rendered=texts.map(row=>row[0]).join('\n');
  for(const text of ['Dataset B','Background pixels: 25','Shared colorbar limits','Start (3, 4)','X (pixel)','Y (pixel)'])assert.ok(rendered.includes(text),text);
  assert.ok(!rendered.includes('Start (1, 2)'));
  assert.equal(elements.find(e=>e.tag==='a').download,'B_result.png');
});
