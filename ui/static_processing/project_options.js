'use strict';
globalThis.QCLProject={
  exportControls(root,onchange=()=>{}){
    root.innerHTML=`<label>Export preset<select class="project-preset"><option value="light">Lightweight reproducible settings</option><option value="full">Complete reproducible project</option><option value="custom">Custom export</option></select></label>
      <label class="check"><input type="checkbox" checked disabled data-project-required>Required: processing settings, ROIs, saved pixel selections, input identities, checksums and environment information</label>
      <label class="check"><input type="checkbox" data-export="raw_inputs">Include full raw input images</label>
      <p>Optional stage images · CSV</p><div class="chips project-stages"></div>
      <label class="check"><input type="checkbox" data-export="auxiliary">Auxiliary arrays: fitted baseline, Fourier mask, background, gain and validity masks</label>
      <label class="check"><input type="checkbox" data-export="tables" checked>CNR, reference-mean and QC tables · CSV</label>
      <label>Section 1 · Full spectrum<select class="project-spectrum"><option value="parameters">Parameters and verification results · original raw data required</option><option value="raw">Include all measured raw bands</option><option value="none">Do not include full spectrum</option></select></label><p class="hint">Includes the last successfully calculated Section 1 spectrum, if available: full-image ROIs, Fourier/SG settings and results. Shared raw images are stored once. This setting is independent of processing-stage CSVs.</p><p class="hint project-export-hint"></p>`;
    const stages=[['raw','Raw intensity'],['reflectance','Reflectance'],['fourier','After Fourier'],['rolling','After flat-field'],['absorbance','Absorbance'],['baseline','After baseline']];
    for(const [key,title] of stages){const label=document.createElement('label');label.className='chip';const input=document.createElement('input');input.type='checkbox';input.dataset.stage=key;label.append(input,document.createTextNode(title));root.querySelector('.project-stages').append(label);}
    const options=()=>({spectrum:root.querySelector('.project-spectrum').value,raw_inputs:root.querySelector('[data-export="raw_inputs"]').checked,stages:[...root.querySelectorAll('[data-stage]:checked')].map(n=>n.dataset.stage),auxiliary:root.querySelector('[data-export="auxiliary"]').checked,tables:root.querySelector('[data-export="tables"]').checked});
    const update=()=>{root.querySelector('.project-export-hint').textContent=options().raw_inputs?'Raw data is included. Selected CSVs can be compared numerically during reproduction; omitted arrays are checked by fingerprint.':'Raw data is NOT included. Reproduction requires matching original raw files. Omitted result arrays are checked by fingerprint; numerical tolerance cannot be measured without those arrays.';onchange();};
    root.querySelector('.project-preset').onchange=e=>{if(e.target.value!=='custom'){const full=e.target.value==='full';root.querySelector('.project-spectrum').value=full?'raw':'parameters';root.querySelectorAll('[data-export], [data-stage]').forEach(n=>n.checked=full||n.dataset.export==='tables');}update();};
    root.querySelectorAll('[data-export], [data-stage]').forEach(n=>n.onchange=()=>{root.querySelector('.project-preset').value='custom';update();});
    root.querySelector('.project-spectrum').onchange=()=>{root.querySelector('.project-preset').value='custom';update();};
    // Initial callback is left to the caller after it receives this controller.
    root.querySelector('.project-export-hint').textContent='Raw data is NOT included. Reproduction requires matching original raw files.';
    return {options};
  },
  importControls(root,onModeChange=()=>{}){
    root.innerHTML=`<label>Import purpose<select class="project-mode"><option value="reproduce">Reproduce original processing</option><option value="apply">Apply saved settings to new raw data</option></select></label>
      <label>Raw data source<select class="project-source"><option value="embedded">Raw images inside the ZIP</option><option value="folder">Choose local raw data folder</option><option value="files">Choose raw CSV files · one pattern</option></select></label>
      <div class="project-folder" hidden><button type="button" class="secondary">Choose Folder</button><span class="project-path">No folder selected</span></div>
      <label class="project-files" hidden>Raw spectral files<input type="file" accept=".csv,text/csv" multiple></label>
      <p class="hint project-import-hint"></p>`;
    let path='';const mode=root.querySelector('.project-mode'),source=root.querySelector('.project-source');
    const update=()=>{onModeChange(mode.value);source.options[0].disabled=mode.value==='apply';if(mode.value==='apply'&&source.value==='embedded')source.value='folder';root.querySelector('.project-folder').hidden=source.value!=='folder';root.querySelector('.project-files').hidden=source.value!=='files';root.querySelector('.project-import-hint').textContent=mode.value==='apply'?'Loads processing settings only. Review normalization, draw new ROIs and reselect reference pixels before calculating. This is not reproduction of the old result.':'External raw data must match the saved pattern, wavenumber, dimensions and values. Lightweight ZIPs require external data. For bundles with different raw folders, import each inner results.zip separately.';};
    mode.onchange=source.onchange=update;update();
    root.querySelector('.project-folder button').onclick=async()=>{try{const selected=await QCLUpload.chooseFolder();if(selected){path=selected;root.querySelector('.project-path').textContent=path;}}catch(e){root.querySelector('.project-import-hint').textContent=e.message;}};
    return {async send(file,url,params={}){
      let staging=null;
      const modeValue=mode.value,sourceValue=source.value;
      root.querySelectorAll('input,select,button').forEach(n=>n.disabled=true);
      try{
        if(sourceValue!=='embedded'){
          if(sourceValue==='folder'&&!path)throw Error('Choose the raw data folder first.');
          const response=sourceValue==='folder'?await fetch('/api/datasets',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path,name:'External raw input'})}):await fetch('/api/datasets/upload-csv',{method:'POST',body:QCLUpload.stream(root.querySelector('.project-files input').files)});
          staging=await response.json();if(!response.ok)throw Error(staging.error||'Raw data import failed.');
        }
        const target=new URL(url,location.href);for(const [key,value] of Object.entries({...params,mode:modeValue,...(staging?.id?{raw_dataset:staging.id}:{})}))target.searchParams.set(key,value);
        const response=await fetch(target.pathname+target.search,{method:'POST',headers:{'Content-Type':'application/zip'},body:file});
        const result=await response.json();if(!response.ok)throw Error(result.error||'Project import failed.');return result;
      }finally{
        if(staging?.id)try{await fetch('/api/datasets/remove',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:staging.id})});}catch(e){}
        root.querySelectorAll('input,select,button').forEach(n=>n.disabled=false);update();
      }
    }};
  }
};
