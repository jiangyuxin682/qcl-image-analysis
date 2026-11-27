/* Independent, browser-local incubator log viewer. Never enters processing state. */
'use strict';
(function(root){
  const fields=[
    ['temperature_C','Air temperature','°C','#e32939'],
    ['temperatureMedium_C','Medium temperature','°C','#8626ae'],
    ['humidity_pct','Humidity','%','#087abb'],
    ['heater','Heater'],['humidifier','Humidifier'],['fan','Fan'],['servo','Servo'],
    ['heaterStandby','Heater standby'],['humidifierStandby','Humidifier standby'],
    ['fanStandby','Fan standby'],['servoStandby','Servo standby'],
    ['waterLevel','Water level','raw units','#222']
  ].map(([key,label,unit,color])=>({key,label,unit:unit||'',color:color||'#111',binary:!unit}));
  function parse(text){
    let header=null, rows=[], skipped=0;
    for(const raw of text.replace(/^\uFEFF/,'').split(/\r?\n/)){
      const line=raw.trim().replace(/^\[[^\]]+\]\s*/,'');
      if(!line)continue;
      const cells=line.split(',').map(v=>v.trim());
      if(cells[0]==='time_s'){
        if(new Set(cells).size!==cells.length)throw Error('Duplicate column names in log header.');
        if(header&&header.join(',')!==cells.join(','))throw Error('The log contains different headers. Import one recording at a time.');
        header=cells;continue;
      }
      if(!header){skipped++;continue;}
      const values=cells.map(v=>v===''?NaN:Number(v));
      const active=fields.filter(f=>header.includes(f.key));
      if(cells.length!==header.length||values.some(v=>!Number.isFinite(v))||values[0]<0||active.some(f=>f.binary&&![0,1].includes(values[header.indexOf(f.key)]))){skipped++;continue;}
      if(rows.length&&values[0]<=rows[rows.length-1].time_s)throw Error('Elapsed time repeats or goes backwards. Import a single uninterrupted recording.');
      rows.push(Object.fromEntries(header.map((key,i)=>[key,values[i]])));
    }
    if(!header||!rows.length)throw Error('No valid incubator data found. Expected a time_s CSV header and numeric data rows.');
    const available=fields.filter(f=>header.includes(f.key));
    if(!available.length)throw Error('No recognized incubator measurements found.');
    return {rows,fields:available,skipped};
  }
  function statistics(rows,key,start,end){
    let n=0,mean=0,m2=0,min=Infinity,max=-Infinity;
    for(const row of rows){if(row.time_s<start||row.time_s>end)continue;const v=row[key];n++;const d=v-mean;mean+=d/n;m2+=d*(v-mean);min=Math.min(min,v);max=Math.max(max,v);}
    return n?{n,mean,sd:Math.sqrt(m2/n),min,max}:null;
  }
  root.QCLIncubator={parse,statistics,fields};
  if(typeof document==='undefined')return;
  const panel=document.querySelector('#incubator-panel');if(!panel)return;
  const $=s=>panel.querySelector(s);
  let data=null,revision=0,recordingName='incubator',exporting=false;
  function node(tag,text){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;return e;}
  function svgNode(tag,attrs,text){const e=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [k,v]of Object.entries(attrs))e.setAttribute(k,v);if(text!==undefined)e.textContent=text;return e;}
  function render(){
    if(!data)return;
    const start=Number($('#incubator-start').value)*3600,end=Number($('#incubator-end').value)*3600;
    const valid=$('#incubator-start').value!==''&&$('#incubator-end').value!==''&&Number.isFinite(start)&&Number.isFinite(end)&&start>=0&&end>=start;
    $('#incubator-range-status').textContent=valid?'Statistics use samples within the inclusive interval (population standard deviation).':'Enter a valid statistics interval: 0 ≤ start ≤ end.';
    const plots=$('#incubator-plots');plots.replaceChildren();
    const rows=data.rows,t0=rows[0].time_s/3600,t1=rows[rows.length-1].time_s/3600;
    const x=t=>100+(t-t0)/(t1-t0||1)*850;
    for(const f of data.fields){
      if(!$('#incubator-field-'+f.key).checked)continue;
      const block=node('div');block.className='incubator-plot';
      const heading=node('div');heading.className='incubator-plot-heading';
      const title=node('strong',f.label+(f.unit?' ('+f.unit+')':''));title.style.color=f.color;heading.append(title);
      if(!f.binary){const s=valid?statistics(rows,f.key,start,end):null;heading.append(node('span',s?`Mean ${s.mean.toFixed(2)} ± ${s.sd.toFixed(2)} ${f.unit} · Min ${s.min.toFixed(2)} · Max ${s.max.toFixed(2)} · n = ${s.n}`:valid?'No samples in the statistics interval.':'Statistics interval is invalid.'));}
      block.append(heading);
      const height=f.binary?92:170,bottom=height-28,top=12;
      const svg=svgNode('svg',{viewBox:`0 0 980 ${height}`,role:'img','aria-label':f.label+' versus elapsed time in hours'});
      let lo=Infinity,hi=-Infinity;for(const r of rows){lo=Math.min(lo,r[f.key]);hi=Math.max(hi,r[f.key]);}
      if(f.binary){lo=0;hi=1;}else{const pad=(hi-lo)*.1||Math.max(Math.abs(hi)*.02,1);lo-=pad;hi+=pad;}
      const y=v=>bottom-(v-lo)/(hi-lo)*(bottom-top);
      svg.append(svgNode('rect',{x:100,y:top,width:850,height:bottom-top,fill:'white',stroke:'#aaa'}));
      if(valid&&end/3600>=t0&&start/3600<=t1){const a=x(Math.max(t0,start/3600)),b=x(Math.min(t1,end/3600));svg.append(svgNode('rect',{x:a,y:top,width:Math.max(0,b-a),height:bottom-top,fill:'#e5f1e9',opacity:.65}));}
      for(let i=0;i<=5;i++){const t=t0+(t1-t0)*i/5,xx=x(t);svg.append(svgNode('line',{x1:xx,x2:xx,y1:top,y2:bottom,stroke:'#ddd','stroke-dasharray':'3 3'}));svg.append(svgNode('text',{x:xx,y:height-8,'text-anchor':'middle'},t.toFixed(3)));}
      for(let i=0;i<=(f.binary?1:3);i++){const v=lo+(hi-lo)*i/(f.binary?1:3),yy=y(v);svg.append(svgNode('text',{x:90,y:yy+4,'text-anchor':'end'},f.binary?(v?'ON':'OFF'):v.toFixed(1)));if(!f.binary)svg.append(svgNode('line',{x1:100,x2:950,y1:yy,y2:yy,stroke:'#ddd','stroke-dasharray':'3 3'}));}
      // Keep every sample and every transition, including short actuator pulses.
      let d='';for(let i=0;i<rows.length;i++){const xx=x(rows[i].time_s/3600).toFixed(2),yy=y(rows[i][f.key]).toFixed(2);d+=i?(f.binary?`H${xx}V${yy}`:`L${xx},${yy}`):`M${xx},${yy}`;}
      if(f.binary)d+=`V${bottom}H100Z`;
      svg.append(svgNode('path',{d,fill:f.binary?f.color:'none',stroke:f.color,'stroke-width':f.binary?.6:1.3,'vector-effect':'non-scaling-stroke'}));
      if(rows.length===1)svg.append(svgNode('circle',{cx:x(t0),cy:y(rows[0][f.key]),r:3,fill:f.color}));
      block.append(svg);plots.append(block);
    }
    $('#incubator-download').disabled=exporting||!plots.children.length;
    plots.append(node('p',plots.children.length?'Elapsed time (h)':'Select at least one measurement to display.'));
  }
  async function downloadPNG(){
    const blocks=[...$('#incubator-plots').querySelectorAll('.incubator-plot')];
    if(!blocks.length||exporting)return;
    exporting=true;$('#incubator-download').disabled=true;
    $('#incubator-export-status').textContent='Preparing PNG…';
    let imageURL=null;
    try{
      // Snapshot the displayed SVGs and text before awaiting image decoding.
      const filename=recordingName+'-incubator.png';
      const svg=svgNode('svg',{'font-family':'Arial, sans-serif','font-size':12});
      const background=svgNode('rect',{width:'100%',height:'100%',fill:'white'});svg.append(background);
      svg.append(svgNode('text',{x:30,y:30,'font-size':20,'font-weight':'bold'},'Incubator recording'));
      svg.append(svgNode('text',{x:30,y:54},`Statistics interval: ${$('#incubator-start').value}–${$('#incubator-end').value} h · Mean ± population SD`));
      svg.append(svgNode('text',{x:30,y:74,fill:'#46515e'},'Pale green: statistics interval. Curves show the full recording.'));
      let offset=94;
      for(const block of blocks){
        const title=block.querySelector('strong'),stats=block.querySelector('.incubator-plot-heading span');
        svg.append(svgNode('text',{x:30,y:offset+16,fill:title.style.color,'font-size':15,'font-weight':'bold'},title.textContent));
        if(stats)svg.append(svgNode('text',{x:30,y:offset+36,fill:'#46515e','font-size':13},stats.textContent));
        const plot=block.querySelector('svg').cloneNode(true);
        const height=Number(plot.getAttribute('viewBox').split(' ')[3]);
        plot.setAttribute('x',0);plot.setAttribute('y',offset+(stats?44:24));
        plot.setAttribute('width',980);plot.setAttribute('height',height);
        svg.append(plot);offset+=height+(stats?54:34);
      }
      svg.append(svgNode('text',{x:525,y:offset+16,'text-anchor':'middle','font-size':15},'Elapsed time (h)'));
      const height=offset+36;
      svg.setAttribute('width',980);svg.setAttribute('height',height);svg.setAttribute('viewBox',`0 0 980 ${height}`);
      imageURL=URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(svg)],{type:'image/svg+xml;charset=utf-8'}));
      const image=new Image();
      await new Promise((resolve,reject)=>{image.onload=resolve;image.onerror=()=>reject(Error('Could not render the chart image.'));image.src=imageURL;});
      const canvas=document.createElement('canvas');canvas.width=1960;canvas.height=height*2;
      const context=canvas.getContext('2d');if(!context)throw Error('Canvas image export is unavailable.');
      context.drawImage(image,0,0,canvas.width,canvas.height);
      const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/png'));
      if(!blob)throw Error('Could not create the PNG image.');
      const downloadURL=URL.createObjectURL(blob),link=node('a');
      link.href=downloadURL;link.download=filename;document.body.append(link);link.click();link.remove();
      setTimeout(()=>URL.revokeObjectURL(downloadURL),60000);
      $('#incubator-export-status').textContent='PNG download started.';
    }catch(error){$('#incubator-export-status').textContent='Download failed: '+error.message;}
    finally{if(imageURL)URL.revokeObjectURL(imageURL);exporting=false;$('#incubator-download').disabled=!$('#incubator-plots').querySelector('.incubator-plot');}
  }
  $('#incubator-download').addEventListener('click',downloadPNG);
  $('#incubator-file').addEventListener('change',async event=>{
    const file=event.target.files[0];if(!file)return;const current=++revision;
    $('#incubator-status').textContent='Reading '+file.name+'…';
    try{
      const next=parse(await file.text());if(current!==revision)return;data=next;recordingName=file.name.replace(/\.[^.]+$/,'');
      $('#incubator-status').textContent=`${file.name} · ${data.rows.length.toLocaleString()} samples · ${(data.rows[0].time_s/3600).toFixed(3)}–${(data.rows[data.rows.length-1].time_s/3600).toFixed(3)} h${data.skipped?' · '+data.skipped+' invalid / non-data lines skipped':''}`;
      $('#incubator-controls').hidden=false;
      $('#incubator-start').value=String(data.rows[0].time_s/3600);
      $('#incubator-end').value=String(data.rows[data.rows.length-1].time_s/3600);
      const choices=$('#incubator-fields');choices.replaceChildren();
      for(const f of data.fields){const label=node('label');label.className='check';const input=node('input');input.type='checkbox';input.checked=true;input.id='incubator-field-'+f.key;input.addEventListener('change',render);label.append(input,document.createTextNode(f.label));choices.append(label);}
      render();
    }catch(error){if(current===revision)$('#incubator-status').textContent=error.message+(data?' Previous recording remains displayed.':'');}
  });
  for(const id of ['#incubator-start','#incubator-end'])$(id).addEventListener('input',render);
})(globalThis);
