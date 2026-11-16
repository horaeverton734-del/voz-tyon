const http = require('http');
const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');

const PORT = process.env.PORT || 8090;
const DAEMON_PORT = process.env.VOICE_DAEMON_PORT || 8091;

// Se estivermos no Windows local, sobe o daemon de voz do cook45 automaticamente
let daemonProc = null;
function startLocalVoiceDaemon() {
  if (process.platform !== 'win32') return;
  const daemonPath = path.join(__dirname, 'cook45_voice_daemon.py');
  if (!fs.existsSync(daemonPath)) return;

  // Tenta Python314 (onde o pip instalou edge-tts) ou python padrão
  const py314 = 'C:\\Users\\SEJUC\\AppData\\Local\\Programs\\Python\\Python314\\python.exe';
  const pyBin = fs.existsSync(py314) ? py314 : 'python';

  console.log(`[SERVE] Iniciando motor de voz cook45 com: ${pyBin}`);
  daemonProc = spawn(pyBin, [daemonPath], {
    cwd: __dirname,
    env: { ...process.env, VOICE_DAEMON_PORT: String(DAEMON_PORT), PYTHONIOENCODING: 'utf-8' },
    stdio: 'inherit'
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

function proxyToDaemon(req, res) {
  const options = {
    hostname: '127.0.0.1',
    port: DAEMON_PORT,
    path: req.url,
    method: req.method,
    headers: req.headers
  };

  const proxyReq = http.request(options, (proxyRes) => {
    res.writeHead(proxyRes.statusCode, proxyRes.headers);
    proxyRes.pipe(res, { end: true });
  });

  proxyReq.on('error', () => {
    // Fallback quando roda em nuvem (Render) sem o daemon local winmm
    res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
    res.end(JSON.stringify({
      cloud_mode: true,
      state: {
        enabled: true,
        auto_read_chat: true,
        clipboard_watch: false,
        voice: 'pt-BR-AntonioNeural',
        rate: '+12%',
        pitch: '-6Hz',
        volume: 100,
        speaking: false,
        current_text: '',
        engine: 'Web Speech Neural / Browser Fallback',
        history: []
      },
      voices: [
        { id: 'pt-BR-AntonioNeural', name: 'Cook45 Padrão (Antonio Neural - Firme/Direto)', pitch: '-6Hz', rate: '+12%' },
        { id: 'pt-BR-DonatoNeural', name: 'Cook45 Veterano (Donato Neural - Grave/Sênior)', pitch: '-8Hz', rate: '+8%' },
        { id: 'pt-BR-HumbertoNeural', name: 'Cook45 Tático (Humberto Neural - Seco/Rápido)', pitch: '-4Hz', rate: '+15%' },
        { id: 'pt-BR-FabioNeural', name: 'Cook45 Estúdio (Fabio Neural - Claro/Natural)', pitch: '-3Hz', rate: '+10%' }
      ]
    }));
  });

  req.pipe(proxyReq, { end: true });
}

const server = http.createServer((req, res) => {
  if (req.url.startsWith('/api/') || req.url.startsWith('/audio/')) {
    return proxyToDaemon(req, res);
  }

  let filePath = req.url === '/' ? '/index.html' : req.url.split('?')[0];
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
    res.writeHead(200, { 'Content-Type': MIME_TYPES[ext] || 'application/octet-stream' });
    res.end(content);
  });
});

server.listen(PORT, () => {
  console.log(`[TYON-V45] Painel do Dispositivo de Voz cook45 rodando em http://localhost:${PORT}`);
});
