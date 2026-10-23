import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp, readFile, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {backendRedirects, onPreBuild} from './index.js';

test('proxy preserves API path and rejects invalid origins', () => {
  assert.deepEqual(backendRedirects('https://test.onrender.com'), [{from:'/api/*',to:'https://test.onrender.com/api/:splat',status:200,force:true}]);
  for (const invalid of [undefined,'','http://test.onrender.com','https://a/b','https://u:p@a','https://a?token=secret']) {
    assert.throws(() => backendRedirects(invalid));
  }
});

test('Netlify hook adds proxy and packages existing overview', async () => {
  const root = await mkdtemp(path.join(tmpdir(),'antidote-static-'));
  const old = process.env.RENDER_BACKEND_URL;
  try {
    process.env.RENDER_BACKEND_URL = 'https://test.onrender.com';
    const config = {redirects:[]};
    await onPreBuild({netlifyConfig:config,constants:{PUBLISH_DIR:root}});
    assert.equal(config.redirects[0].status,200);
    assert.match(await readFile(path.join(root,'overview/index.html'),'utf8'),/Project overview/);
    assert.ok((await readFile(path.join(root,'overview/overview.pdf'))).length > 0);
  } finally {
    if (old === undefined) delete process.env.RENDER_BACKEND_URL; else process.env.RENDER_BACKEND_URL = old;
    await rm(root,{recursive:true,force:true});
  }
});
