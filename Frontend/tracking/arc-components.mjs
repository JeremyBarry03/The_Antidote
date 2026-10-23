/* Browser-native adaptations of Arc UI's free components.
 * Source and MIT license: THIRD_PARTY_NOTICES.md. */
const reduced=()=>matchMedia('(prefers-reduced-motion: reduce)').matches;
const finePointer=()=>matchMedia('(hover: hover) and (pointer: fine)').matches;
const clamp=(value,min,max)=>Math.max(min,Math.min(Math.max(min,max),value));
const check='<svg viewBox="0 0 16 16" aria-hidden="true"><path d="m3 8 3 3 7-7"/></svg>';

// Arc's two equal-command polygons interpolate from a triangle to pause bars.
const playPaths=['M7 4.5 L12 7.42 L12 16.58 L7 19.5 Z','M12 7.42 L19.5 11.8 L19.5 12.2 L12 16.58 Z'];
const pausePaths=['M7 5 L9 5 L9 19 L7 19 Z','M15 5 L17 5 L17 19 L15 19 Z'];
export function setArcPlayIcon(button,playing){
 let icon=button.querySelector('.arc-play-icon');
 if(!icon){
  icon=document.createElementNS('http://www.w3.org/2000/svg','svg');icon.setAttribute('viewBox','0 0 24 24');icon.setAttribute('aria-hidden','true');icon.classList.add('arc-play-icon');
  for(const d of playing?pausePaths:playPaths){const path=document.createElementNS(icon.namespaceURI,'path');path.setAttribute('d',d);icon.append(path);}
  button.replaceChildren(icon);
 }
 [...icon.children].forEach((path,index)=>path.style.d=`path('${(playing?pausePaths:playPaths)[index]}')`);
 button.setAttribute('aria-pressed',String(playing));
}

export function enhanceArcSlider(input){
 const root=input.closest('.scrubber');root.classList.add('arc-slider');
 // Values stay in the existing inline output; dragging never opens a bubble.
 input.addEventListener('pointerdown',()=>root.setAttribute('data-dragging',''));
 const release=()=>root.removeAttribute('data-dragging');
 window.addEventListener('pointerup',release);window.addEventListener('pointercancel',release);
}

export function createArcSelect({trigger,menu,label,getValue,onChange}){
  const root=trigger.parentElement,options=[...menu.querySelectorAll('[role=option]')];
  const value=option=>option.dataset.model;
  const highlight=document.createElement('span');highlight.className='arc-menu-highlight';highlight.setAttribute('aria-hidden','true');menu.prepend(highlight);
  let active=0,typeBuffer='',typeTimer;
  for(const option of options){
    option.classList.add('arc-option');
    const text=document.createElement('span');text.className='arc-option-label';text.textContent=option.textContent;
    const indicator=document.createElement('span');indicator.className='arc-option-check';indicator.innerHTML=check;
    option.replaceChildren(text,indicator);
  }
  function moveHighlight(index,keyboard=false){
    active=(index+options.length)%options.length;
    const option=options[active];menu.dataset.input=keyboard?'keyboard':'pointer';
    highlight.style.height=option.offsetHeight+'px';highlight.style.transform=`translateY(${option.offsetTop}px)`;highlight.style.opacity='1';
    for(const item of options)item.toggleAttribute('data-highlighted',item===option);
  }
  function position(){
    if(menu.hidden)return;
    const rect=trigger.getBoundingClientRect(),width=menu.offsetWidth,height=menu.offsetHeight;
    const below=innerHeight-rect.bottom-12,above=rect.top-12;
    const side=height>below&&above>below?'top':'bottom';
    menu.dataset.side=side;menu.style.left=clamp(rect.right-width,12,innerWidth-width-12)+'px';
    menu.style.top=(side==='top'?Math.max(12,rect.top-height-6):rect.bottom+6)+'px';
    menu.style.maxHeight=Math.max(40,side==='top'?above-6:below-6)+'px';
  }
  function close(restore=false){
    clearTimeout(typeTimer);typeBuffer='';
    menu.hidden=true;trigger.setAttribute('aria-expanded','false');trigger.dataset.state='closed';
    if(restore)trigger.focus({preventScroll:true});
  }
  function open(direction=0){
    menu.hidden=false;trigger.setAttribute('aria-expanded','true');trigger.dataset.state='open';
    document.dispatchEvent(new Event('arc-overlay-open'));position();
    const selected=Math.max(0,options.findIndex(option=>value(option)===getValue()));
    moveHighlight(selected+direction,true);options[active].focus({preventScroll:true});
  }
  function choose(option){
    const previous=options.findIndex(item=>value(item)===getValue()),next=options.indexOf(option);
    onChange(value(option));
    for(const item of options)item.setAttribute('aria-selected',String(item===option));
    label.textContent=option.querySelector('.arc-option-label').textContent;
    trigger.setAttribute('aria-label',`Model: ${label.textContent}`);close(true);
    label.getAnimations().forEach(animation=>animation.cancel());
    if(!reduced()&&next!==previous)label.animate([{opacity:0,transform:`translateY(${(next>previous?1:-1)*.35}em)`},{opacity:1,transform:'translateY(0)'}],{duration:200,easing:'cubic-bezier(.22,1,.36,1)'});
  }
  function typeahead(key){
    clearTimeout(typeTimer);typeBuffer+=key.toLowerCase();typeTimer=setTimeout(()=>typeBuffer='',650);
    const index=options.findIndex((option,index)=>index!==active&&option.textContent.toLowerCase().startsWith(typeBuffer));
    const match=index>=0?index:options.findIndex(option=>option.textContent.toLowerCase().startsWith(key.toLowerCase()));
    if(match>=0){moveHighlight(match,true);options[active].focus({preventScroll:true});}
  }
  trigger.addEventListener('click',()=>menu.hidden?open():close());
  trigger.addEventListener('keydown',event=>{
    if(['ArrowDown','ArrowUp'].includes(event.key)){event.preventDefault();open(event.key==='ArrowUp'?-1:0);}
    else if(event.key==='Enter'||event.key===' '){event.preventDefault();menu.hidden?open():close();}
    else if(event.key.length===1&&/\S/.test(event.key)&&!event.metaKey&&!event.ctrlKey&&!event.altKey){event.preventDefault();open();typeahead(event.key);}
  });
  menu.addEventListener('keydown',event=>{
    const next=event.key==='ArrowDown'?active+1:event.key==='ArrowUp'?active-1:event.key==='Home'?0:event.key==='End'?options.length-1:null;
    if(next!=null){event.preventDefault();moveHighlight(next,true);options[active].focus({preventScroll:true});}
    else if(event.key==='Escape'){event.preventDefault();event.stopPropagation();close(true);}
    else if(event.key==='Tab'){close(true);}
    else if(event.key==='Enter'||event.key===' '){event.preventDefault();choose(options[active]);}
    else if(event.key.length===1&&/\S/.test(event.key)&&!event.metaKey&&!event.ctrlKey&&!event.altKey){event.preventDefault();typeahead(event.key);}
  });
  options.forEach((option,index)=>{
    option.addEventListener('click',()=>choose(option));
    option.addEventListener('pointerenter',event=>{if(event.pointerType!=='touch')moveHighlight(index);});
    option.addEventListener('focus',()=>moveHighlight(index,menu.dataset.input==='keyboard'));
  });
  document.addEventListener('pointerdown',event=>{if(!root.contains(event.target))close();});
  window.addEventListener('resize',position);
  window.addEventListener('scroll',event=>{if(!menu.contains(event.target))close();},true);
  return {open,close};
}

export function enhanceArcGroup(root){
  root.classList.add('arc-button-group');root.setAttribute('role','group');
  const buttons=[...root.querySelectorAll(':scope > button')];
  const highlight=document.createElement('span');highlight.className='arc-group-highlight';highlight.setAttribute('aria-hidden','true');root.prepend(highlight);
  function show(button,keyboard=false){
    if(!button||button.disabled)return;
    const a=button.getBoundingClientRect(),b=root.getBoundingClientRect();
    root.dataset.input=keyboard?'keyboard':'pointer';highlight.style.width=a.width+'px';highlight.style.height=a.height+'px';
    highlight.style.transform=`translate(${a.left-b.left}px,${a.top-b.top}px)`;highlight.style.opacity='1';
    const selected=buttons.indexOf(button);buttons.forEach((button,index)=>button.toggleAttribute('data-quiet',index===selected||index===selected+1));
  }
  function hide(){highlight.style.opacity='0';buttons.forEach(button=>button.removeAttribute('data-quiet'));}
  for(const button of buttons){
    button.addEventListener('pointerenter',event=>{if(event.pointerType!=='touch')show(button);});
    button.addEventListener('pointerdown',()=>{show(button);root.dataset.pressed='true';});
    button.addEventListener('focus',()=>{if(button.matches(':focus-visible'))show(button,true);});
  }
  root.addEventListener('pointerleave',()=>{if(!root.querySelector(':focus-visible'))hide();});
  root.addEventListener('focusout',event=>{if(!root.contains(event.relatedTarget))hide();});
  window.addEventListener('pointerup',()=>{delete root.dataset.pressed;if(!finePointer())hide();});
  root.addEventListener('keydown',event=>{
    const enabled=buttons.filter(button=>!button.disabled),index=enabled.indexOf(document.activeElement);
    const next=event.key==='ArrowRight'?index+1:event.key==='ArrowLeft'?index-1:event.key==='Home'?0:event.key==='End'?enabled.length-1:null;
    if(index>=0&&next!=null){event.preventDefault();const button=enabled[(next+enabled.length)%enabled.length];button.focus();show(button,true);}
  });
}

export function enhanceArcDisclosure(details,{fixed=false}={}){
  const trigger=details.querySelector('summary'),panel=document.createElement('div');
  panel.id='poison-content';panel.className='arc-disclosure-panel';
  for(const child of [...details.children])if(child!==trigger)panel.append(child);
  details.append(panel);trigger.setAttribute('aria-controls',panel.id);
  let expanded=details.open,animation;
  function setOpen(next){
    const from=panel.getBoundingClientRect().height,opacity=getComputedStyle(panel).opacity;
    animation?.cancel();expanded=next;details.dataset.expanded=String(next);
    trigger.setAttribute('aria-expanded',String(next));panel.inert=!next;
    if(!next&&panel.contains(document.activeElement))trigger.focus();
    if(fixed){details.open=next;panel.style.height=next?'':'0px';panel.style.opacity=next?'1':'0';return;}
    details.open=true;panel.style.height=next?'auto':'0px';panel.style.opacity=next?'1':'0';
    const to=next?panel.scrollHeight:0;
    if(reduced()){details.open=next;return;}
    animation=panel.animate([{height:from+'px',opacity},{height:to+'px',opacity:next?1:0}],{duration:260,easing:'cubic-bezier(.22,1,.36,1)'});
    const current=animation;
    animation.onfinish=()=>{if(animation===current){details.open=expanded;animation=null;}};
  }
  details.dataset.expanded=String(expanded);trigger.setAttribute('aria-expanded',String(expanded));
  panel.inert=!expanded;panel.style.height=expanded?(fixed?'':'auto'):'0px';panel.style.opacity=expanded?'1':'0';
  trigger.addEventListener('click',event=>{event.preventDefault();setOpen(!expanded);});
  details.addEventListener('keydown',event=>{if(event.key==='Escape'&&expanded){event.preventDefault();event.stopPropagation();setOpen(false);trigger.focus();}});
  return {setOpen};
}

export function enhanceArcDialog(dialog){
  dialog.addEventListener('keydown',event=>{
    if(event.key!=='Tab')return;
    const controls=[...dialog.querySelectorAll('button:not(:disabled),a[href],input:not(:disabled),select:not(:disabled),textarea:not(:disabled),[tabindex="0"]')].filter(control=>control.getClientRects().length);
    const first=controls[0],last=controls.at(-1);
    if(!first){event.preventDefault();return;}
    if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}
    else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}
  });
}

export function setupArcTooltips(){
  const tooltip=document.createElement('div');tooltip.id='arc-tooltip';tooltip.className='arc-tooltip';tooltip.setAttribute('role','tooltip');tooltip.hidden=true;document.body.append(tooltip);
  let active,timer,lastShown=0;
  function hide(){
    clearTimeout(timer);tooltip.hidden=true;
    if(active){const ids=(active.getAttribute('aria-describedby')||'').split(' ').filter(id=>id&&id!==tooltip.id);if(ids.length)active.setAttribute('aria-describedby',ids.join(' '));else active.removeAttribute('aria-describedby');}
    active=null;
  }
  function schedule(target,keyboard=false){
    hide();if(target.disabled)return;active=target;
    timer=setTimeout(()=>{
      if(active!==target||!target.isConnected)return;
      tooltip.textContent=target.dataset.arcTooltip;tooltip.hidden=false;
      const rect=target.getBoundingClientRect(),box=tooltip.getBoundingClientRect();
      const top=rect.top-box.height-7,bottom=top<12;
      tooltip.dataset.side=bottom?'bottom':'top';tooltip.style.left=clamp(rect.left+(rect.width-box.width)/2,12,innerWidth-box.width-12)+'px';
      tooltip.style.top=(bottom?rect.bottom+7:top)+'px';
      const ids=(target.getAttribute('aria-describedby')||'').split(' ').filter(Boolean);target.setAttribute('aria-describedby',[...ids,tooltip.id].join(' '));lastShown=performance.now();
    },keyboard||performance.now()-lastShown<900?0:350);
  }
  document.addEventListener('pointerover',event=>{const target=event.target.closest('[data-arc-tooltip]');if(target&&event.pointerType!=='touch'&&finePointer()&&!target.contains(event.relatedTarget))schedule(target);});
  document.addEventListener('pointerout',event=>{if(active&&active.contains(event.target)&&!active.contains(event.relatedTarget))hide();});
  document.addEventListener('focusin',event=>{const target=event.target.closest('[data-arc-tooltip]');if(target&&target.matches(':focus-visible'))schedule(target,true);});
  document.addEventListener('focusout',event=>{if(event.target===active)hide();});
  document.addEventListener('pointerdown',hide);document.addEventListener('click',hide);
  document.addEventListener('keydown',event=>{if(event.key==='Escape')hide();});
  document.addEventListener('arc-overlay-open',hide);window.addEventListener('scroll',hide,true);window.addEventListener('resize',hide);
}
