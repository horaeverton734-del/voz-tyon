import os
import sys
import json
import time
import glob
import re
import ctypes
import asyncio
import hashlib
import sqlite3
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# Diretórios base
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AUDIO_DIR = os.path.join(BASE_DIR, "audio_cache")
OFFLINE_MODELS_DIR = os.path.join(BASE_DIR, "offline_models")
BRAIN_DIR = os.path.expanduser(r"~\.gemini\antigravity\brain")
KILO_DB_PATH = os.path.expanduser(r"~\.local\share\kilo\kilo.db")
STATE_FILE = os.path.join(BASE_DIR, "device_state.json")

os.makedirs(AUDIO_DIR, exist_ok=True)
os.makedirs(OFFLINE_MODELS_DIR, exist_ok=True)

# Estado global do Dispositivo de Voz cook45 + Niko (Kilo Code) + Agente PC
DEVICE_STATE = {
    "enabled": True,
    "offline_mode": False,
    "pc_control": True,
    "auto_read_chat": True,
    "auto_read_kilo": True,
    "clipboard_watch": False,
    "voice": "pt-BR-AntonioNeural",
    "offline_voice": "pt_BR-faber-medium.onnx",
    "rate": "+3%",
    "pitch": "-1Hz",
    "kilo_voice": "en-US-BrianMultilingualNeural",
    "offline_kilo_voice": "pt_BR-cadu-medium.onnx",
    "kilo_rate": "+4%",
    "kilo_pitch": "+0Hz",
    "volume": 100,
    "speaking": False,
    "recording": False,
    "last_transcript": "",
    "current_text": "",
    "last_audio_url": "",
    "last_step_key": "",
    "history": [],
    "engine": "Piper ONNX + Edge-TTS (Híbrido)"
}

def load_persisted_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            for k in (
                "enabled", "offline_mode", "pc_control", "auto_read_chat", "auto_read_kilo", "clipboard_watch",
                "voice", "offline_voice", "rate", "pitch",
                "kilo_voice", "offline_kilo_voice", "kilo_rate", "kilo_pitch", "volume"
            ):
                if k in saved:
                    DEVICE_STATE[k] = saved[k]
        except Exception:
            pass

def save_persisted_state():
    try:
        data = {
            k: DEVICE_STATE[k] for k in (
                "enabled", "offline_mode", "pc_control", "auto_read_chat", "auto_read_kilo", "clipboard_watch",
                "voice", "offline_voice", "rate", "pitch",
                "kilo_voice", "offline_kilo_voice", "kilo_rate", "kilo_pitch", "volume"
            )
        }
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

load_persisted_state()

AVAILABLE_VOICES = [
    {"id": "pt-BR-AntonioNeural", "name": "Cook45 Veterano (Antonio PT-BR - Grave -8Hz)", "pitch": "-8Hz", "rate": "+10%"},
    {"id": "en-US-BrianMultilingualNeural", "name": "Niko Masculino (Brian Neural - Outro Homem)", "pitch": "-2Hz", "rate": "+12%"},
    {"id": "en-US-AndrewMultilingualNeural", "name": "Andrew Masculino (Copilot Neural - Firme)", "pitch": "-4Hz", "rate": "+10%"},
    {"id": "pt-PT-DuarteNeural", "name": "Duarte Masculino (Neural Luso)", "pitch": "-3Hz", "rate": "+12%"},
    {"id": "fr-FR-RemyMultilingualNeural", "name": "Remy Masculino (Multilingual Neural)", "pitch": "-3Hz", "rate": "+10%"},
    {"id": "it-IT-GiuseppeMultilingualNeural", "name": "Giuseppe Masculino (Multilingual Neural)", "pitch": "-4Hz", "rate": "+10%"}
]

SPEECH_QUEUE = []
QUEUE_LOCK = threading.Lock()
STOP_REQUESTED = False
LAST_UI_HEARTBEAT = 0.0

def has_active_player() -> bool:
    """So permite reproducao automatica se houver um Mini-Player aberto na tela (heartbeat nos ultimos 5s)."""
    return (time.time() - LAST_UI_HEARTBEAT) <= 5.0

# Win32 MCI API direto no kernel/subsistema multimídia (winmm.dll)
winmm = ctypes.windll.winmm
user32 = ctypes.windll.user32

def pin_mini_player_window(pinned: bool = True, move_to_side: bool = False) -> int:
    """Localiza a janela do Mini Player via user32.dll e aplica HWND_TOPMOST (Sempre no Topo)."""
    HWND_TOPMOST = -1
    HWND_NOTOPMOST = -2
    SWP_NOMOVE = 0x0002
    SWP_NOSIZE = 0x0001
    SWP_SHOWWINDOW = 0x0040

    found_hwnds = []
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def enum_cb(hwnd, lparam):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                title = buf.value
                if "MINI PLAYER COOK45" in title or "TYON-V45 // MINI" in title:
                    found_hwnds.append(hwnd)
        return True

    cb = WNDENUMPROC(enum_cb)
    user32.EnumWindows(cb, 0)

    z_order = HWND_TOPMOST if pinned else HWND_NOTOPMOST
    for hwnd in found_hwnds:
        if move_to_side:
            screen_w = user32.GetSystemMetrics(0)
            width, height = 355, 535
            x = max(10, screen_w - width - 16)
            y = 70
            user32.SetWindowPos(hwnd, z_order, x, y, width, height, SWP_SHOWWINDOW)
        else:
            user32.SetWindowPos(hwnd, z_order, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)

    return len(found_hwnds)

def mci_send(cmd: str) -> str:
    buf = ctypes.create_unicode_buffer(512)
    err = winmm.mciSendStringW(cmd, buf, 512, 0)
    return buf.value

def stop_audio_playback():
    global STOP_REQUESTED
    STOP_REQUESTED = True
    try:
        mci_send("stop cook45_voice")
        mci_send("close cook45_voice")
        mci_send("stop cook45_music")
        mci_send("close cook45_music")
    except Exception:
        pass
    DEVICE_STATE["speaking"] = False

def play_music_winmm(filepath: str, volume: int = 85):
    """Toca musica direto via winmm.dll (alias separado cook45_music, zero lag e sem depender de app UWP)."""
    abs_path = os.path.abspath(filepath)
    mci_send("stop cook45_music")
    mci_send("close cook45_music")
    res = winmm.mciSendStringW(f'open "{abs_path}" type mpegvideo alias cook45_music', None, 0, 0)
    if res != 0:
        return False
    mci_vol = max(0, min(1000, int(volume * 10)))
    mci_send(f"setaudio cook45_music volume to {mci_vol}")
    mci_send("play cook45_music")
    return True

def play_mp3_winmm(filepath: str, volume: int = 100):
    """Toca arquivo MP3 ou WAV nativamente usando winmm.dll na thread de áudio."""
    global STOP_REQUESTED
    STOP_REQUESTED = False
    try:
        mci_send("close cook45_voice")
        abs_path = os.path.abspath(filepath)
        media_type = "waveaudio" if abs_path.lower().endswith(".wav") else "mpegvideo"
        res = winmm.mciSendStringW(f'open "{abs_path}" type {media_type} alias cook45_voice', None, 0, 0)
        if res != 0 and media_type == "waveaudio":
            res = winmm.mciSendStringW(f'open "{abs_path}" type mpegvideo alias cook45_voice', None, 0, 0)
        if res != 0:
            return False
        # Volume no MCI vai de 0 a 1000 (waveaudio usa setaudio quando suportado)
        mci_vol = max(0, min(1000, int(volume * 10)))
        mci_send(f"setaudio cook45_voice volume to {mci_vol}")
        mci_send("play cook45_voice")
        
        # Aguarda término ou interrupção imediata se o usuário desligar o Play
        while not STOP_REQUESTED and DEVICE_STATE["enabled"]:
            status = mci_send("status cook45_voice mode")
            if status not in ("playing", "seeking"):
                break
            time.sleep(0.06)
        mci_send("stop cook45_voice")
        mci_send("close cook45_voice")
        return True
    except Exception as e:
        print(f"[WARN] Erro winmm: {e}")
        return False

def clean_text_for_speech(raw_text: str) -> str:
    """Limpa markdown, URLs gigantes e blocos de código para leitura fluida da voz do cook45."""
    if not raw_text:
        return ""
    text = raw_text

    # Substitui blocos de código extensos por aviso falado curto
    def replace_code_block(match):
        lang = (match.group(1) or "").strip()
        code_lines = match.group(2).strip().splitlines()
        if len(code_lines) > 4:
            return f" ... Bloco de código {lang} gerado na tela. ... "
        return " " + " ".join(code_lines) + " "

    text = re.sub(r"```([a-zA-Z0-9_-]*)\n(.*?)```", replace_code_block, text, flags=re.DOTALL)

    # Remove tags HTML/custom cards
    text = re.sub(r"<[^>]+>", " ", text)

    # Converte links markdown [texto](url) -> texto
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)

    # Remove URLs cruas http/https/file
    text = re.sub(r"(?:https?|file)://\S+", " link na tela ", text)

    # Simplifica caminhos Windows longos (ex: C:\Users\SEJUC\...)
    def simplify_path(m):
        p = m.group(0)
        base = os.path.basename(p.rstrip("\\/"))
        return f" {base} " if base else " pasta "

    text = re.sub(r"[A-Za-z]:\\[\\\S]+", simplify_path, text)

    # Remove formatação markdown (**, __, `, #, >, |, ---)
    text = re.sub(r"[*_`#~|>]+", " ", text)
    text = re.sub(r"-{2,}", " ", text)
    text = re.sub(r"━+", " ", text)

    # Remove emojis e símbolos decorativos que causam engasgos ou leitura robótica
    text = re.sub(r"[\U00010000-\U0010ffff\u2600-\u27bf\ufe0f]", " ", text)

    # Ajustes de pronúncia técnica PT-BR
    replacements = {
        r"\bcook45\b": "cúk quarenta e cinco",
        r"\bCook45\b": "Cúk quarenta e cinco",
        r"\bCOOK45\b": "Cúk quarenta e cinco",
        r"\bclack\b": "cléck",
        r"\bClack\b": "Cléck",
        r"\bTTS\b": "Tê Tê Ésse",
        r"\bGPU\b": "Gê Pê U",
        r"\bCPU\b": "Cê Pê U",
        r"\bAPI\b": "A Pê I",
        r"\bHUD\b": "rãd",
        r"\bDLL\b": "Dê Éle Éle",
        r"\bJSONL\b": "djêison éle",
        r"\bJSON\b": "djêison",
        r"\bREADME\b": "rídmi",
    }
    for pattern, repl in replacements.items():
        text = re.sub(pattern, repl, text)

    # Preserva pausas naturais de respiração nas quebras de linha e listas
    lines = []
    for raw_line in text.splitlines():
        ln = re.sub(r"[ \t]+", " ", raw_line).strip()
        if not ln:
            continue
        if ln[-1] not in ".!?:,;":
            ln += "."
        lines.append(ln)

    text = " ".join(lines)
    text = re.sub(r"\s+", " ", text).strip()
    return text

PIPER_CACHE = {}
WHISPER_MODEL = None
REC_STATE = {"stream": None, "frames": [], "samplerate": 16000}

def get_piper_voice(model_filename: str):
    if model_filename in PIPER_CACHE:
        return PIPER_CACHE[model_filename]
    from piper import PiperVoice
    model_path = os.path.join(OFFLINE_MODELS_DIR, model_filename)
    if not os.path.exists(model_path):
        # Fallback para qualquer .onnx disponível na pasta offline_models
        candidates = glob.glob(os.path.join(OFFLINE_MODELS_DIR, "*.onnx"))
        if not candidates:
            raise FileNotFoundError("Nenhum modelo .onnx encontrado em offline_models")
        model_path = candidates[0]
    voice = PiperVoice.load(model_path)
    PIPER_CACHE[model_filename] = voice
    return voice

def synthesize_piper_offline(text: str, model_filename: str, rate_str: str, out_wav_path: str):
    import wave
    voice = get_piper_voice(model_filename)
    # Converte rate "+10%" / "-10%" em length_scale (menor = mais rápido)
    try:
        pct = int(re.sub(r"[^\d-]", "", rate_str or "0") or "0")
    except Exception:
        pct = 0
    length_scale = max(0.65, min(1.5, 1.0 - (pct / 100.0)))
    try:
        from piper.config import SynthesisConfig
        syn_cfg = SynthesisConfig(length_scale=length_scale)
        with wave.open(out_wav_path, "wb") as wf:
            voice.synthesize_wav(text, wf, syn_config=syn_cfg)
    except Exception:
        with wave.open(out_wav_path, "wb") as wf:
            voice.synthesize_wav(text, wf)

def transcribe_wav_offline(wav_path: str) -> str:
    global WHISPER_MODEL
    from faster_whisper import WhisperModel
    if WHISPER_MODEL is None:
        WHISPER_MODEL = WhisperModel("tiny", device="cpu", compute_type="int8")
    segments, _ = WHISPER_MODEL.transcribe(wav_path, language="pt", beam_size=3)
    return " ".join(seg.text.strip() for seg in segments).strip()

async def synthesize_edge_tts(text: str, voice: str, rate: str, pitch: str, out_path: str):
    import edge_tts
    try:
        communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate, pitch=pitch)
        await communicate.save(out_path)
    except Exception:
        communicate = edge_tts.Communicate(text=text, voice="pt-BR-AntonioNeural", rate=rate, pitch=pitch)
        await communicate.save(out_path)

def fallback_sapi_speak(text: str):
    try:
        import pyttsx3
        engine = pyttsx3.init()
        engine.setProperty("rate", 195)
        engine.say(text)
        engine.runAndWait()
    except Exception as e:
        print(f"[ERR] Fallback SAPI falhou: {e}")

def enqueue_speech(
    raw_text: str,
    source_label: str = "chat",
    play_on_host: bool = True,
    voice_override: str = None,
    rate_override: str = None,
    pitch_override: str = None
):
    cleaned = clean_text_for_speech(raw_text)
    if not cleaned:
        return None

    item_id = hashlib.md5(f"{time.time()}_{cleaned[:60]}".encode("utf-8")).hexdigest()[:10]
    filename = f"cook45_{item_id}.mp3"
    filepath = os.path.join(AUDIO_DIR, filename)

    entry = {
        "id": item_id,
        "timestamp": time.strftime("%H:%M:%S"),
        "source": source_label,
        "raw_text": raw_text[:1500],
        "clean_text": cleaned,
        "voice": voice_override or DEVICE_STATE["voice"],
        "rate": rate_override or DEVICE_STATE["rate"],
        "pitch": pitch_override or DEVICE_STATE["pitch"],
        "audio_file": filepath,
        "audio_url": f"/audio/{filename}",
        "play_on_host": play_on_host,
        "ready": False
    }

    with QUEUE_LOCK:
        SPEECH_QUEUE.append(entry)

    return entry

def speech_worker_loop():
    """Worker dedicado que sintetiza e reproduz a fila de voz do cook45."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    while True:
        entry = None
        with QUEUE_LOCK:
            if SPEECH_QUEUE:
                entry = SPEECH_QUEUE.pop(0)

        if not entry:
            time.sleep(0.1)
            continue

        try:
            DEVICE_STATE["speaking"] = True
            DEVICE_STATE["current_text"] = entry["clean_text"]
            print(f"\n[VOZ COOK45] ({entry['source']}) Sintetizando: {entry['clean_text'][:90]}...")

            use_offline = bool(DEVICE_STATE.get("offline_mode", False))
            is_niko = "Niko" in entry.get("source", "")
            offline_model = DEVICE_STATE.get("offline_kilo_voice", "pt_BR-cadu-medium.onnx") if is_niko else DEVICE_STATE.get("offline_voice", "pt_BR-faber-medium.onnx")

            if not use_offline:
                try:
                    loop.run_until_complete(
                        synthesize_edge_tts(
                            entry["clean_text"],
                            entry["voice"],
                            entry["rate"],
                            entry["pitch"],
                            entry["audio_file"]
                        )
                    )
                    entry["ready"] = True
                    DEVICE_STATE["engine"] = "edge-tts (Neural Online)"
                    DEVICE_STATE["last_audio_url"] = entry["audio_url"]
                except Exception as e:
                    print(f"[WARN] Sem internet ou falha no edge-tts ({e}), chaveando para Piper ONNX 100% Offline...")
                    use_offline = True

            if use_offline:
                try:
                    wav_path = entry["audio_file"].rsplit(".", 1)[0] + ".wav"
                    wav_url = entry["audio_url"].rsplit(".", 1)[0] + ".wav"
                    synthesize_piper_offline(entry["clean_text"], offline_model, entry["rate"], wav_path)
                    entry["audio_file"] = wav_path
                    entry["audio_url"] = wav_url
                    entry["ready"] = True
                    DEVICE_STATE["engine"] = f"Piper ONNX Offline ({offline_model.replace('.onnx', '')})"
                    DEVICE_STATE["last_audio_url"] = wav_url
                except Exception as e2:
                    print(f"[WARN] Falha no Piper ({e2}), acionando SAPI5 local...")
                    DEVICE_STATE["engine"] = "Windows SAPI5 (Offline)"
                    if entry.get("play_on_host", True) and DEVICE_STATE["enabled"]:
                        fallback_sapi_speak(entry["clean_text"])

            # Adiciona ao histórico
            hist_item = {
                "id": entry["id"],
                "timestamp": entry["timestamp"],
                "source": entry["source"],
                "text": entry["clean_text"],
                "raw_text": entry["raw_text"],
                "audio_url": entry["audio_url"] if entry["ready"] else "",
                "voice": entry["voice"]
            }
            DEVICE_STATE["history"].insert(0, hist_item)
            DEVICE_STATE["history"] = DEVICE_STATE["history"][:30]

            # Toca direto na placa de som do Windows se habilitado
            if entry["ready"] and entry.get("play_on_host", True) and DEVICE_STATE["enabled"]:
                play_mp3_winmm(entry["audio_file"], DEVICE_STATE["volume"])

        except Exception as e:
            print(f"[ERR] Erro no worker de voz: {e}")
        finally:
            DEVICE_STATE["speaking"] = False
            DEVICE_STATE["current_text"] = ""

def get_latest_transcript_files(limit: int = 20):
    """Localiza todos os logs ativos do Antigravity (suporta multiplas janelas abertas ao mesmo tempo)."""
    if not os.path.isdir(BRAIN_DIR):
        return []
    pattern_full = os.path.join(BRAIN_DIR, "*", ".system_generated", "logs", "transcript_full.jsonl")
    pattern_std = os.path.join(BRAIN_DIR, "*", ".system_generated", "logs", "transcript.jsonl")
    all_files = glob.glob(pattern_full) + glob.glob(pattern_std)
    # Deduplica por conversa: prefere transcript_full.jsonl se existir na mesma pasta
    by_conv = {}
    for f in all_files:
        conv_dir = os.path.dirname(f)
        if conv_dir not in by_conv or os.path.basename(f) == "transcript_full.jsonl":
            by_conv[conv_dir] = f
    deduped = list(by_conv.values())
    deduped.sort(key=lambda f: os.path.getmtime(f) if os.path.exists(f) else 0, reverse=True)
    return deduped[:limit]

def transcript_watcher_loop():
    """Monitora em tempo real todas as janelas/conversas abertas do Antigravity sem se perder."""
    seen_keys = set()
    file_offsets = {}
    conv_labels = {}

    def get_conv_tag(conv_id: str) -> str:
        if conv_id not in conv_labels:
            conv_labels[conv_id] = f"Janela {len(conv_labels) + 1}"
        return conv_labels[conv_id]

    # Na inicialização, indexa TODAS as conversas existentes para nunca reler histórico antigo ao trocar de janela
    for tfile in get_latest_transcript_files(limit=60):
        conv_dir = os.path.dirname(tfile)
        conv_id = os.path.basename(os.path.dirname(os.path.dirname(conv_dir)))
        try:
            with open(tfile, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    s = line.strip()
                    if not s:
                        continue
                    try:
                        obj = json.loads(s)
                        if obj.get("source") == "MODEL" and obj.get("type") == "PLANNER_RESPONSE":
                            content = (obj.get("content") or "").strip()
                            if content:
                                key = f"{conv_id}:{obj.get('step_index')}"
                                seen_keys.add(key)
                                DEVICE_STATE["last_step_key"] = key
                    except Exception:
                        pass
                file_offsets[tfile] = f.tell()
        except Exception:
            pass

    print(f"[WATCHER] Monitorando todas as janelas do Antigravity ({len(file_offsets)} conversas indexadas).")

    while True:
        try:
            for tfile in get_latest_transcript_files(limit=15):
                conv_dir = os.path.dirname(tfile)
                conv_id = os.path.basename(os.path.dirname(os.path.dirname(conv_dir)))
                fsize = os.path.getsize(tfile) if os.path.exists(tfile) else 0
                prev_offset = file_offsets.get(tfile, 0)

                # Se o arquivo foi truncado/recriado, reseta offset
                if fsize < prev_offset:
                    prev_offset = 0

                if fsize == prev_offset:
                    continue

                with open(tfile, "r", encoding="utf-8", errors="ignore") as f:
                    f.seek(prev_offset)
                    for line in f:
                        s = line.strip()
                        if not s:
                            continue
                        try:
                            obj = json.loads(s)
                            if obj.get("source") == "MODEL" and obj.get("type") == "PLANNER_RESPONSE":
                                content = (obj.get("content") or "").strip()
                                step_idx = obj.get("step_index")
                                key = f"{conv_id}:{step_idx}"
                                if content and key not in seen_keys:
                                    seen_keys.add(key)
                                    DEVICE_STATE["last_step_key"] = key
                                    tag = get_conv_tag(conv_id)
                                    if DEVICE_STATE["enabled"] and DEVICE_STATE["auto_read_chat"] and has_active_player():
                                        print(f"[WATCHER] Nova mensagem do cook45 ({tag} / {key})!")
                                        enqueue_speech(content, source_label=f"cook45 ({tag})", play_on_host=True)
                        except Exception:
                            pass
                    file_offsets[tfile] = f.tell()
        except Exception as e:
            print(f"[WARN] Erro no watcher: {e}")

        time.sleep(0.30)

def get_latest_kilo_parts(limit: int = 12):
    """Lê os últimos blocos de resposta do assistente no banco SQLite do Kilo Code (kilo.db)."""
    if not os.path.exists(KILO_DB_PATH):
        return []
    results = []
    try:
        con = sqlite3.connect(KILO_DB_PATH, timeout=1.5)
        cur = con.cursor()
        rows = cur.execute(
            "SELECT p.id, p.data, m.data FROM part p "
            "JOIN message m ON p.message_id = m.id "
            "ORDER BY p.rowid DESC LIMIT ?",
            (limit,)
        ).fetchall()
        con.close()
        for pid, p_raw, m_raw in reversed(rows):
            try:
                m_obj = json.loads(m_raw)
                if m_obj.get("role") != "assistant":
                    continue
                p_obj = json.loads(p_raw)
                if p_obj.get("type") == "text":
                    t_info = p_obj.get("time") or {}
                    # Só lê quando o bloco de texto terminou de ser gerado ("end" presente)
                    if "end" in t_info:
                        txt = (p_obj.get("text") or "").strip()
                        if txt:
                            results.append((pid, txt))
            except Exception:
                pass
    except Exception:
        pass
    return results

def kilo_watcher_loop():
    """Monitora em tempo real todas as respostas do Niko (Kilo Code) e fala com timbre próprio."""
    seen_kilo_ids = set()
    for pid, _ in get_latest_kilo_parts(limit=30):
        seen_kilo_ids.add(pid)

    print(f"[KILO WATCHER] Monitorando respostas do Niko/Kilo Code ({len(seen_kilo_ids)} partes anteriores indexadas).")

    while True:
        try:
            for pid, txt in get_latest_kilo_parts(limit=10):
                if pid not in seen_kilo_ids:
                    seen_kilo_ids.add(pid)
                    if DEVICE_STATE["enabled"] and DEVICE_STATE.get("auto_read_kilo", True) and has_active_player():
                        print(f"[KILO WATCHER] Nova resposta do Niko detectada ({pid})!")
                        enqueue_speech(
                            txt,
                            source_label="Chat Niko (Kilo)",
                            play_on_host=True,
                            voice_override=DEVICE_STATE.get("kilo_voice", "en-US-BrianMultilingualNeural"),
                            rate_override=DEVICE_STATE.get("kilo_rate", "+4%"),
                            pitch_override=DEVICE_STATE.get("kilo_pitch", "+0Hz")
                        )
        except Exception as e:
            print(f"[WARN] Erro no kilo_watcher: {e}")

        time.sleep(0.45)

def get_windows_clipboard() -> str:
    """Lê o texto do Clipboard direto via user32.dll / kernel32.dll."""
    CF_UNICODETEXT = 13
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    user32.OpenClipboard.argtypes = [ctypes.c_void_p]
    user32.GetClipboardData.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]

    text = ""
    if user32.OpenClipboard(None):
        try:
            handle = user32.GetClipboardData(CF_UNICODETEXT)
            if handle:
                ptr = kernel32.GlobalLock(handle)
                if ptr:
                    try:
                        text = ctypes.wstring_at(ptr)
                    finally:
                        kernel32.GlobalUnlock(handle)
        finally:
            user32.CloseClipboard()
    return text

def clipboard_watcher_loop():
    """Monitora Ctrl+C quando o modo Clipboard estiver ativado."""
    last_clip = ""
    try:
        last_clip = get_windows_clipboard()
    except Exception:
        pass

    while True:
        try:
            if DEVICE_STATE["enabled"] and DEVICE_STATE["clipboard_watch"]:
                curr = get_windows_clipboard()
                if curr and curr != last_clip and len(curr.strip()) > 1:
                    last_clip = curr
                    enqueue_speech(curr, source_label="Clipboard (Ctrl+C)", play_on_host=True)
            else:
                last_clip = get_windows_clipboard()
        except Exception:
            pass
        time.sleep(0.5)

class VoiceDaemonHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Access-Control-Request-Private-Network")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._send_json({"ok": True})

    def do_GET(self):
        global LAST_UI_HEARTBEAT
        parsed = urlparse(self.path)
        if parsed.path == "/api/state":
            LAST_UI_HEARTBEAT = time.time()
            self._send_json({
                "state": DEVICE_STATE,
                "voices": AVAILABLE_VOICES,
                "queue_size": len(SPEECH_QUEUE),
                "player_connected": True
            })
        elif parsed.path == "/api/pc/search":
            if not DEVICE_STATE.get("pc_control", True):
                return self._send_json({"ok": False, "error": "Controle do PC bloqueado no painel"}, 403)
            qs = parse_qs(parsed.query)
            q = (qs.get("q", [""])[0]).lower().strip()
            ftype = (qs.get("type", ["all"])[0]).lower().strip()
            ext_map = {
                "music": (".mp3", ".wav", ".flac", ".m4a", ".ogg", ".wma"),
                "image": (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"),
                "video": (".mp4", ".mkv", ".avi", ".mov", ".webm"),
            }
            allowed_exts = ext_map.get(ftype)
            folders = [
                r"C:\musica",
                r"C:\musicas 2",
                r"C:\img",
                os.path.expanduser(r"~\Music"),
                os.path.expanduser(r"~\Pictures"),
                os.path.expanduser(r"~\Videos"),
                os.path.expanduser(r"~\Downloads"),
                os.path.expanduser(r"~\Desktop"),
                os.path.expanduser(r"~\Documents"),
            ]
            matches = []
            for base_f in folders:
                if not os.path.isdir(base_f):
                    continue
                for root, _, files in os.walk(base_f):
                    for fn in files:
                        if allowed_exts and not fn.lower().endswith(allowed_exts):
                            continue
                        if q and q not in fn.lower():
                            continue
                        matches.append(os.path.join(root, fn))
                        if len(matches) >= 50:
                            break
                    if len(matches) >= 50:
                        break
            return self._send_json({"ok": True, "files": matches})

        elif parsed.path.startswith("/audio/"):
            fname = os.path.basename(parsed.path)
            fpath = os.path.join(AUDIO_DIR, fname)
            if os.path.exists(fpath):
                with open(fpath, "rb") as f:
                    data = f.read()
                self.send_response(200)
                ctype = "audio/wav" if fname.lower().endswith(".wav") else "audio/mpeg"
                self.send_header("Content-Type", ctype)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            else:
                self._send_json({"error": "Arquivo de áudio não encontrado"}, 404)
        else:
            self._send_json({"service": "TYON-V45 cook45 Voice Daemon", "status": "online"})

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
        try:
            payload = json.loads(raw_body)
        except Exception:
            payload = {}

        if parsed.path == "/api/speak":
            text = (payload.get("text") or "").strip()
            source = payload.get("source") or "Manual / Painel"
            play_host = payload.get("play_on_host", True)
            if not text:
                return self._send_json({"error": "Texto vazio"}, 400)
            entry = enqueue_speech(text, source_label=source, play_on_host=play_host)
            return self._send_json({"ok": True, "entry": entry})

        elif parsed.path == "/api/stop":
            with QUEUE_LOCK:
                SPEECH_QUEUE.clear()
            stop_audio_playback()
            return self._send_json({"ok": True, "message": "Áudio interrompido"})

        elif parsed.path == "/api/config":
            for k in (
                "enabled", "offline_mode", "pc_control", "auto_read_chat", "auto_read_kilo", "clipboard_watch",
                "voice", "offline_voice", "rate", "pitch",
                "kilo_voice", "offline_kilo_voice", "kilo_rate", "kilo_pitch", "volume"
            ):
                if k in payload:
                    DEVICE_STATE[k] = payload[k]
            if not DEVICE_STATE["enabled"]:
                with QUEUE_LOCK:
                    SPEECH_QUEUE.clear()
                stop_audio_playback()
            save_persisted_state()
            return self._send_json({"ok": True, "state": DEVICE_STATE})

        elif parsed.path == "/api/record_start":
            try:
                import sounddevice as sd
                if REC_STATE["stream"] is not None:
                    try:
                        REC_STATE["stream"].stop()
                        REC_STATE["stream"].close()
                    except Exception:
                        pass
                REC_STATE["frames"] = []
                def _cb(indata, frames, time_info, status):
                    REC_STATE["frames"].append(indata.copy())
                stream = sd.InputStream(samplerate=16000, channels=1, dtype="int16", callback=_cb)
                stream.start()
                REC_STATE["stream"] = stream
                DEVICE_STATE["recording"] = True
                return self._send_json({"ok": True, "recording": True})
            except Exception as e:
                DEVICE_STATE["recording"] = False
                return self._send_json({"ok": False, "error": f"Microfone não detectado ({e})"}, 400)

        elif parsed.path == "/api/record_stop":
            try:
                import wave
                import numpy as np
                if REC_STATE["stream"] is not None:
                    REC_STATE["stream"].stop()
                    REC_STATE["stream"].close()
                    REC_STATE["stream"] = None
                DEVICE_STATE["recording"] = False
                if not REC_STATE["frames"]:
                    return self._send_json({"ok": False, "error": "Nenhum áudio gravado"}, 400)
                audio_np = np.concatenate(REC_STATE["frames"], axis=0)
                rec_path = os.path.join(AUDIO_DIR, "dictation_last.wav")
                with wave.open(rec_path, "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(16000)
                    wf.writeframes(audio_np.tobytes())
                transcript = transcribe_wav_offline(rec_path)
                DEVICE_STATE["last_transcript"] = transcript
                return self._send_json({"ok": True, "text": transcript})
            except Exception as e:
                DEVICE_STATE["recording"] = False
                return self._send_json({"ok": False, "error": str(e)}, 500)

        elif parsed.path == "/api/pc/open":
            if not DEVICE_STATE.get("pc_control", True):
                return self._send_json({"ok": False, "error": "Controle do PC bloqueado no painel"}, 403)
            target = (payload.get("target") or "").strip()
            if not target:
                return self._send_json({"ok": False, "error": "Alvo vazio"}, 400)
            try:
                if target.lower().endswith((".mp3", ".wav", ".wma", ".m4a")):
                    if play_music_winmm(target, DEVICE_STATE.get("volume", 90)):
                        return self._send_json({"ok": True, "opened": target, "player": "winmm_direct"})
                os.startfile(target)
                return self._send_json({"ok": True, "opened": target})
            except Exception as e:
                return self._send_json({"ok": False, "error": str(e)}, 500)

        elif parsed.path == "/api/narrate_batch":
            text = (payload.get("text") or "").strip()
            if not text:
                return self._send_json({"error": "Texto vazio"}, 400)
            chunks = [c.strip() for c in re.split(r"(?<=[.!?])\s+|\n+", text) if c.strip()]
            entries = []
            for idx, chunk in enumerate(chunks[:30]):
                e = enqueue_speech(chunk, source_label=f"Narrador Lote {idx+1}/{len(chunks)}", play_on_host=True)
                if e:
                    entries.append(e["id"])
            return self._send_json({"ok": True, "queued": len(entries)})

        elif parsed.path == "/api/pin":
            pinned = bool(payload.get("pinned", True))
            move_side = bool(payload.get("move_to_side", False))
            count = pin_mini_player_window(pinned=pinned, move_to_side=move_side)
            return self._send_json({"ok": True, "pinned": pinned, "windows_updated": count})

        elif parsed.path == "/api/spawn_floating":
            try:
                import subprocess
                script = os.path.join(BASE_DIR, "abrir_mini_player.py")
                subprocess.Popen([sys.executable, script], cwd=BASE_DIR)
                return self._send_json({"ok": True, "spawned": True})
            except Exception as e:
                return self._send_json({"error": str(e)}, 500)

        elif parsed.path == "/api/read_last_kilo":
            parts = get_latest_kilo_parts(limit=10)
            if parts:
                _, last_txt = parts[-1]
                entry = enqueue_speech(
                    last_txt,
                    source_label="Replay Niko (Kilo)",
                    play_on_host=True,
                    voice_override=DEVICE_STATE.get("kilo_voice", "en-US-BrianMultilingualNeural"),
                    rate_override=DEVICE_STATE.get("kilo_rate", "+12%"),
                    pitch_override=DEVICE_STATE.get("kilo_pitch", "-2Hz")
                )
                return self._send_json({"ok": True, "entry": entry})
            return self._send_json({"error": "Nenhuma mensagem do Niko encontrada"}, 404)

        elif parsed.path == "/api/read_last":
            # Força a leitura da última resposta do cook45 no chat atual
            for tfile in get_latest_transcript_files():
                try:
                    last_content = None
                    with open(tfile, "r", encoding="utf-8", errors="ignore") as f:
                        for line in f:
                            obj = json.loads(line.strip())
                            if obj.get("source") == "MODEL" and obj.get("type") == "PLANNER_RESPONSE":
                                c = (obj.get("content") or "").strip()
                                if c:
                                    last_content = c
                    if last_content:
                        entry = enqueue_speech(last_content, source_label="Replay Última Mensagem", play_on_host=True)
                        return self._send_json({"ok": True, "entry": entry})
                except Exception:
                    pass
            return self._send_json({"error": "Nenhuma mensagem encontrada"}, 404)

        self._send_json({"error": "Rota inválida"}, 404)

def acquire_single_instance_mutex():
    """Garante instancia unica do motor de voz para evitar atrito de dois audios tocando juntos."""
    kernel32 = ctypes.windll.kernel32
    mutex = kernel32.CreateMutexW(None, False, "Local\\TYON_V45_COOK45_VOICE_MUTEX")
    if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        return None
    return mutex

def main():
    _mutex = acquire_single_instance_mutex()
    if _mutex is None:
        print("[TYON-V45] Outro motor de voz já está ativo. Encerrando duplicata para evitar atrito de áudio.")
        sys.exit(0)

    port = int(os.environ.get("VOICE_DAEMON_PORT", "8091"))
    t_worker = threading.Thread(target=speech_worker_loop, daemon=True)
    t_worker.start()

    t_watcher = threading.Thread(target=transcript_watcher_loop, daemon=True)
    t_watcher.start()

    t_kilo = threading.Thread(target=kilo_watcher_loop, daemon=True)
    t_kilo.start()

    t_clip = threading.Thread(target=clipboard_watcher_loop, daemon=True)
    t_clip.start()

    server = HTTPServer(("127.0.0.1", port), VoiceDaemonHandler)
    print(f"============================================================")
    print(f" TYON-V45 // DISPOSITIVO DE VOZ COOK45 ONLINE (Porta {port})")
    print(f" Escutando o chat do Antigravity em tempo real...")
    print(f"============================================================")
    server.serve_forever()

if __name__ == "__main__":
    main()
