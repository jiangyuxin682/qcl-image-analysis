'use strict';
// File objects carry relative paths and modification times, never local absolute paths.
globalThis.QCLUpload={
  zipName(value,fallback='qcl-processing'){
    let name=String(value||'').trim().replace(/[\x00-\x1f\x7f<>:"/\\|?*]/g,'_').replace(/(?:\.zip)+$/i,'').replace(/^[. ]+|[. ]+$/g,'');
    if(!name)name=fallback;
    if(/^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/i.test(name))name='_'+name;
    return Array.from(name).slice(0,120).join('').replace(/[. ]+$/g,'')+'.zip';
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
