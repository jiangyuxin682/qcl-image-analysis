const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('ui/static_processing/compare.js','utf8');
class Node {
  constructor(tag,text=''){this.tag=tag;this.textContent=text;this.children=[];this.style={};this.classList={add(){},remove(){}};}
  get value(){return this._value??(this.tag==='select'?this.children[0]?.value:'')??'';}
  set value(value){this._value=String(value);}
  get selectedOptions(){return this.children.filter(n=>n.value===this.value);}
  append(...nodes){for(const node of nodes){if(node.parent)node.parent.children=node.parent.children.filter(n=>n!==node);node.parent=this;this.children.push(node);}}
  replaceChildren(...nodes){this.children=[];this._value=undefined;this.append(...nodes);}
  setAttribute(){}
  async decode(){}
}
function setup(){
  const nodes=new Map(),requests=[],profiles=[],downloads=[];
  const el=(tag,text)=>new Node(tag,text),$=s=>{if(!nodes.has(s))nodes.set(s,el('div'));return nodes.get(s);};
  const select=(id,value)=>{const node=el('select'),option=el('option',value);option.value=value;node.append(option);nodes.set(id,node);};
  select('#compare-stage','absorbance');select('#compare-band-mode','per-folder');select('#compare-cmap','inferno');
  nodes.set('#compare-band',el('select'));$('#compare-shared-scale').checked=true;
  const records=[{id:'a',name:'Folder A',patterns:['pattern0'],bands:[1658],mapping:{1658:[]},baseline_enabled:{1658:false}},
    {id:'b',name:'Folder B',patterns:['pattern0'],bands:[1775],mapping:{1775:[]},baseline_enabled:{1775:false}}].map((d,i)=>({...d,has_gold:false,r0_selection:{method:'roi'},cnr_rois:{},cnr:[{pattern:'pattern0',wavenumber:d.bands[0],stage:'absorbance',cnr:11+i,cnr_unadjusted:11+i,contrast_low_percentile:0,contrast_high_percentile:100}]}));
  const c={$,el,document:{createTextNode:text=>el('text',text),createElementNS:(_,tag)=>el(tag),body:el('body')},
    datasets:records.map(d=>({...d,maxStep:8,cnrDirty:false})),info:[],selections:new Map(),revision:0,automaticColorLimits:true,URLSearchParams,
    sharing:{spectral:false,processing:false,normalization:false,analyte:false},QCLPixelAxes:{attach(){}},
    QCLImages:{setColorbar(){},download:async(...args)=>downloads.push(args)},
    attachComparisonProfile:args=>{profiles.push(args);return {status:{textContent:'profile'},ensureReady:async()=>{}};},
    api:async url=>{if(url.startsWith('/api/comparison-info'))return records;
      const q=new URLSearchParams(url.split('?')[1]);requests.push(q);
      if(q.get('stats_only'))return {available:true,data_min:q.get('dataset')==='a'?-.2:-.1,data_max:q.get('dataset')==='a'?.4:.8};
      return {available:true,width:10,height:10,png:'',vmin:-.2,vmax:.8};}};
  vm.createContext(c);vm.runInContext(source.slice(source.indexOf('function fill('),source.indexOf("$('#compare-stage').onchange=")),c);
  return {c,requests,profiles,downloads,$};
}
test('rendered cards, metrics, profiles, shared scale and PNG all follow each folder’s selected band',async()=>{
  const {c,requests,profiles,downloads,$}=setup();await c.loadComparison();
  assert.match($('#compare-status').textContent,/shared colorbar/);
  const cards=$('#comparison-grid').children;assert.equal(cards.length,2);
  const images=requests.filter(q=>!q.has('stats_only'));
  assert.deepEqual(images.map(q=>q.get('wavenumber')),['1658','1775']);
  assert.ok(images.every(q=>q.get('display_min')==='-0.2'&&q.get('display_max')==='0.8'));
  assert.deepEqual(profiles.map(p=>p.wn),[1658,1775]);
  for(const [i,card] of cards.entries()){
    assert.match(card.children.find(n=>n.className==='cnr-parameters').innerHTML,new RegExp(`CNR: ${11+i}`));
    await card.children.find(n=>n.tag==='button'&&n.textContent.startsWith('Download')).onclick();
  }
  assert.match(downloads[0][2],/Folder A.*1658/);assert.match(downloads[1][2],/Folder B.*1775/);
  assert.ok(downloads.every(d=>d[5].information.includes('Baseline correction: skipped')));
});

test('blocked comparison identifies shared section, dataset values and section navigation',async()=>{
  const {c,requests,$}=setup();
  const records=await c.api('/api/comparison-info');
  records[0].r0_selection={method:'roi'};records[1].r0_selection={method:'darkest',count:20};
  c.sharing.analyte=true;c.desiredStep=1;c.select=id=>c.opened=id;
  await c.loadComparison();
  assert.match($('#compare-status').textContent,/Section 6/);assert.equal(requests.length,0);
  const root=$('#compare-diagnostics');assert.equal(root.hidden,false);
  const walk=node=>[node,...node.children.flatMap(walk)],nodes=walk(root),text=nodes.map(n=>n.textContent).join(' ');
  for(const value of ['Sharing ON','Folder A','Folder B','roi','darkest','20'])assert.ok(text.includes(value),value);
  const buttons=nodes.filter(n=>n.tag==='button');buttons[1].onclick();
  assert.equal(c.opened,'b');assert.equal(c.desiredStep,6);
  c.sharing.analyte=false;await c.loadComparison();
  assert.equal(root.hidden,true);assert.equal(root.children.length,0);
  assert.equal($('#comparison-grid').children.length,2);
});

test('diagnostics show incomplete CNR alongside conflicts and ignore disabled groups',async()=>{
  const {c,$}=setup(),records=await c.api('/api/comparison-info');
  records[1].has_gold=true;records[1].n_pixels=10;records[1].qc_settings={};
  c.sharing.normalization=true;c.datasets[0].cnrDirty=true;
  await c.loadComparison();
  assert.match($('#compare-status').textContent,/Section 3/);
  assert.match($('#compare-status').textContent,/CNR/);
  const conflicts=c.sharingConflicts(records);assert.equal(conflicts.length,1);assert.equal(conflicts[0].section,3);
  assert.ok(conflicts[0].differences.includes('normalization.has_gold'));
  c.sharing.normalization=false;assert.equal(c.sharingConflicts(records).length,0);
});
