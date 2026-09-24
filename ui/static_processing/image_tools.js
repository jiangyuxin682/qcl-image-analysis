/* Shared display tools for Section 8 and Final comparison. */
window.QCLImages = (() => {
  const orientation = {horizontal:false, vertical:false};
  const section=document.querySelector('section[data-step="8"]')||document.querySelector('#comparison');
  const controls=document.querySelector('#cnr-flip-controls')||document.querySelector('#compare-flip-controls');
  const style=document.createElement('style');
  style.textContent='#six-stages .heatmap canvas,#six-stages .heatmap svg,#comparison-grid .heatmap img,#comparison-grid .roi-overlay{transform:scale(var(--image-flip-x,1),var(--image-flip-y,1));transform-origin:center}';
  document.head.append(style);
  if(controls)for(const axis of ['horizontal','vertical']){
    const label=document.createElement('label');label.className='check';
    const input=document.createElement('input');input.type='checkbox';input.id='flip-'+axis;
    input.onchange=()=>{orientation[axis]=input.checked;section.style.setProperty('--image-flip-'+(axis==='horizontal'?'x':'y'),input.checked?'-1':'1');window.QCLLine?.orientLabels(section,orientation);window.QCLPixelAxes?.refresh();};
    label.append(input,document.createTextNode(axis==='horizontal'?'Horizontal flip':'Vertical flip'));controls.append(label);
  }
  function eventPoint(event,image){
    if(!image.closest('#six-stages, #comparison-grid'))return {clientX:event.clientX,clientY:event.clientY};
    const rect=image.getBoundingClientRect();
    return {clientX:orientation.horizontal?rect.left+rect.right-event.clientX:event.clientX,
            clientY:orientation.vertical?rect.top+rect.bottom-event.clientY:event.clientY};
  }
  function wrapText(ctx,text,width){
    const lines=[];let line='';
    for(const word of text.split(/\s+/)){
      const next=line?line+' '+word:word;
      if(line&&ctx.measureText(next).width>width){lines.push(line);line=word;}else line=next;
    }
    if(line)lines.push(line);return lines;
  }
  async function svgImage(svg,width,height,flip=null){
    const copy=svg.cloneNode(true);
    copy.setAttribute('xmlns','http://www.w3.org/2000/svg');
    copy.setAttribute('width',width);copy.setAttribute('height',height);
    copy.style.cssText='';
    if(flip)window.QCLLine?.orientLabels(copy,flip);
    const image=new Image();
    image.src='data:image/svg+xml;charset=utf-8,'+encodeURIComponent(new XMLSerializer().serializeToString(copy));
    await image.decode();return image;
  }
  async function download(image,data,title,filename,card,details={}){
    const w=Math.max(600,data.width),h=Math.round(w*data.height/data.width),out=document.createElement('canvas');
    const ctx=out.getContext('2d');
    const metrics=card.querySelector('.cnr-parameters');
    const parameters=metrics?[...metrics.children].map(node=>{
      const copy=node.cloneNode(true);
      copy.querySelectorAll('sub').forEach(sub=>{sub.textContent='_'+sub.textContent;});
      return copy.textContent;
    }):[];
    parameters.unshift(...(details.information||[]));
    const zero=card.querySelector('input[type="checkbox"]');
    parameters.push(`Color limits: ${data.vmin.toPrecision(6)} to ${data.vmax.toPrecision(6)}${zero?` · Lower limit set to 0: ${zero.checked?'yes':'no'}`:''}`);
    const flip={...orientation};
    parameters.push(`Horizontal flip: ${flip.horizontal?'yes':'no'} · Vertical flip: ${flip.vertical?'yes':'no'}`);
    ctx.font='bold 18px sans-serif';const titles=wrapText(ctx,title,w+120);
    ctx.font='15px sans-serif';const lines=parameters.flatMap(text=>wrapText(ctx,text,w+120));
    const imageTop=24+titles.length*26+lines.length*22+18;
    const profile=card.querySelector('.line-profile-plot');
    const profileStatus=profile?(details.profileStatus??document.querySelector('#profile-status')?.textContent??''):'';
    const profileLines=profile?wrapText(ctx,profileStatus,w+120):[];
    const profileHeight=profile?Math.round(w*225/360):0;
    const profileTop=imageTop+h+104+profileLines.length*22;
    out.width=w+220;out.height=profile?profileTop+profileHeight+24:imageTop+h+74;
    ctx.fillStyle='white';ctx.fillRect(0,0,out.width,out.height);ctx.fillStyle='#213a35';
    ctx.font='bold 18px sans-serif';titles.forEach((line,i)=>ctx.fillText(line,20,24+i*26));
    ctx.font='15px sans-serif';lines.forEach((line,i)=>ctx.fillText(line,20,24+titles.length*26+i*22));
    ctx.save();ctx.translate(80+(flip.horizontal?w:0),imageTop+(flip.vertical?h:0));
    ctx.scale(flip.horizontal?-1:1,flip.vertical?-1:1);ctx.drawImage(image,0,0,w,h);
    const svg=card.querySelector('.roi-overlay');
    if(svg)ctx.drawImage(await svgImage(svg,data.width,data.height,flip),0,0,w,h);
    ctx.restore();
    window.QCLPixelAxes.drawCanvas(ctx,{x:80,y:imageTop,width:w,height:h,columns:data.width,rows:data.height,...flip});
    const gradient=getComputedStyle(card.querySelector('.strip')).backgroundImage;
    const colors=[...gradient.matchAll(/rgba?\([^)]+\)|#[\da-f]{3,8}/gi)].map(m=>m[0]);
    const ramp=ctx.createLinearGradient(0,imageTop+h,0,imageTop);
    colors.forEach((c,i)=>ramp.addColorStop(i/Math.max(1,colors.length-1),c));
    ctx.fillStyle=colors.length?ramp:'#000';ctx.fillRect(w+100,imageTop,18,h);ctx.fillStyle='#213a35';ctx.font='14px sans-serif';
    [data.vmax,(data.vmin+data.vmax)/2,data.vmin].forEach((v,i)=>ctx.fillText(v.toFixed(3),w+128,imageTop+10+(h-12)*i/2));
    if(profile){
      ctx.font='bold 18px sans-serif';ctx.fillText('Line profile',20,imageTop+h+82);
      ctx.font='15px sans-serif';profileLines.forEach((line,i)=>ctx.fillText(line,20,imageTop+h+106+i*22));
      // The plot keeps its normal axes and S-to-E ordering when the heatmap flips.
      ctx.drawImage(await svgImage(profile,720,450),20,profileTop,w,profileHeight);
    }
    const blob=await new Promise(resolve=>out.toBlob(resolve,'image/png'));if(!blob)throw Error('PNG export failed.');
    const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=filename.replace(/[<>:"/\\|?*\x00-\x1f]/g,'_')+'.png';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  function setColorbar(strip,name){
    const colors={gray_r:['white','black'],gray:['black','white'],magenta:['black','#ff00ff'],yellow:['black','#ffff00'],blue:['black','#0000ff']};
    strip.style.background=colors[name]?`linear-gradient(to top, ${colors[name].join(', ')})`:'';
  }
  return {orientation,eventPoint,download,setColorbar};
})();
