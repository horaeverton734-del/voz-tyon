const http = require('http');
const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');

const PORT = process.env.PORT || 18090;
const HOST = process.env.PORT ? '0.0.0.0' : '127.0.0.1';
const DAEMON_PORT = process.env.VOICE_DAEMON_PORT || 8091;

// Estado em memória na nuvem (Render) para receber sync do PC do clack ou comandos web
const CLOUD_STATE = {
  enabled: true,
  auto_read_chat: true,
  auto_read_kilo: true,
  clipboard_watch: false,
  voice: 'pt-BR-AntonioNeural',
  rate: '+10%',
  pitch: '-8Hz',
  kilo_voice: 'en-US-BrianMultilingualNeural',
  kilo_rate: '+12%',
  kilo_pitch: '-2Hz',
  volume: 100,
  speaking: false,
  current_text: '',
  engine: 'Hybrid Cloud + Local Bridge (127.0.0.1:8091)',
  history: []
};

let daemonProc = null;
function startLocalVoiceDaemon() {
  if (process.platform !== 'win32') return;
  const daemonPath = path.join(__dirname, 'cook45_voice_daemon.py');
  if (!fs.existsSync(daemonPath)) return;

  const py314w = 'C:\\Users\\SEJUC\\AppData\\Local\\Programs\\Python\\Python314\\pythonw.exe';
  const py314 = 'C:\\Users\\SEJUC\\AppData\\Local\\Programs\\Python\\Python314\\python.exe';
  const pyBin = fs.existsSync(py314w) ? py314w : (fs.existsSync(py314) ? py314 : 'pythonw');

  console.log(`[SERVE] Iniciando motor de voz cook45 com: ${pyBin}`);
  daemonProc = spawn(pyBin, [daemonPath], {
    cwd: __dirname,
    env: { ...process.env, VOICE_DAEMON_PORT: String(DAEMON_PORT), PYTHONIOENCODING: 'utf-8' },
    windowsHide: true,
    stdio: 'ignore'
  });

  daemonProc.on('exit', (code) => {
    console.log(`[SERVE] Daemon de voz encerrou (code ${code}). Reiniciando em 3s...`);
    setTimeout(startLocalVoiceDaemon, 3000);
  });
}

startLocalVoiceDaemon();

const MIME_TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.mp3': 'audio/mpeg',
  '.wav': 'audio/wav',
  '.svg': 'image/svg+xml',
  '.png': 'image/png'
};

function setCors(res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Private-Network', 'true');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Access-Control-Request-Private-Network');
}

function handleCloudFallback(req, res, bodyStr) {
  setCors(res);
  let payload = {};
  try { payload = JSON.parse(bodyStr || '{}'); } catch (e) {}

  if (req.url === '/api/sync' && req.method === 'POST') {
    if (payload.state) {
      Object.assign(CLOUD_STATE, payload.state);
    }
    res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
    return res.end(JSON.stringify({ ok: true }));
  }

  if (req.url === '/api/config' && req.method === 'POST') {
    Object.assign(CLOUD_STATE, payload);
    res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
    return res.end(JSON.stringify({ ok: true, state: CLOUD_STATE }));
  }

  if (req.url === '/api/speak' && req.method === 'POST') {
    const txt = (payload.text || '').trim();
    if (txt) {
      CLOUD_STATE.current_text = txt;
      CLOUD_STATE.history.unshift({
        id: Date.now().toString(36),
        timestamp: new Date().toLocaleTimeString('pt-BR'),
        source: payload.source || 'Nuvem Render',
        text: txt,
        voice: CLOUD_STATE.voice
      });
      CLOUD_STATE.history = CLOUD_STATE.history.slice(0, 25);
    }
    res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
    return res.end(JSON.stringify({ ok: true, cloud_speak: txt }));
  }

  res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
  res.end(JSON.stringify({
    cloud_mode: true,
    state: CLOUD_STATE,
    voices: [
      { id: 'pt-BR-AntonioNeural', name: 'Cook45 Veterano (Antonio PT-BR - Grave -8Hz)', pitch: '-8Hz', rate: '+10%' },
      { id: 'en-US-BrianMultilingualNeural', name: 'Niko Masculino (Brian Neural - Outro Homem)', pitch: '-2Hz', rate: '+12%' },
      { id: 'en-US-AndrewMultilingualNeural', name: 'Andrew Masculino (Copilot Neural - Firme)', pitch: '-4Hz', rate: '+10%' },
      { id: 'pt-PT-DuarteNeural', name: 'Duarte Masculino (Neural Luso)', pitch: '-3Hz', rate: '+12%' }
    ],
    queue_size: 0
  }));
}

function proxyToDaemon(req, res) {
  let bodyChunks = [];
  req.on('data', chunk => bodyChunks.push(chunk));
  req.on('end', () => {
    const bodyBuffer = Buffer.concat(bodyChunks);
    const bodyStr = bodyBuffer.toString('utf-8');

    const options = {
      hostname: '127.0.0.1',
      port: DAEMON_PORT,
      path: req.url,
      method: req.method,
      headers: req.headers
    };

    const proxyReq = http.request(options, (proxyRes) => {
      setCors(res);
      res.writeHead(proxyRes.statusCode, proxyRes.headers);
      proxyRes.pipe(res, { end: true });
    });

    proxyReq.on('error', () => {
      handleCloudFallback(req, res, bodyStr);
    });

    if (bodyBuffer.length > 0) {
      proxyReq.write(bodyBuffer);
    }
    proxyReq.end();
  });
}

const server = http.createServer((req, res) => {
  if (req.method === 'OPTIONS') {
    setCors(res);
    res.writeHead(200);
    return res.end();
  }

  if (req.url.startsWith('/api/') || req.url.startsWith('/audio/')) {
    return proxyToDaemon(req, res);
  }

  const cleanUrl = req.url.split('?')[0];
  let filePath = (cleanUrl === '/' || cleanUrl === '') ? '/index.html' : cleanUrl;
  const fullPath = path.join(__dirname, filePath);

  if (!fullPath.startsWith(__dirname)) {
    res.writeHead(403);
    return res.end('Forbidden');
  }

  fs.readFile(fullPath, (err, content) => {
    if (err) {
      res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
      return res.end('404 Not Found');
    }
    const ext = path.extname(fullPath).toLowerCase();
    setCors(res);
    res.writeHead(200, { 'Content-Type': MIME_TYPES[ext] || 'application/octet-stream' });
    res.end(content);
  });
});

server.on('error', (err) => {
  if (err.code === 'EADDRINUSE') {
    console.log(`[TYON-V45] Porta ${PORT} já está ativa em outra instância. Encerrando duplicata.`);
    process.exit(0);
  }
  throw err;
});

server.listen(PORT, HOST, () => {
  console.log(`[TYON-V45] Painel do Dispositivo de Voz cook45 rodando em http://${HOST}:${PORT}`);
});
