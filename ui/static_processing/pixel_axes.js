/* Pixel-center coordinates, independent of ROI overlays and numerical arrays. */
window.QCLPixelAxes = (() => {
  const entries=new Map();
  function ticks(size,extent,reverse=false){
    const count=extent>=280?5:3;
    const indices=[...new Set(Array.from({length:count},(_,i)=>Math.round(i*(size-1)/(count-1))))];
    return indices.map(value=>({value,position:(reverse?1-(value+.5)/size:(value+.5)/size)*extent}));
  }
  function render(entry){
    const {image,host,svg}=entry;
    if(!image.isConnected){entry.observer?.disconnect();entries.delete(image);return;}
    const width=entry.width||image.width;
    const height=entry.height||image.height;
    const box=image.getBoundingClientRect(),frame=host.getBoundingClientRect();
    if(!width||!height||!box.width||!box.height)return;
    const x=box.left-frame.left,y=box.top-frame.top;
    const flip=image.closest('#six-stages, #comparison-grid')?window.QCLImages?.orientation||{}:{};
    svg.setAttribute('viewBox',`0 0 ${frame.width} ${frame.height}`);svg.replaceChildren();
    const node=(tag,attrs,text)=>{const n=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [k,v] of Object.entries(attrs))n.setAttribute(k,v);if(text!==undefined)n.textContent=text;svg.append(n);};
    const line=(x1,y1,x2,y2)=>node('line',{x1,y1,x2,y2,stroke:'#687a72','stroke-width':1});
    const text=(tx,ty,value,extra={})=>node('text',{x:tx,y:ty,fill:'#435b50','font-size':10,'font-family':'sans-serif',...extra},value);
    line(x,y+box.height,x+box.width,y+box.height);line(x,y,x,y+box.height);
    for(const tick of ticks(width,box.width,flip.horizontal)){line(x+tick.position,y+box.height,x+tick.position,y+box.height+4);text(x+tick.position,y+box.height+15,tick.value,{'text-anchor':'middle'});}
    for(const tick of ticks(height,box.height,flip.vertical)){line(x-4,y+tick.position,x,y+tick.position);text(x-7,y+tick.position+3,tick.value,{'text-anchor':'end'});}
    text(x+box.width/2,y+box.height+31,'X (pixel)',{'text-anchor':'middle'});
    text(11,y+box.height/2,'Y (pixel)',{'text-anchor':'middle',transform:`rotate(-90 11 ${y+box.height/2})`});
  }
  function attach(image,dimensions={}){
    if(!image)return;
    if(entries.has(image)){Object.assign(entries.get(image),dimensions);render(entries.get(image));return;}
    let host=image.closest('.heatmap');
    if(!host){host=document.createElement('div');host.className='pixel-axis-frame';image.replaceWith(host);host.append(image);}
    host.classList.add('has-pixel-axes');
    const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.classList.add('pixel-axes');svg.setAttribute('aria-label','Image X and Y pixel axes');host.append(svg);
    const entry={image,host,svg,...dimensions};entries.set(image,entry);
    entry.observer=new ResizeObserver(()=>render(entry));entry.observer.observe(image);entry.observer.observe(host);
    image.addEventListener('load',()=>render(entry));render(entry);
  }
  function refresh(){for(const entry of entries.values())render(entry);}
  function drawCanvas(ctx,{x,y,width,height,columns,rows,horizontal=false,vertical=false}){
    ctx.save();ctx.fillStyle='#435b50';ctx.strokeStyle='#687a72';ctx.lineWidth=1;ctx.font='13px sans-serif';
    const line=(x1,y1,x2,y2)=>{ctx.beginPath();ctx.moveTo(x1,y1);ctx.lineTo(x2,y2);ctx.stroke();};
    line(x,y+height,x+width,y+height);line(x,y,x,y+height);
    ctx.textAlign='center';
    for(const tick of ticks(columns,width,horizontal)){line(x+tick.position,y+height,x+tick.position,y+height+5);ctx.fillText(String(tick.value),x+tick.position,y+height+20);}
    ctx.fillText('X (pixel)',x+width/2,y+height+39);ctx.textAlign='right';
    for(const tick of ticks(rows,height,vertical)){line(x-5,y+tick.position,x,y+tick.position);ctx.fillText(String(tick.value),x-9,y+tick.position+4);}
    ctx.translate(x-52,y+height/2);ctx.rotate(-Math.PI/2);ctx.textAlign='center';ctx.fillText('Y (pixel)',0,0);ctx.restore();
  }
  return {attach,refresh,ticks,drawCanvas};
})();
