export function backendRedirects(value) {
  let url;
  try { url = new URL(value); } catch { throw Error('Set RENDER_BACKEND_URL to the HTTPS origin of the Render API.'); }
  if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash || url.pathname !== '/') {
    throw Error('RENDER_BACKEND_URL must be an HTTPS origin without credentials, path, query or fragment.');
  }
  return [{from:'/api/*', to:`${url.origin}/api/:splat`, status:200, force:true}];
}
