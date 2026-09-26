const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function setup(mode='reproduce',source='folder'){
  const selectors=new Map(),requests=[];
  const modeNode={value:mode},sourceNode={value:source,options:[{}]},folderButton={},pathNode={},filesNode={files:['raw.csv']},hint={};
  selectors.set('.project-mode',modeNode);selectors.set('.project-source',sourceNode);selectors.set('.project-folder',{});selectors.set('.project-files',{});selectors.set('.project-import-hint',hint);selectors.set('.project-folder button',folderButton);selectors.set('.project-path',pathNode);selectors.set('.project-files input',filesNode);
  const root={querySelector:s=>selectors.get(s),querySelectorAll:()=>[modeNode,sourceNode,folderButton,filesNode]};
  const c={URL,location:{href:'http://localhost:8765/'},QCLUpload:{chooseFolder:async()=>'/raw/folder',stream:()=> 'raw-stream'},fetch:async(url,options)=>{requests.push({url,options});return {ok:true,json:async()=>url.startsWith('/api/datasets/reproduce')?{datasets:[{id:'result'}]}:{id:'staging'}};}};
  vm.createContext(c);vm.runInContext(fs.readFileSync('ui/static_processing/project_options.js','utf8'),c);
  const importer=c.QCLProject.importControls(root);
  return {c,importer,requests,folderButton,sourceNode,modeNode,hint};
}
test('external folder reproduction uses a temporary raw dataset and cleans it up',async()=>{
  const {importer,requests,folderButton}=setup();await folderButton.onclick();
  const result=await importer.send('zip-file','/api/datasets/reproduce',{name:'Project'});
  assert.equal(result.datasets[0].id,'result');assert.equal(requests.length,3);
  assert.equal(JSON.parse(requests[0].options.body).path,'/raw/folder');
  const query=new URL(requests[1].url,'http://localhost').searchParams;
  assert.equal(query.get('raw_dataset'),'staging');assert.equal(query.get('mode'),'reproduce');
  assert.equal(requests[2].url,'/api/datasets/remove');
});
test('apply mode requires external inputs; CSV staging is cleaned on project errors',async()=>{
  const {c,importer,requests,sourceNode}=setup('apply','embedded');
  assert.equal(sourceNode.value,'folder');assert.equal(sourceNode.options[0].disabled,true);
  sourceNode.value='files';const normal=c.fetch;
  c.fetch=async(url,options)=>url.startsWith('/api/datasets/reproduce')?{ok:false,json:async()=>({error:'bad project'})}:normal(url,options);
  await assert.rejects(importer.send('zip','/api/datasets/reproduce'),/bad project/);
  assert.equal(requests[0].url,'/api/datasets/upload-csv');assert.equal(requests.at(-1).url,'/api/datasets/remove');
  assert.equal(sourceNode.disabled,false);assert.equal(sourceNode.options[0].disabled,true);
});

test('export presets default to lightweight and custom selections select only requested stages',()=>{
  const c={document:{createElement:tag=>({tag,dataset:{},checked:false,children:[],append(...items){this.children.push(...items);}}),createTextNode:text=>({text})}};
  vm.createContext(c);vm.runInContext(fs.readFileSync('ui/static_processing/project_options.js','utf8'),c);
  const preset={value:'light'},hint={},stages={children:[],append(node){this.children.push(node);}},flags={raw_inputs:{checked:false,dataset:{export:'raw_inputs'}},auxiliary:{checked:false,dataset:{export:'auxiliary'}},tables:{checked:true,dataset:{export:'tables'}}};
  const inputs=()=>stages.children.map(n=>n.children[0]);
  const root={querySelector:s=>s==='.project-preset'?preset:s==='.project-stages'?stages:s==='.project-export-hint'?hint:flags[/data-export="([^"]+)"/.exec(s)[1]],querySelectorAll:s=>s==='[data-stage]:checked'?inputs().filter(n=>n.checked):[...Object.values(flags),...inputs()]};
  let updates=0;const controller=c.QCLProject.exportControls(root,()=>updates++);
  assert.equal(controller.options().raw_inputs,false);assert.equal(controller.options().tables,true);assert.equal(controller.options().stages.length,0);
  preset.value='full';preset.onchange({target:preset});assert.equal(controller.options().stages.length,6);assert.equal(controller.options().raw_inputs,true);
  preset.value='light';preset.onchange({target:preset});inputs().find(n=>n.dataset.stage==='baseline').checked=true;inputs()[0].onchange();
  assert.equal(preset.value,'custom');assert.deepEqual([...controller.options().stages],['baseline']);assert.equal(controller.options().raw_inputs,false);assert.equal(updates,3);
  assert.match(hint.textContent,/NOT included/);
});
