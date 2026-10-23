const STORAGE_KEY='antidote-appearance';

/** Neutral-only light preview. The map API repaints known basemap layers;
 * colored data is never inverted through a canvas or page filter. */
export function setupAppearance({button=document.getElementById('invert'),onChange}={}){
  if(!button)throw new Error('The appearance control is missing.');
  const root=document.documentElement;
  let theme='dark';
  try{if(localStorage.getItem(STORAGE_KEY)==='light')theme='light';}catch{}
  const apply=(next,{persist=true}={})=>{
    theme=next==='light'?'light':'dark';
    root.dataset.theme=theme;
    const label=theme==='light'?'Switch to dark view':'Switch to light view';
    button.textContent='Invert';
    button.setAttribute('aria-pressed',String(theme==='light'));
    button.setAttribute('aria-label',label);
    button.dataset.arcTooltip=label;
    button.removeAttribute('title');
    if(persist)try{localStorage.setItem(STORAGE_KEY,theme);}catch{}
    window.coastalPreview?.setTheme(theme);
    onChange?.(theme);
    window.dispatchEvent(new CustomEvent('appearance-change',{detail:{theme}}));
  };
  const toggle=()=>apply(theme==='light'?'dark':'light');
  const syncMap=()=>window.coastalPreview?.setTheme(theme);
  button.addEventListener('click',toggle);
  window.addEventListener('coastal-ready',syncMap);
  apply(theme,{persist:false});
  return {getTheme:()=>theme,setTheme:next=>apply(next),destroy:()=>{
    button.removeEventListener('click',toggle);
    window.removeEventListener('coastal-ready',syncMap);
  }};
}
