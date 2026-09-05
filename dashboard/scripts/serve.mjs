/** Serve the built dashboard and proxy its API to the local Paceboard backend. */
import http from 'node:http';
import process from 'node:process';
import console from 'node:console';
import { createReadStream } from 'node:fs';
import { stat, realpath } from 'node:fs/promises';
import { dirname, resolve, sep, extname } from 'node:path';
import { fileURLToPath, URL } from 'node:url';

const root = await realpath(resolve(dirname(fileURLToPath(import.meta.url)), '../dist'));
const port = Number(process.env.PACEBOARD_WEB_PORT ?? 3001);
const apiPort = Number(process.env.PACEBOARD_API_PORT ?? 8787);
const types = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.svg': 'image/svg+xml', '.png': 'image/png', '.ico': 'image/x-icon', '.woff2': 'font/woff2' };
const server = http.createServer(async (req, res) => {
  res.setHeader('Cache-Control', 'no-store');
  res.setHeader('X-Content-Type-Options', 'nosniff');
  res.setHeader('Referrer-Policy', 'no-referrer');
  let path;
  try { path = decodeURIComponent(new URL(req.url, 'http://127.0.0.1').pathname); }
  catch { res.writeHead(400).end('Invalid URL'); return; }
  if (path.startsWith('/api/') || path === '/healthz') {
    const upstream = http.request({ hostname: '127.0.0.1', port: apiPort, path: req.url, method: req.method, headers: { ...req.headers, host: `127.0.0.1:${apiPort}` } }, response => {
      res.writeHead(response.statusCode ?? 502, { ...response.headers, 'cache-control': 'no-store' });
      response.pipe(res);
    });
    upstream.setTimeout(120_000, () => upstream.destroy(new Error('Backend timeout')));
    upstream.on('error', () => {
      if (!res.headersSent) res.writeHead(502, { 'Content-Type': 'application/json' }).end(JSON.stringify({ error: { code: 'backend_unavailable', message: 'Paceboard backend is offline. Start the local backend to reconnect your data.' } }));
      else res.destroy();
    });
    req.on('aborted', () => upstream.destroy());
    req.pipe(upstream);
    return;
  }
  if (!['GET', 'HEAD'].includes(req.method)) { res.writeHead(405, { Allow: 'GET, HEAD' }).end(); return; }
  try {
    let file = resolve(root, `.${path}`);
    if (file !== root && !file.startsWith(root + sep)) { res.writeHead(403).end(); return; }
    try {
      if (!(await stat(file)).isFile()) file = resolve(root, 'index.html');
    } catch {
      if (extname(path)) { res.writeHead(404).end('Not found'); return; }
      file = resolve(root, 'index.html');
    }
    file = await realpath(file);
    if (!file.startsWith(root + sep)) { res.writeHead(403).end(); return; }
    res.writeHead(200, { 'Content-Type': types[extname(file)] ?? 'application/octet-stream' });
    if (req.method === 'HEAD') { res.end(); return; }
    createReadStream(file).on('error', () => res.destroy()).pipe(res);
  } catch { if (!res.headersSent) res.writeHead(500); res.end('Unable to load dashboard'); }
});
server.listen(port, '127.0.0.1', () => console.log(`Paceboard live: http://127.0.0.1:${port}`));
