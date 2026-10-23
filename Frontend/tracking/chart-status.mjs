// Visible loading states show real counts; the explanation remains available to
// assistive technology. Error and empty-state explanations stay visible.
export function setChartStatus(loading,state){
 const message=loading.querySelector('span');
 if(state.status==='loading'){
  const known=Number.isFinite(state.completed)&&Number.isFinite(state.total)&&state.total>0;
  message.textContent=known?`${state.completed.toLocaleString()} / ${state.total.toLocaleString()}`:'0%';
  message.setAttribute('aria-hidden','true');
  loading.setAttribute('aria-label',state.message||'Loading graph');
 }else{
  message.textContent=state.message;
  message.removeAttribute('aria-hidden');
  loading.removeAttribute('aria-label');
 }
}
