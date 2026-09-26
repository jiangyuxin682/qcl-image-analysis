'use strict';
const $=s=>document.querySelector(s),$$=s=>[...document.querySelectorAll(s)],datasets=[];
let active=null,desiredStep=1,shared=null,info=[],revision=0,importing=false,managing=false;
const selections=new Map();
let automaticColorLimits=true;
const el=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;};
async function api(url,payload){const r=await fetch(url,payload?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}:{});const d=await r.json();if(!r.ok)throw Error(d.error||'Request failed');return d;}
function tell(d,message){d.frame.contentWindow.postMessage(message,location.origin);}
let comparisonTab=null;
function tabs(){
  const root=$('#dataset-tabs'),disabled=managing||importing||datasets.some(x=>x.busy);
  if(!comparisonTab){comparisonTab=el('button','Final comparison');comparisonTab.onclick=()=>select('comparison');root.append(comparisonTab);}
  for(const d of datasets){
    if(!d.tab){
      const group=el('div');group.className='dataset-tab';
      const button=el('button'),remove=el('button','×');
      button.onclick=()=>select(d.id);button.title='Double-click to rename';button.ondblclick=()=>renameDataset(d);
      remove.className='secondary tab-action';remove.onclick=()=>removeDataset(d);
      group.append(button,remove);root.insertBefore(group,comparisonTab);d.tab={group,button,remove};
    }
    const {button,remove}=d.tab;
    const title=`${d.name} · ${d.step||1}/10`;if(button.textContent!==title)button.textContent=title;
    button.className=d.id===active?'secondary active':'secondary';button.disabled=remove.disabled=disabled;
    remove.title=`Remove ${d.name}`;remove.setAttribute('aria-label',remove.title);
  }
  comparisonTab.className=active==='comparison'?'secondary active':'secondary';comparisonTab.disabled=disabled||datasets.length<2;
  $('#add-folder').disabled=disabled;
  $$('#import-folders input, #import-folders select').forEach(n=>n.disabled=disabled);
}
async function renameDataset(d){
  if(managing||importing||datasets.some(x=>x.busy))return;
  const name=window.prompt('Dataset name',d.name);if(name===null||name.trim()===d.name)return;
  if(!name.trim()||name.trim().length>160){$('#multi-status').textContent='Enter a dataset name between 1 and 160 characters.';return;}
  managing=true;revision++;tabs();
  try{
    const result=await api('/api/datasets/rename',{id:d.id,name:name.trim()});
    d.name=result.name;d.frame.title=result.name;$('#comparison-grid').replaceChildren();
    $('#multi-status').textContent=`Renamed dataset to ${d.name}.`;
  }catch(e){$('#multi-status').textContent=e.message;}
  finally{managing=false;tabs();if(active==='comparison')await loadComparison();}
}
function forgetDataset(d){
  const index=datasets.indexOf(d);if(index<0)return;
  datasets.splice(index,1);d.tab?.group.remove();d.frame.remove();selections.delete(d.id);info=info.filter(x=>x.id!==d.id);
  for(const group of Object.keys(sharing))if(firstCommitted[group]===d.id){
    delete firstCommitted[group];const next=datasets.find(x=>x.committed?.[group]);if(next)firstCommitted[group]=next.id;
  }
  shared=null;
  for(const group of Object.keys(sharing))if(sharing[group]){
    const source=datasets.find(x=>x.id===firstCommitted[group]),settings=source?.committed?.[group]||datasets.find(x=>x.settings)?.settings;
    if(settings)shared=mergeSettings(shared,groupSettings(settings,group));
  }
  revision++;automaticColorLimits=true;$('#comparison-grid').replaceChildren();$('#compare-export').disabled=true;
  broadcastPolicy();
  if(!datasets.length){active=null;desiredStep=1;$('#comparison').hidden=true;$('#import-folders').open=true;}
  else if(active===d.id||(active==='comparison'&&datasets.length<2))select(datasets[Math.min(index,datasets.length-1)].id);
}
async function removeDataset(d){
  if(managing||importing||datasets.some(x=>x.busy))return;
  if(!window.confirm(`Remove “${d.name}” from this comparison? Its in-session processing will be discarded. Original files and saved ZIPs are kept.`))return;
  managing=true;revision++;tabs();
  try{await api('/api/datasets/remove',{id:d.id});forgetDataset(d);$('#multi-status').textContent=`Removed ${d.name} from the comparison. Original files are unchanged.`;}
  catch(e){$('#multi-status').textContent=e.message;}
  finally{managing=false;tabs();if(active==='comparison')await loadComparison();}
}
function select(id){active=id;revision++;datasets.forEach(d=>d.frame.hidden=d.id!==id);$('#comparison').hidden=id!=='comparison';tabs();if(id==='comparison')loadComparison();else tell(datasets.find(d=>d.id===id),{type:'section',step:desiredStep});}
function addDatasetTab(d){
  const frame=el('iframe');frame.title=d.name;frame.hidden=true;
  datasets.push({...d,frame,maxStep:1,step:1,busy:false,cnrDirty:true});
  frame.src='/?'+new URLSearchParams({dataset:d.id,embedded:'1',load:'1'});$('#dataset-frames').append(frame);
  select(d.id);
}
const projectImport=QCLProject.importControls($('#comparison-project-import'));
const projectExport=QCLProject.exportControls($('#comparison-project-export'));
$('#folder-input-kind').onchange=()=>{
  const kind=$('#folder-input-kind').value;
  $('#folder-picker-label').hidden=kind!=='folder';$('#folder-files-label').hidden=kind!=='files';$('#folder-zip-label').hidden=kind!=='zip';$('#comparison-project-import').hidden=kind!=='zip';
};
let localComparisonFolder='';
$('#folder-picker').onclick=async()=>{
  $('#folder-picker').disabled=true;
  try{const path=await QCLUpload.chooseFolder();if(path){localComparisonFolder=path;$('#folder-picker-path').textContent=path;$('#folder-picker-path').title=path;}}
  catch(e){$('#multi-status').textContent=e.message;}
  finally{$('#folder-picker').disabled=false;}
};
$('#add-folder').onclick=async()=>{
  importing=true;tabs();
  try{
    const kind=$('#folder-input-kind').value,name=$('#folder-name').value;
    if(kind==='zip'){
      const files=[...$('#folder-zip').files];if(!files.length)throw Error('Choose a processing ZIP first.');
      for(const file of files){
        if(file.size>1024**3)throw Error('Project ZIP exceeds the 1 GiB upload limit.');
        $('#multi-status').textContent=`Importing ${file.name}… Reading project settings and selected raw data.`;
        const result=await projectImport.send(file,'/api/datasets/reproduce',{name:name||file.name.replace(/\.zip$/i,'')});
        result.datasets.forEach(addDatasetTab);
      }
    }else{
      $('#multi-status').textContent='Importing selected spectral files…';
      if(kind==='folder'&&!localComparisonFolder)throw Error('Choose a local data folder first.');
      const response=kind==='folder'
        ?await fetch('/api/datasets',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:localComparisonFolder,name})})
        :await fetch('/api/datasets/upload-csv',{method:'POST',body:QCLUpload.stream($('#folder-files').files,name)});
      const result=await response.json();if(!response.ok)throw Error(result.error||'Data import failed.');addDatasetTab(result);
    }
    $('#folder-name').value='';$('#import-folders').open=false;
    $('#multi-status').textContent='Datasets imported. ZIP tabs retain saved settings; if shared groups differ, turn off their sharing switches or explicitly reconfigure before Final comparison.';
  }catch(e){$('#multi-status').textContent=e.message;}finally{importing=false;tabs();}
};
const sharing={spectral:false,normalization:true,processing:false,analyte:true};
const groupFields={spectral:[],normalization:['has-gold','reference-pixels','qc-z','qc-deviation'],processing:['fourier-enabled','filter-mode','notches','notch-sigma-x','notch-sigma-y','notch-strength','protect-radius','fourier-pad','cutoff-x','cutoff-y','rolling-enabled','rb-radius','rb-height','rb-polarity','rb-sigma','rb-pad'],analyte:['r0-method','r0-count']};
const firstCommitted={};
function groupSettings(settings,group){
  return group==='spectral'?{mapping:settings.mapping,...(settings.baseline_enabled?{baseline_enabled:settings.baseline_enabled}:{}),fields:{}}:{fields:Object.fromEntries(groupFields[group].filter(id=>id in settings.fields).map(id=>[id,settings.fields[id]]))};
}
function mergeSettings(base,patch){return {...base,...patch,fields:{...base?.fields,...patch.fields}};}
function enabledSettings(settings){let result={fields:{}};for(const group of Object.keys(sharing))if(sharing[group])result=mergeSettings(result,groupSettings(settings,group));return result;}
function broadcastPolicy(){datasets.forEach(d=>tell(d,{type:'sharing-policy',sharing,multiple:datasets.length>1}));}
window.addEventListener('message',e=>{
  if(e.origin!==location.origin)return;const d=datasets.find(d=>d.frame.contentWindow===e.source&&d.id===e.data.dataset);if(!d)return;
  if(e.data.type==='ready'){
    broadcastPolicy();
    if(e.data.reproduced){
      d.settings=e.data.settings;d.committed={};
      for(const group of Object.keys(sharing)){
        d.committed[group]=groupSettings(d.settings,group);
        if(!firstCommitted[group]){
          firstCommitted[group]=d.id;
          if(sharing[group]){
            shared=mergeSettings(shared,d.committed[group]);
            datasets.filter(x=>x!==d&&!x.reproduced&&!x.committed?.[group]).forEach(x=>tell(x,{type:'shared',settings:d.committed[group]}));
          }
        }
      }
      if(!shared)shared=enabledSettings(d.settings);
      // Imported calculations remain valid; never silently replace their recipe.
    }else{
      if(shared)tell(d,{type:'shared',settings:enabledSettings(shared)});
      tell(d,{type:'request-shared'});
    }
    if(d.id===active)tell(d,{type:'section',step:desiredStep});
  }
  if(e.data.type==='shared'){
    d.settings=e.data.settings;
    shared=mergeSettings(shared,enabledSettings(d.settings));
    datasets.filter(x=>x!==d).forEach(x=>tell(x,{type:'shared',settings:enabledSettings(shared)}));
    revision++;$('#comparison-grid').replaceChildren();
  }
  if(e.data.type==='shared-commit'){
    d.settings=e.data.settings;d.committed??={};d.committed[e.data.group]=groupSettings(d.settings,e.data.group);
    firstCommitted[e.data.group]??=d.id;
  }
  if(e.data.type==='sharing-toggle'&&e.data.group in sharing){
    const group=e.data.group;sharing[group]=!!e.data.enabled;
    if(sharing[group]){
      const source=datasets.find(x=>x.id===firstCommitted[group]);
      const settings=source?.committed?.[group]||groupSettings(datasets.find(x=>x.settings)?.settings||{mapping:{},fields:{}},group);
      shared=mergeSettings(shared,settings);
      datasets.forEach(x=>tell(x,{type:'shared',settings}));
    }
    broadcastPolicy();revision++;$('#comparison-grid').replaceChildren();
  }
  if(e.data.type==='busy')d.busy=e.data.busy;
  if(e.data.type==='progress'){d.maxStep=e.data.maxStep;d.step=e.data.step;d.cnrDirty=e.data.cnrDirty;if(d.id===active)desiredStep=d.step;}
  tabs();
});
function fill(node,values,value){node.replaceChildren();values.forEach(v=>{const o=el('option',String(v));o.value=v;node.append(o);});if(values.map(String).includes(String(value)))node.value=value;}
function availableBands(d,kind){return kind==='baseline'?Object.keys(d.mapping).filter(c=>d.baseline_enabled?.[c]!==false).map(Number):d.bands;}
function commonBands(){const stage=$('#compare-stage').value;return info.reduce((a,d)=>{const bands=availableBands(d,stage);return a===null?bands:a.filter(v=>bands.includes(v));},null)||[];}
function comparisonBands(kind,perFolder,sharedBand){
  return new Map(info.map(d=>{
    const choice=selections.get(d.id)||{pattern:d.patterns[0]};selections.set(d.id,choice);
    const bands=availableBands(d,kind);
    if(perFolder&&choice.wavenumber===undefined)choice.wavenumber=bands.includes(sharedBand)?sharedBand:(bands[0]??null);
    const wn=perFolder?choice.wavenumber:sharedBand;
    return [d.id,bands.includes(wn)?wn:null];
  }));
}
function stable(value){if(Array.isArray(value))return value.map(stable);if(value&&typeof value==='object')return Object.fromEntries(Object.keys(value).sort().map(k=>[k,stable(value[k])]));return value;}
function signature(d){return JSON.stringify(stable({mapping:sharing.spectral?d.mapping:null,baseline_enabled:sharing.spectral?Object.fromEntries(Object.keys(d.mapping).map(c=>[c,d.baseline_enabled?.[c]!==false])):null,parameters:sharing.processing?d.parameters:null,normalization:sharing.normalization?{has_gold:d.has_gold,...(d.has_gold?{n_pixels:d.n_pixels,qc:d.qc_settings}:{})}:null,r0:sharing.analyte?{method:d.r0_selection.method,count:d.r0_selection.count}:null}));}
function sharingConflicts(records){
  const groups=[['spectral',2,'Center and reference wavenumbers',['mapping','baseline_enabled']],['normalization',3,'Normalization parameters',['normalization']],['processing',5,'Fourier and rolling-ball parameters',['parameters']],['analyte',6,'Analyte-free selection',['r0']]];
  // Read the same normalized values as the comparison gate, so diagnostics cannot disagree with it.
  const values=records.map(d=>JSON.parse(signature(d)));
  function flatten(value,path,result){
    if(value&&typeof value==='object'&&!Array.isArray(value)){
      const entries=Object.entries(value);if(!entries.length)result[path]='{}';
      for(const [key,v] of entries)flatten(v,path?path+'.'+key:key,result);
    }else result[path]=JSON.stringify(value);
  }
  return groups.filter(([group])=>sharing[group]).map(([group,section,title,keys])=>{
    const folders=records.map((d,i)=>{const fields={};for(const key of keys)flatten(values[i][key],key,fields);return {id:d.id,name:d.name,fields};});
    const paths=[...new Set(folders.flatMap(d=>Object.keys(d.fields)))].sort();
    const differences=paths.filter(path=>new Set(folders.map(d=>d.fields[path]??'Not applicable')).size>1);
    return {group,section,title,folders,differences};
  }).filter(group=>group.differences.length);
}
function renderComparisonIssues(conflicts,incomplete){
  const root=$('#compare-diagnostics');root.replaceChildren();root.hidden=!conflicts.length&&!incomplete.length;
  if(root.hidden)return;
  root.append(el('h3','Why comparison is blocked'));
  root.append(el('p','Sharing switches apply to all folder tabs. An enabled switch blocks comparison only when the saved parameter values differ. Open a section below to turn off sharing, or unify its settings and recalculate.'));
  if(incomplete.length)root.append(el('p','Processing or CNR needs completion/recalculation: '+incomplete.map(d=>d.name).join(', ')));
  const labels={'mapping':'Center → reference wavenumbers','baseline_enabled':'Apply baseline correction','normalization.has_gold':'Gold reference available','normalization.n_pixels':'Gold reference pixel count','normalization.qc.robust_z_threshold':'QC robust-z threshold','normalization.qc.min_relative_deviation':'QC relative deviation','r0.method':'Analyte-free selection method','r0.count':'Analyte-free pixel count'};
  for(const conflict of conflicts){
    root.append(el('h4',`Section ${conflict.section} · ${conflict.title} · Sharing ON for all folders`));
    const wrap=el('div');wrap.className='table-wrap';const table=el('table'),head=el('tr');head.append(el('th','Differing parameter'));
    for(const folder of conflict.folders){
      const cell=el('th'),button=el('button',`Open Section ${conflict.section}`);button.className='secondary';
      button.disabled=(datasets.find(d=>d.id===folder.id)?.maxStep||1)<conflict.section;
      button.onclick=()=>{desiredStep=conflict.section;select(folder.id);};
      cell.append(el('div',folder.name),el('small','Sharing ON'),button);head.append(cell);
    }
    const thead=el('thead');thead.append(head);table.append(thead);const body=el('tbody');
    for(const path of conflict.differences){
      const row=el('tr'),label=labels[path]||path.replace(/^parameters\./,'').replace(/_/g,' ');row.append(el('th',label));
      for(const folder of conflict.folders)row.append(el('td',folder.fields[path]??'Not applicable'));body.append(row);
    }
    table.append(body);wrap.append(table);root.append(wrap);
  }
}
function comparisonColorRange(records){
  const finite=records.filter(r=>r.available&&Number.isFinite(r.data_min)&&Number.isFinite(r.data_max));
  if(!finite.length)throw Error('No finite values in the selected images.');
  const min=Math.min(...finite.map(r=>r.data_min)),max=Math.max(...finite.map(r=>r.data_max));
  return {min,max:max>min?max:min+Math.max(1e-12,Math.abs(min)*1e-12)};
}
async function sharedColorRange(kind,wn,current,bandsByDataset=null){
  const enabled=$('#compare-shared-scale').checked;
  for(const id of ['compare-color-min','compare-color-max','compare-color-auto'])$('#'+id).disabled=!enabled;
  if(!enabled)return null;
  if(automaticColorLimits){
    const records=await Promise.all(info.map(d=>{
      const selected=selections.get(d.id)?.pattern,pattern=d.patterns.includes(selected)?selected:d.patterns[0];
      return api('/api/image?'+new URLSearchParams({dataset:d.id,pattern,wavenumber:bandsByDataset?bandsByDataset.get(d.id):wn,kind,stats_only:true}));
    }));
    if(current!==revision)return null;
    const range=comparisonColorRange(records);
    $('#compare-color-min').value=String(range.min);$('#compare-color-max').value=String(range.max);
  }
  const minText=$('#compare-color-min').value,maxText=$('#compare-color-max').value;
  const min=Number(minText),max=Number(maxText);
  if(!minText.trim()||!maxText.trim()||!Number.isFinite(min)||!Number.isFinite(max)||min>=max)throw Error('Enter finite colorbar limits with minimum < maximum.');
  return {display_min:min,display_max:max};
}
async function loadComparison(){
  const current=++revision;$('#comparison-grid').replaceChildren();$('#compare-export').disabled=true;$('#compare-diagnostics').replaceChildren();$('#compare-diagnostics').hidden=true;
  try{
    info=await api('/api/comparison-info?'+new URLSearchParams({ids:datasets.map(d=>d.id).join(',')}));if(current!==revision)return;
    const incomplete=datasets.filter(d=>d.maxStep<8||d.cnrDirty||!info.find(i=>i.id===d.id)?.cnr.length);
    const conflicts=sharingConflicts(info);renderComparisonIssues(conflicts,incomplete);
    if(incomplete.length||conflicts.length){$('#compare-status').textContent='Comparison blocked. '+(conflicts.length?'Shared settings differ in '+conflicts.map(c=>'Section '+c.section).join(', ')+'. ':'')+(incomplete.length?'Processing or CNR also needs attention. ':'')+'See the dataset and section details below.';return;}

    const reflectanceOption=$('#compare-stage option[value="reflectance"]');reflectanceOption.disabled=reflectanceOption.hidden=info.some(d=>!d.has_gold);
    if(reflectanceOption.disabled&&$('#compare-stage').value==='reflectance')$('#compare-stage').value='raw';
    const perFolder=$('#compare-band-mode').value==='per-folder';$('#compare-band-label').hidden=perFolder;
    const previousBand=+$('#compare-band').value;fill($('#compare-band'),commonBands(),$('#compare-band').value);if(!perFolder&&!$('#compare-band').value){$('#compare-status').textContent='No common wavenumber for this stage.';return;}
    $('#compare-export').disabled=false;$('#compare-status').textContent='Each image has its own color scale. CNR uses each folder’s independently selected target and background ROIs.';
    const kind=$('#compare-stage').value,sharedBand=perFolder?previousBand:+$('#compare-band').value;
    const bandsByDataset=comparisonBands(kind,perFolder,sharedBand),missing=[...bandsByDataset.values()].some(wn=>wn===null);
    const colorRange=missing?null:await sharedColorRange(kind,sharedBand,current,bandsByDataset);if(current!==revision)return;
    if(colorRange)$('#compare-status').textContent=`Same-stage shared colorbar: ${colorRange.display_min} to ${colorRange.display_max}. CNR retains each image’s independent calculation.`;
    if(missing)$('#compare-status').textContent='Select an available wavenumber in each folder for this stage. Skipped centers have no after-baseline result.';
    for(const d of info){
      const wn=bandsByDataset.get(d.id);
      const card=el('div');card.className='card';card.append(el('h3',d.name));card.append(el('p',d.has_gold?'Processing basis: gold-normalized reflectance':'Processing basis: raw intensity · reflectance skipped'));const options=el('div');options.className='dataset-options';
      const choice=selections.get(d.id)||{pattern:d.patterns[0]};choice.low=d.cnr[0]?.contrast_low_percentile??0;choice.high=d.cnr[0]?.contrast_high_percentile??100;selections.set(d.id,choice);
      const label=el('label','Pattern'),select=el('select');fill(select,d.patterns,choice.pattern);choice.pattern=select.value;label.append(select);options.append(label);
      if(perFolder){
        const bandLabel=el('label','Wavenumber · cm⁻¹'),bandSelect=el('select');
        if(wn===null){const placeholder=el('option','Select a wavenumber');placeholder.value='';bandSelect.append(placeholder);}
        for(const band of availableBands(d,kind)){const option=el('option',`${band} · ${Object.hasOwn(d.mapping,String(band))?'center':'reference'}`);option.value=band;bandSelect.append(option);}
        bandSelect.value=wn===null?'':String(wn);bandLabel.append(bandSelect);options.append(bandLabel);
        bandSelect.onchange=()=>{choice.wavenumber=bandSelect.value===''?null:Number(bandSelect.value);loadComparison();};
      }
      select.onchange=()=>{choice.pattern=select.value;loadComparison();};card.append(options);$('#comparison-grid').append(card);
      if(wn===null){card.append(el('p','No image selected for this stage. Choose a wavenumber or change the image stage.'));continue;}
      const baselineNote=d.baseline_enabled?.[wn]===false?'Baseline correction: skipped':Object.hasOwn(d.mapping,String(wn))?`Baseline references: ${d.mapping[wn].join(', ')} cm⁻¹`:'Reference band · no baseline correction';
      card.append(el('p',`${wn} cm⁻¹ · ${baselineNote}`));
      for(const key of ['low','high']){const l=el('label',`${key==='low'?'Lower':'Upper'} display / CNR percentile`),input=el('input');input.type='number';input.min=0;input.max=100;input.value=choice[key];input.disabled=!!colorRange;input.onchange=async()=>{
        const dataset=datasets.find(x=>x.id===d.id),range={low:choice.low,high:choice.high,[key]:Number(input.value)};
        dataset.busy=true;tabs();$('#compare-export').disabled=true;document.querySelectorAll('#comparison input, #comparison select, #comparison button').forEach(n=>n.disabled=true);
        try{const result=await api('/api/cnr?'+new URLSearchParams({dataset:d.id}),{...d.cnr_rois,...range});tell(dataset,{type:'cnr-contrast',...range,records:result.records});}
        catch(e){$('#compare-status').textContent=e.message;input.value=choice[key];}
        finally{dataset.busy=false;tabs();document.querySelectorAll('#comparison input, #comparison select, #comparison button').forEach(n=>n.disabled=n.hasAttribute('data-project-required'));await loadComparison();}
      };l.append(input);options.append(l);}
      choice.zero??={};const zeroLabel=el('label'),zeroInput=el('input');zeroInput.type='checkbox';zeroInput.checked=!colorRange&&!!choice.zero[kind];zeroInput.disabled=!!colorRange;zeroLabel.append(zeroInput,document.createTextNode('Set lower limit to 0 · display only'));card.append(zeroLabel);zeroInput.onchange=()=>{choice.zero[kind]=zeroInput.checked;loadComparison();};
      const stageTitle=kind==='absorbance'&&d.baseline_enabled?.[wn]===false?'Absorbance · baseline not applied':$('#compare-stage').selectedOptions[0].textContent;
      card.append(el('h4',stageTitle));const metrics=el('p');metrics.className='cnr-parameters';const row=d.cnr.find(r=>r.pattern===choice.pattern&&r.wavenumber===wn&&r.stage===kind);
      const number=(v,digits=2)=>typeof v==='number'&&Number.isFinite(v)?digits===0?v.toFixed(0):v.toExponential(2):'—';
      metrics.innerHTML=`<div>Unadjusted CNR: ${number(row?.cnr_unadjusted,0)} · CNR: ${number(row?.cnr,0)} · Percentiles: ${row?.contrast_low_percentile}–${row?.contrast_high_percentile}</div><div><i>A</i><sub>s</sub>: ${number(row?.target_mean)} · <i>A</i><sub>bg</sub>: ${number(row?.background_mean)} · σ<sub>bg</sub>: ${number(row?.background_std)} · |<i>A</i><sub>s</sub> − <i>A</i><sub>bg</sub>|: ${number(row?.signed_contrast==null?null:Math.abs(row.signed_contrast))}</div>`;card.append(metrics);$('#comparison-grid').append(card);
      const data=await api('/api/image?'+new URLSearchParams({dataset:d.id,pattern:choice.pattern,wavenumber:wn,kind,cmap:$('#compare-cmap').value,cnr_background_source:d.cnr_rois?.background_source||'manual',low:choice.low,high:choice.high,colorbar_zero:!colorRange&&!!choice.zero[kind],...(colorRange||{})}));if(current!==revision)return;
      if(!data.available){card.append(el('p','Stage unavailable'));continue;}
      const wrap=el('div');wrap.className='heatmap';const img=el('img');img.alt=`${d.name} ${choice.pattern} ${wn} ${kind}`;img.src='data:image/png;base64,'+data.png;const bar=el('div');bar.className='bar';const strip=el('div');strip.className='strip';QCLImages.setColorbar(strip,$('#compare-cmap').value);const ticks=el('div');ticks.className='ticks';[data.vmax,(data.vmin+data.vmax)/2,data.vmin].forEach(v=>ticks.append(el('span',v.toFixed(3))));bar.append(strip,ticks);
      const holder=el('div');holder.style.cssText='position:relative;width:calc(100% - 60px);align-self:start';img.style.width='100%';img.style.display='block';holder.append(img);
      const ns='http://www.w3.org/2000/svg',overlay=document.createElementNS(ns,'svg');overlay.classList.add('roi-overlay');overlay.setAttribute('viewBox',`0 0 ${data.width} ${data.height}`);overlay.setAttribute('preserveAspectRatio','none');overlay.style.cssText='position:absolute;inset:0;width:100%;height:100%;pointer-events:none';
      for(const [name,color] of [['background','#00eaff'],['target','#7dff00']]){const roi=d.cnr_rois?.[name];if(!roi)continue;const box=document.createElementNS(ns,'rect');for(const [key,value] of Object.entries({x:roi.x_min,y:roi.y_min,width:roi.x_max-roi.x_min,height:roi.y_max-roi.y_min,fill:'none',stroke:color,'stroke-width':1,'stroke-opacity':1,'stroke-dasharray':'4 3','vector-effect':'non-scaling-stroke'}))box.setAttribute(key,value);overlay.append(box);}if(data.cell_free_pixels){const path=document.createElementNS(ns,'path'),arm=Math.max(1.25,data.width/320);path.setAttribute('d',data.cell_free_pixels.map(([y,x])=>`M${x+.5-arm} ${y+.5}h${2*arm}M${x+.5} ${y+.5-arm}v${2*arm}`).join(''));path.setAttribute('stroke','#00eaff');path.setAttribute('stroke-width',Math.max(.35,data.width/1200));path.setAttribute('fill','none');overlay.append(path);}holder.append(overlay);wrap.append(holder,bar);card.append(wrap);QCLPixelAxes.attach(img,{width:data.width,height:data.height});
      card.append(el('p',`Target pixels: ${row?.target_pixels??0} · Background pixels: ${row?.background_pixels??0} · ${row?.status||'unavailable'}`));
      const profile=attachComparisonProfile({card,img,overlay,data,dataset:d,choice,kind,wn,current});
      const download=el('button','Download current image · PNG');download.className='secondary';card.append(download);
      download.onclick=async()=>{
        download.disabled=true;card.downloadInProgress=true;document.body.classList.add('busy');
        try{
          await img.decode();await profile.ensureReady();
          if(current!==revision)throw Error('Comparison changed. Download the refreshed image.');
          const stage=stageTitle;
          await QCLImages.download(img,data,`${d.name} · ${choice.pattern} · ${wn} cm⁻¹ · ${stage}`,
            `${d.name}_${choice.pattern}_${wn}_${kind==='baseline'?'Abs_baseline_corrected':kind}`,card,
            {profileStatus:profile.status.textContent,information:[baselineNote,
              d.has_gold?'Processing basis: gold-normalized reflectance':'Processing basis: raw intensity',
              `Target pixels: ${row?.target_pixels??0} · Background pixels: ${row?.background_pixels??0} · Excluded background pixels: ${row?.excluded_background_pixels??0} · Status: ${row?.status||'unavailable'}`,
              `Color map: ${$('#compare-cmap').selectedOptions[0].textContent} · ${colorRange?'Same-stage shared colorbar limits':'Independent image colorbar limits'}`]});
        }catch(e){$('#compare-status').textContent=e.message;}
        finally{download.disabled=false;card.downloadInProgress=false;document.body.classList.remove('busy');}
      };
    }
  }catch(e){if(current===revision)$('#compare-status').textContent=e.message;}
}
$('#compare-stage').onchange=$('#compare-band').onchange=()=>{automaticColorLimits=true;loadComparison();};$('#compare-refresh').onclick=loadComparison;
$('#compare-band-mode').onchange=()=>{automaticColorLimits=true;loadComparison();};
$('#compare-cmap').onchange=loadComparison;
$('#compare-shared-scale').onchange=()=>{automaticColorLimits=true;loadComparison();};
for(const id of ['compare-color-min','compare-color-max'])$('#'+id).onchange=()=>{automaticColorLimits=false;loadComparison();};
$('#compare-color-auto').onclick=()=>{automaticColorLimits=true;loadComparison();};
$('#compare-export').onclick=async()=>{try{const r=await fetch('/api/comparison-export?'+new URLSearchParams({ids:datasets.map(d=>d.id).join(','),options:JSON.stringify(projectExport.options())}));if(!r.ok)throw Error((await r.json()).error);const url=URL.createObjectURL(await r.blob()),a=el('a');a.href=url;a.download=QCLUpload.zipName($('#compare-zip-name').value,'qcl-folder-comparison');a.click();setTimeout(()=>URL.revokeObjectURL(url),60000);}catch(e){$('#compare-status').textContent=e.message;}};
tabs();


function attachComparisonProfile({card,img,overlay,data,dataset,choice,kind,wn,current}){
  let ready=false;
  const line=choice.line??={direction:'horizontal',start:null,end:null,selecting:false,revision:0};
  const controls=el('div');controls.className='toolbar';
  const label=el('label','Line direction'),direction=el('select');
  for(const value of ['horizontal','vertical']){const option=el('option',value==='horizontal'?'Horizontal':'Vertical');option.value=value;direction.append(option);}direction.value=line.direction;label.append(direction);
  const select=el('button','Select line start / end'),clear=el('button','Clear line');select.className=clear.className='secondary';
  const status=el('p');status.className='hint';status.setAttribute('role','status');
  controls.append(label,select,clear);card.append(controls,status);
  img.draggable=false;img.style.cursor='crosshair';img.style.touchAction='none';
  const valid=p=>!p||(p.x>=0&&p.y>=0&&p.x<data.width&&p.y<data.height);
  if(!valid(line.start)||!valid(line.end)){line.start=line.end=null;line.selecting=false;line.revision++;}
  function draw(){QCLLine.drawLine(overlay,line.start,line.end,data.width);}
  function clearLine(){ready=false;line.revision++;line.start=line.end=null;line.selecting=false;card.querySelector('.line-profile-plot')?.remove();draw();status.textContent='Choose Horizontal or Vertical, then select two points. Positions and profiles are independent for each folder; values are unaffected by display contrast.';}
  async function refresh(){
    ready=false;const token=++line.revision;
    if(!line.start||!line.end)return;
    status.textContent='Calculating line profile…';card.querySelector('.line-profile-plot')?.remove();
    try{
      const result=await api('/api/line-profile?'+new URLSearchParams({dataset:dataset.id}),{pattern:choice.pattern,wavenumber:wn,start:line.start,end:line.end});
      if(token!==line.revision||current!==revision)return;
      QCLLine.renderPlot(card,kind,dataset.name+' '+kind,dataset.has_gold,result);ready=true;
      status.textContent=`Start (${result.start.x}, ${result.start.y}) → End (${result.end.x}, ${result.end.y}) · ${result.distance.at(-1).toFixed(2)} pixels · Actual stage values; invalid samples appear as gaps.`;
    }catch(e){if(token===line.revision&&current===revision)status.textContent=e.message;}
  }
  select.onclick=()=>{clearLine();line.selecting=true;status.textContent='Click the start point on this image.';};
  clear.onclick=clearLine;
  direction.onchange=()=>{line.direction=direction.value;clearLine();};
  img.onpointerdown=e=>{
    if(card.downloadInProgress||!line.selecting||e.button!==0||current!==revision||datasets.some(d=>d.busy))return;
    e.preventDefault();e=QCLImages.eventPoint(e,img);const rect=img.getBoundingClientRect();
    let point={x:Math.max(0,Math.min(data.width-1,Math.floor((e.clientX-rect.left)*data.width/rect.width))),y:Math.max(0,Math.min(data.height-1,Math.floor((e.clientY-rect.top)*data.height/rect.height)))};
    if(!line.start){line.start=point;status.textContent=`Start (${point.x}, ${point.y}). Click the end point; it snaps ${line.direction}ly.`;}
    else{
      point=QCLLine.snapEnd(line.start,point,line.direction);
      if(point.x===line.start.x&&point.y===line.start.y){status.textContent='Choose a different end position along the selected direction.';return;}
      line.end=point;line.selecting=false;refresh();
    }
    draw();
  };
  draw();
  if(line.end)refresh();
  else status.textContent=line.start?'Click the end point on this image.':'Choose Horizontal or Vertical, then select two points. Each folder has its own line.';
  return {status,ensureReady:async()=>{if(line.end&&!ready){await refresh();if(!ready)throw Error('Line profile is not ready. Please retry the download.');}}};
}
