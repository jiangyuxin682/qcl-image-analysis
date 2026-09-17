'use strict';
const $=s=>document.querySelector(s),$$=s=>[...document.querySelectorAll(s)];
const names={clean:'Clean source',input:'Input with optional noise',filtered:'After Fourier filtering',removed:'Removed signal · input − filtered',fft_clean:'FFT · clean source',fft_input:'FFT · noisy input · click to notch',fft_filtered:'FFT · after filtering',fft_removed:'FFT · rejected frequencies',mask:'Filter mask · fraction retained'};
const zero=new Set();let file=null,lastConfig=null,lastResult=null,dirty=true,running=false,revision=0;
function el(tag,text){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;}
function status(text,error=false){$('#status').textContent=text;$('#status').className=error?'error':'';}
function controls(){
  const type=$('#source').value,mode=$('#filter').value;
  $('#synthetic').hidden=type==='upload';$('#upload').hidden=type!=='upload';
  $$('[data-source]').forEach(n=>n.hidden=!n.dataset.source.split(' ').includes(type));
  $('#radius-field').hidden=$('#corners').value!=='round';
  $('#edge_sigma').disabled=!$('#edge_smoothing').checked;
  $('#lowpass-fields').hidden=!['lowpass','combined'].includes(mode);$('#notch-fields').hidden=!['notch','combined'].includes(mode);
  for(const [flag,ids] of [['gaussian',['noise_sigma']],['impulse',['impulse_rate']],['stripes',['stripe_amplitude','stripe_period','stripe_angle']]])ids.forEach(id=>$('#'+id).disabled=!$('#'+flag).checked);
}
function changed(){revision++;dirty=true;$('#export').disabled=true;status('Settings changed · generate to update the experiment.');controls();}
$('#settings').addEventListener('input',changed);$('#settings').addEventListener('change',controls);$('#settings').onsubmit=e=>{e.preventDefault();run();};
function configuration(){
  const result={};for(const n of $$('#settings input[id], #settings select, #settings textarea')){if(n.id==='file')continue;result[n.id]=n.type==='checkbox'?n.checked:n.type==='number'?Number(n.value):n.value;}
  result.notches=result.notches.split(/[;\n]+/).filter(s=>s.trim()).map(s=>{const pieces=s.split(',');if(pieces.length!==2||pieces.some(p=>!p.trim()||!Number.isFinite(Number(p))))throw Error('Notch centers must be fy, fx pairs.');return pieces.map(Number);});
  if(result.source==='upload'){if(!file)throw Error('Choose an image or CSV first.');Object.assign(result,file);}
  result.zero_images=[...zero];return result;
}
$('#file').onchange=async()=>{
  const chosen=$('#file').files[0];file=null;changed();if(!chosen)return;
  if(chosen.size>8000000){status('Choose a file smaller than 8 MB.',true);return;}
  try{const data=await new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(r.result.split(',')[1]);r.onerror=()=>reject(Error('Could not read file.'));r.readAsDataURL(chosen);});
    if($('#file').files[0]!==chosen)return;file={filename:chosen.name,file_data:data};$('#file-status').textContent=chosen.name;status('File loaded · generate to inspect.');
  }catch(e){status(e.message,true);}
};
$('#new-seed').onclick=()=>{$('#seed').value=crypto.getRandomValues(new Uint32Array(1))[0];changed();};
$('#clear-notches').onclick=()=>{$('#notches').value='';changed();};
async function api(path,config){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(config)});if(!r.ok)throw Error((await r.json()).error||'Request failed');return r;}
async function run(displayOnly=false){
  if(running)return;
  let config;try{config=displayOnly?{...lastConfig,zero_images:[...zero]}:configuration();}catch(e){status(e.message,true);return;}
  const at=revision;running=true;$('#run').disabled=true;$('#export').disabled=true;status('Generating image and Fourier diagnostics…');
  try{const result=await (await api('/api/analyze',config)).json();lastConfig=config;lastResult=result;dirty=at!==revision||displayOnly&&dirty;render(result);status(dirty?'Showing previous settings · generate to update.':'Current experiment · click the input FFT to select a notch.');}
  catch(e){dirty=true;status(e.message,true);}
  finally{running=false;$('#run').disabled=false;$('#export').disabled=dirty||!lastConfig;}
}
$('#run').onclick=()=>run();
function render(result){
  for(const id of ['spatial-grid','fft-grid','mask-grid'])$('#'+id).replaceChildren();
  for(const data of result.cards){
    const card=el('article');card.className='card'+(data.key.startsWith('fft_')?' fft':'');card.dataset.key=data.key;card.append(el('h3',names[data.key]));
    const wrap=el('div');wrap.className='heatmap';const picture=el('div');picture.className='picture';const img=el('img');img.alt=names[data.key];img.src='data:image/png;base64,'+data.png;picture.append(img);wrap.append(picture);
    const bar=el('div');bar.className='bar';const strip=el('div');strip.className='strip';if(data.palette==='gray')strip.style.background='linear-gradient(to top,#000,#fff)';if(data.palette==='coolwarm')strip.style.background='linear-gradient(to top,#3b4cc0,#ddd,#b40426)';const ticks=el('div');ticks.className='ticks';[data.vmax,(data.vmax+data.vmin)/2,data.vmin].forEach(v=>ticks.append(el('span',v.toFixed(3))));bar.append(strip,ticks);wrap.append(bar);card.append(wrap);
    if(data.key.startsWith('fft_')||data.key==='mask'){
      const axis=el('div');axis.className='axes';axis.append(el('span',`fx ${result.fx[0].toFixed(3)}`),el('span','0'),el('span',result.fx.at(-1).toFixed(3)));card.append(axis);
      card.append(el('p',`fy ${result.fy[0].toFixed(3)} (top) → ${result.fy.at(-1).toFixed(3)} (bottom)`));card.lastChild.className='hint';
    }
    if(data.key==='fft_input')picture.onclick=event=>{
      if(running)return;const box=img.getBoundingClientRect(),ix=Math.max(0,Math.min(data.width-1,Math.floor((event.clientX-box.left)/box.width*data.width))),iy=Math.max(0,Math.min(data.height-1,Math.floor((event.clientY-box.top)/box.height*data.height)));
      const fy=result.fy[iy],fx=result.fx[ix];$('#notches').value+=($('#notches').value.trim()?'\n':'')+`${fy.toFixed(6)}, ${fx.toFixed(6)}`;
      if(!['notch','combined'].includes($('#filter').value))$('#filter').value='notch';changed();status(`Added (fy ${fy.toFixed(4)}, fx ${fx.toFixed(4)}) and its partner · apply filter to inspect.`);
    };
    const label=el('label');label.className='check';const check=el('input');check.type='checkbox';check.checked=zero.has(data.key);label.append(check,document.createTextNode('Set lower limit to 0 · display only'));card.append(label);
    check.onchange=()=>{if(running){check.checked=zero.has(data.key);return;}check.checked?zero.add(data.key):zero.delete(data.key);run(true);};
    $('#'+(data.key.startsWith('fft_')?'fft-grid':data.key==='mask'?'mask-grid':'spatial-grid')).append(card);
  }
  $('#summary').replaceChildren();for(const [key,label] of [['input_rmse','Input RMSE vs source'],['filtered_rmse','Filtered RMSE vs source'],['removed_rms','Removed signal RMS']]){const n=el('div');n.className='metric';n.append(el('small',label),el('b',result.metrics[key].toExponential(3)));$('#summary').append(n);}
  $('#profile-title').textContent=`Intensity along row ${result.profile_row}`;profile(result.profiles);
}
function profile(profiles){
  const svg=$('#profile');svg.replaceChildren();const ns='http://www.w3.org/2000/svg';
  const values=Object.values(profiles).flat(),lo=Math.min(...values),hi=Math.max(...values),span=hi-lo||1;
  const make=(tag,attrs,text)=>{const n=document.createElementNS(ns,tag);for(const [k,v] of Object.entries(attrs))n.setAttribute(k,v);if(text!==undefined)n.textContent=text;svg.append(n);return n;};
  for(let i=0;i<5;i++){const y=25+i*60;make('line',{x1:62,x2:685,y1:y,y2:y,stroke:'#e2eae6'});make('text',{x:3,y:y+4,'font-size':11,fill:'#61766d'},(hi-span*i/4).toFixed(3));}
  for(const [key,color] of [['clean','#203b36'],['input','#bd7829'],['filtered','#168d87']]){const a=profiles[key];make('polyline',{points:a.map((v,i)=>`${62+i/(a.length-1)*623},${25+(hi-v)/span*240}`).join(' '),fill:'none',stroke:color,'stroke-width':1.5});}
  make('text',{x:62,y:289,'font-size':11},'0');make('text',{x:650,y:289,'font-size':11},String(profiles.clean.length-1));make('text',{x:315,y:312,'font-size':12},'x · pixels');
}
$('#export').onclick=async()=>{if(dirty||!lastConfig||running)return;$('#export').disabled=true;try{const r=await api('/api/export',lastConfig),url=URL.createObjectURL(await r.blob()),a=el('a');a.href=url;a.download='fourier-experiment.zip';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);status('Exported arrays, complex FFTs and reproducible settings.');}catch(e){status(e.message,true);}finally{$('#export').disabled=dirty;}};
controls();run();
