import {enhanceArcSlider} from './arc-components.mjs';

// Labels, bounds, units and explanations come from the same catalog as the API.
export function createPoisoningControls({container,onChange,onExplain}){
 const inputs=new Map();
 function values(){return Object.fromEntries([...inputs].map(([id,{input}])=>[id,Number(input.value)]));}
 function configure(controls){
  container.replaceChildren();inputs.clear();
  for(const control of controls){
   const row=document.createElement('div');row.className='poison-method';
   const title=document.createElement('button');title.type='button';title.className='method-name';title.textContent=control.label+':';title.setAttribute('aria-haspopup','dialog');
   title.addEventListener('click',()=>onExplain(control));
   const output=document.createElement('output');output.className='method-value';output.htmlFor=control.id;
   const range=document.createElement('div');range.className='method-range';
   const track=document.createElement('div');track.className='scrubber';
   const thumb=document.createElement('span');thumb.className='timeline-thumb';thumb.setAttribute('aria-hidden','true');
   const input=document.createElement('input');input.type='range';input.id=control.id;input.min='0';input.max=String(control.maximum);input.step='1';input.value='0';input.setAttribute('aria-label',`${control.label}, ${control.unit==='min'?'minutes':control.id.startsWith('missing_')||control.id==='position_jump'?'percent of reports':'percent strength'}`);
   function sync(){
    const value=Number(input.value),text=control.unit==='min'?`${value} min`:`${value}%`;
    output.textContent=text;input.setAttribute('aria-valuetext',text);thumb.style.left=value/control.maximum*100+'%';track.style.setProperty('--progress',thumb.style.left);
   }
   input.addEventListener('input',()=>{sync();onChange(values());});
   inputs.set(control.id,{input,output});sync();track.append(input,thumb);
   range.append(document.createTextNode('0'),track,document.createTextNode(control.maximum+(control.unit==='min'?' min':'')));
   row.append(title,output,range);container.append(row);enhanceArcSlider(input);
  }
  return values();
 }
 return {configure,values};
}
