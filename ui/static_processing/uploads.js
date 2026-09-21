'use strict';
// File objects carry relative paths and modification times, never local absolute paths.
globalThis.QCLUpload={
  zipName(value,fallback='qcl-processing'){
    let name=String(value||'').trim().replace(/[\x00-\x1f\x7f<>:"/\\|?*]/g,'_').replace(/(?:\.zip)+$/i,'').replace(/^[. ]+|[. ]+$/g,'');
    if(!name)name=fallback;
    if(/^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/i.test(name))name='_'+name;
    return Array.from(name).slice(0,120).join('').replace(/[. ]+$/g,'')+'.zip';
  },
  stream(files,name=''){
    const selected=[...files].filter(file=>/^lineScan_\d+_0invcm\.csv$/i.test(file.name));
    if(!selected.length)throw Error('Choose spectral CSV files from one pattern.');
    const metadata=new TextEncoder().encode(JSON.stringify({kind:'files',name,files:selected.map(file=>({path:file.name,size:file.size,last_modified:file.lastModified}))}));
    const header=new ArrayBuffer(8);new DataView(header).setBigUint64(0,BigInt(metadata.length));
    return new Blob([header,metadata,...selected],{type:'application/octet-stream'});
  },
  async chooseFolder(){
    const response=await fetch('/api/choose-folder',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
    const result=await response.json();if(!response.ok)throw Error(result.error||'Folder selection failed.');return result.path;
  },
  data(files,kind,name=''){
    const selected=[...files].filter(file=>/^lineScan_\d+_0invcm\.csv$/i.test(file.name));
    if(!selected.length)throw Error('Choose a data folder or lineScan_<wavenumber>_0invcm.csv files.');
    if(selected.reduce((sum,file)=>sum+file.size,0)>1024**3)throw Error('Selected CSVs exceed the 1 GiB upload limit.');
    const form=new FormData();
    form.append('metadata',JSON.stringify({kind,name,files:selected.map(file=>({path:kind==='folder'?file.webkitRelativePath:file.name,last_modified:file.lastModified}))}));
    selected.forEach((file,i)=>form.append('files',file,`image_${i}.csv`));
    return form;
  }
};
