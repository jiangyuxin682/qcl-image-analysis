const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
function node(tag){
  const n={tag,attributes:{},children:[],style:{},classList:{add(){}},append(child){this.children.push(child);},
    setAttribute(key,value){this.attributes[key]=String(value);},getAttribute(key){return this.attributes[key];},
    querySelector(){return null;},querySelectorAll(){return this.children.flatMap(c=>c.tag==='text'?[c]:c.querySelectorAll());},
    cloneNode(){const copy=node(this.tag);copy.attributes={...this.attributes};copy.textContent=this.textContent;copy.children=this.children.map(c=>c.cloneNode());return copy;}};
  return n;
}
function setup(orientation){
  const context={document:{createElementNS:(_ns,tag)=>node(tag)},QCLImages:{orientation}};
  vm.createContext(context);vm.runInContext(fs.readFileSync('ui/static_processing/line_profile.js','utf8'),context);return context;
}
for(const horizontal of [false,true])for(const vertical of [false,true]){
  test(`S/E glyphs remain upright and their anchors follow flip H=${horizontal} V=${vertical}`,()=>{
    const c=setup({horizontal,vertical}),overlay=node('svg');
    c.QCLLine.drawLine(overlay,{x:2,y:3},{x:18,y:3},20);
    const labels=overlay.querySelectorAll();assert.equal(labels.length,2);
    const sx=horizontal?-1:1,sy=vertical?-1:1;
    for(const [i,label] of labels.entries()){
      const x=i?18.5:2.5,y=3.5;
      assert.equal(label.getAttribute('x'),String(x));assert.equal(label.getAttribute('y'),String(y));
      assert.equal(label.getAttribute('transform'),`translate(${x} ${y}) scale(${sx} ${sy}) translate(${-x} ${-y})`);
      // Inner reflection fixes the anchor; outer image reflection moves it.
      // Their product cancels the glyph reflection along both axes.
      const inner=(p,anchor,sign)=>anchor+sign*(p-anchor);
      const outer=(p,size,sign)=>sign===-1?size-p:p;
      assert.equal(outer(inner(x,x,sx),20,sx),horizontal?20-x:x);
      assert.equal(outer(inner(x+1,x,sx),20,sx)-outer(inner(x,x,sx),20,sx),1);
      assert.equal(outer(inner(y+1,y,sy),10,sy)-outer(inner(y,y,sy),10,sy),1);
    }
    c.QCLLine.orientLabels(overlay,{horizontal:!horizontal,vertical:!vertical});
    assert.ok(labels[0].getAttribute('transform').includes(`scale(${-sx} ${-sy})`));
    assert.equal(labels[0].textContent,'S');assert.equal(labels[1].textContent,'E');
  });
}
test('PNG SVG serialization includes upright-label transforms and leaves live overlay untouched',async()=>{
  const c=setup({horizontal:false,vertical:false}),overlay=node('svg');
  c.QCLLine.drawLine(overlay,{x:2,y:3},{x:18,y:3},20);
  let serialized;
  c.window={QCLLine:c.QCLLine};c.Image=class{async decode(){}};
  c.XMLSerializer=class{serializeToString(copy){serialized=copy;return '<svg/>';}};
  const source=fs.readFileSync('ui/static_processing/image_tools.js','utf8');
  vm.runInContext(source.slice(source.indexOf('  async function svgImage('),source.indexOf('  async function download(')),c);
  await c.svgImage(overlay,20,10,{horizontal:true,vertical:true});
  assert.ok(serialized.querySelectorAll()[0].getAttribute('transform').includes('scale(-1 -1)'));
  assert.ok(overlay.querySelectorAll()[0].getAttribute('transform').includes('scale(1 1)'));
});
