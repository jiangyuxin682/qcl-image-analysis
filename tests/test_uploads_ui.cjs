const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const source=fs.readFileSync(require('node:path').join(__dirname,'../ui/static_processing/uploads.js'),'utf8');
function setup(){const context={FormData:class{constructor(){this.entries=[]}append(...args){this.entries.push(args)}}};vm.createContext(context);vm.runInContext(source,context);return context.QCLUpload;}
test('folder selection sends spectral files with their relative paths and timestamps',()=>{
  const u=setup();const form=u.data([{name:'lineScan_1658_0invcm.csv',webkitRelativePath:'run/stacks/pattern1/lineScan_1658_0invcm.csv',lastModified:123,size:10},{name:'metadata.csv',size:10}],'folder','Test');
  const metadata=JSON.parse(form.entries[0][1]);assert.equal(metadata.kind,'folder');assert.equal(metadata.name,'Test');
  assert.deepEqual(metadata.files,[{path:'run/stacks/pattern1/lineScan_1658_0invcm.csv',last_modified:123}]);
  assert.equal(form.entries.length,2);assert.equal(form.entries[1][2],'image_0.csv');
});
test('CSV chooser uses basenames and rejects empty or oversized selections',()=>{
  const u=setup(),file={name:'lineScan_1601_0invcm.csv',size:5,lastModified:456};
  assert.equal(JSON.parse(u.data([file],'files').entries[0][1]).files[0].path,file.name);
  assert.throws(()=>u.data([],'files'),/Choose/);
  assert.throws(()=>u.data([{...file,size:1024**3+1}],'files'),/limit/);
});
