import {cp, mkdir} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import path from 'node:path';

export function backendRedirects(value) {
  let url;
  try { url = new URL(value); } catch { throw Error('Set RENDER_BACKEND_URL to the HTTPS origin of the Render API.'); }
  if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash || url.pathname !== '/') {
    throw Error('RENDER_BACKEND_URL must be an HTTPS origin without credentials, path, query or fragment.');
  }
  return [{from:'/api/*', to:`${url.origin}/api/:splat`, status:200, force:true}];
}

export async function onPreBuild({netlifyConfig, constants}) {
  netlifyConfig.redirects = [...backendRedirects(process.env.RENDER_BACKEND_URL), ...(netlifyConfig.redirects ?? [])];
  // Preserve the existing overview link while publishing tracking as the site root.
  const frontend = fileURLToPath(new URL('../../', import.meta.url));
  const target = path.join(constants.PUBLISH_DIR, 'overview');
  await mkdir(target, {recursive:true});
  for (const name of ['index.html','style.css','research.mjs']) {
    await cp(path.join(frontend, 'research', name), path.join(target, name));
  }
  for (const [source, dest] of [['paper.pdf','overview.pdf'], ['paper.tex','overview.tex']]) {
    await cp(path.join(frontend, 'research', source), path.join(target, dest));
  }
}
