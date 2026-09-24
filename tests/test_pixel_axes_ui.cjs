const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const window={};
vm.runInNewContext(fs.readFileSync('ui/static_processing/pixel_axes.js','utf8'),{window});
const axes=window.QCLPixelAxes;
test('ticks mark pixel centers, with descending coordinates when flipped',()=>{
  const forward=axes.ticks(100,600),reverse=axes.ticks(100,600,true);
  assert.equal(forward[0].value,0);assert.equal(forward[0].position,3);
  assert.equal(forward.at(-1).value,99);assert.equal(forward.at(-1).position,597);
  forward.forEach((tick,i)=>{assert.equal(reverse[i].value,tick.value);assert.ok(Math.abs(reverse[i].position+tick.position-600)<1e-10);});
});
test('one-pixel and narrow images do not duplicate ticks',()=>{
  assert.equal(axes.ticks(1,400).length,1);assert.equal(axes.ticks(1,400)[0].position,200);
  assert.equal(axes.ticks(2,100).length,2);assert.equal(axes.ticks(1000,180).length,3);
});
