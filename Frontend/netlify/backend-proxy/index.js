import {cp, mkdir} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
import {backendRedirects} from './redirects.js';

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
