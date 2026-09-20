'use strict';
// Shared line geometry and rendering for stage and folder comparisons.
(function(){
function snapEnd(start,end,direction){
  return direction==='vertical'?{x:start.x,y:end.y}:{x:end.x,y:start.y};
}
function drawLine(overlay,start,end,width){
  overlay.querySelector('.profile-line-overlay')?.remove();
  if(!start)return;
  const group=document.createElementNS('http://www.w3.org/2000/svg','g');group.classList.add('profile-line-overlay');overlay.append(group);
  const ns='http://www.w3.org/2000/svg';
  if(end){
    const line=document.createElementNS(ns,'line');
    for(const [key,value] of Object.entries({x1:start.x+.5,y1:start.y+.5,x2:end.x+.5,y2:end.y+.5,stroke:'#00dfff','stroke-width':1.5,'stroke-dasharray':'6 4','vector-effect':'non-scaling-stroke'}))line.setAttribute(key,value);
    group.append(line);
  }
  for(const [label,p] of [['S',start],['E',end]]){
    if(!p)continue;
    const text=document.createElementNS(ns,'text');text.textContent=label;
    text.setAttribute('x',p.x+.5);text.setAttribute('y',p.y+.5);text.setAttribute('fill','#00dfff');text.setAttribute('font-size',Math.max(3,width/40));text.setAttribute('paint-order','stroke');text.setAttribute('stroke','#173c39');text.setAttribute('stroke-width',.3);group.append(text);
  }
}
function renderPlot(root,kind,title,hasGold,result){
  const values=result.profiles[kind];if(!values)return;
  const ns='http://www.w3.org/2000/svg';
  root.querySelector('.line-profile-plot')?.remove();
  const svg=document.createElementNS(ns,'svg');svg.classList.add('line-profile-plot');svg.setAttribute('viewBox','0 0 360 225');svg.setAttribute('role','img');svg.setAttribute('aria-label',title+' line profile');svg.style.cssText='width:100%;height:auto;margin-top:14px;display:block';root.append(svg);
  function node(tag,attrs,text){const n=document.createElementNS(ns,tag);for(const [key,value] of Object.entries(attrs))n.setAttribute(key,value);if(text!==undefined)n.textContent=text;svg.append(n);return n;}
  const finite=values.filter(Number.isFinite),left=78,right=345,top=24,bottom=177;
  const ylabel=['absorbance','baseline'].includes(kind)?'Absorbance':kind==='reflectance'||(hasGold&&['fourier','rolling'].includes(kind))?'Reflectance':'Intensity';
  node('text',{x:10,y:13,fill:'#435b50','font-size':11},ylabel);
  node('text',{x:(left+right)/2,y:216,'text-anchor':'middle',fill:'#435b50','font-size':11},'Position from start (pixels)');
  if(!finite.length){node('text',{x:left,y:85,'font-size':12,fill:'#73847d'},'No finite samples');return;}
  let low=Math.min(...finite),high=Math.max(...finite);const pad=(high-low||Math.max(Math.abs(low)*.1,1))*.07;low-=pad;high+=pad;
  const length=result.distance.at(-1),x=d=>left+(right-left)*d/length,y=v=>bottom-(bottom-top)*(v-low)/(high-low);
  for(let i=0;i<4;i++){
    const value=low+(high-low)*i/3,py=y(value),position=length*i/3;
    node('line',{x1:left,y1:py,x2:right,y2:py,stroke:'#dce6df'});
    node('text',{x:left-6,y:py+3,'text-anchor':'end','font-size':10,fill:'#687a72'},value.toExponential(2));
    node('text',{x:x(position),y:bottom+17,'text-anchor':'middle','font-size':10,fill:'#687a72'},position.toFixed(1));
  }
  let path='',connected=false;
  values.forEach((v,i)=>{if(!Number.isFinite(v)){connected=false;return;}path+=`${connected?'L':'M'}${x(result.distance[i])},${y(v)} `;connected=true;});
  node('path',{d:path,fill:'none',stroke:'#137e6b','stroke-width':1.7});
}

globalThis.QCLLine={snapEnd,drawLine,renderPlot};
})();
