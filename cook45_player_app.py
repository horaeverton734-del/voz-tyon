import os
import sys
import math
import time
import json
import ctypes
import threading
import urllib.request
import tkinter as tk
from tkinter import ttk

API_BASE = "http://127.0.0.1:8091"

# Cores do tema tático cook45
BG_DARK = "#080b10"
CHASSIS = "#10151f"
PANEL = "#161d2b"
BORDER = "#26334d"
NEON = "#00ff9d"
AMBER = "#ffae00"
DANGER = "#ff3b5c"
CYAN = "#00d2ff"
TEXT = "#e2e8f0"
MUTED = "#8494ad"

VOICES = [
    ("Cook45 Padrão (Antonio - Firme/Direto)", "pt-BR-AntonioNeural", -6, 12),
    ("Cook45 Veterano (Donato - Grave/Sênior)", "pt-BR-DonatoNeural", -8, 8),
    ("Cook45 Tático (Humberto - Seco/Rápido)", "pt-BR-HumbertoNeural", -4, 15),
    ("Cook45 Estúdio (Fabio - Claro/Natural)", "pt-BR-FabioNeural", -3, 10),
    ("Cook45 Operador (Julio - Dinâmico)", "pt-BR-JulioNeural", -5, 12),
    ("Cook45 Clássico (Nicolau)", "pt-BR-NicolauNeural", -4, 10),
    ("Cook45 Pesado (Valerio - Subgrave)", "pt-BR-ValerioNeural", -10, 8),
]

def api_get(path):
    try:
        req = urllib.request.Request(f"{API_BASE}{path}", method="GET")
        with urllib.request.urlopen(req, timeout=1.2) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None

def api_post(path, payload=None):
    def _worker():
        try:
            body = json.dumps(payload or {}).encode("utf-8")
            req = urllib.request.Request(
                f"{API_BASE}{path}",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            urllib.request.urlopen(req, timeout=2.0).read()
        except Exception:
            pass
    threading.Thread(target=_worker, daemon=True).start()


class Cook45MiniPlayer(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("COOK45 // MINI PLAYER DE VOZ")
        self.configure(bg=BG_DARK)
        self.resizable(False, False)

        # Estado local sincronizado com o daemon
        self.is_topmost = True
        self.is_compact = False
        self.enabled = True
        self.auto_chat = True
        self.clip_watch = False
        self.speaking = False
        self.phase = 0.0
        self.history_items = []
        self.active_tab = "voice"

        # Posiciona no canto direito da tela, bem ao lado do chat
        screen_w = self.winfo_screenwidth()
        self.win_w = 345
        self.win_h_full = 515
        self.win_h_mini = 205
        x_pos = max(10, screen_w - self.win_w - 22)
        y_pos = 75
        self.geometry(f"{self.win_w}x{self.win_h_full}+{x_pos}+{y_pos}")
        self.attributes("-topmost", True)

        self._setup_styles()
        self._build_ui()
        self._enable_drag()

        # Força a janela a aparecer na frente de tudo no Windows
        self.after(150, self._bring_to_front)
        self.after(40, self._animate_scope)
        self.after(500, self._poll_daemon)

    def _enable_drag(self):
        """Permite arrastar o Mini-Player clicando e segurando no cabeçalho ou no chassi."""
        self._drag_x = 0
        self._drag_y = 0

        def start_drag(event):
            self._drag_x = event.x_root - self.winfo_x()
            self._drag_y = event.y_root - self.winfo_y()

        def do_drag(event):
            x = event.x_root - self._drag_x
            y = event.y_root - self._drag_y
            self.geometry(f"+{x}+{y}")

        for widget in (self.main_frame, self.scope, self.lbl_status):
            widget.bind("<ButtonPress-1>", start_drag)
            widget.bind("<B1-Motion>", do_drag)

    def _bring_to_front(self):
        try:
            self.deiconify()
            self.lift()
            self.attributes("-topmost", True)
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id()) or self.winfo_id()
            ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            ctypes.windll.user32.SetForegroundWindow(hwnd)
        except Exception:
            pass

    def _setup_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(
            "TCombobox",
            fieldbackground="#0b0f17",
            background="#1a2333",
            foreground=TEXT,
            arrowcolor=NEON
        )

    def _build_ui(self):
        # Container principal
        self.main_frame = tk.Frame(self, bg=CHASSIS, highlightbackground=BORDER, highlightthickness=2, padx=10, pady=8)
        self.main_frame.pack(fill="both", expand=True, padx=4, pady=4)

        # 1. TOPO: LED + Título + Botões Pin e Compactar
        top_bar = tk.Frame(self.main_frame, bg=CHASSIS)
        top_bar.pack(fill="x", pady=(0, 6))

        self.led_canvas = tk.Canvas(top_bar, width=14, height=14, bg=CHASSIS, highlightthickness=0)
        self.led_canvas.pack(side="left", padx=(0, 6))
        self.led_dot = self.led_canvas.create_oval(2, 2, 12, 12, fill=NEON, outline="")

        title_box = tk.Frame(top_bar, bg=CHASSIS)
        title_box.pack(side="left", fill="x", expand=True)
        tk.Label(title_box, text="TYON-V45 // COOK45 PLAYER", font=("Consolas", 9, "bold"), fg="#ffffff", bg=CHASSIS, anchor="w").pack(fill="x")
        self.lbl_status = tk.Label(title_box, text="ONLINE - ESCUTANDO CHAT", font=("Consolas", 7), fg=NEON, bg=CHASSIS, anchor="w")
        self.lbl_status.pack(fill="x")

        self.btn_compact = tk.Button(
            top_bar, text="➖ MINI", font=("Consolas", 7, "bold"),
            bg="#1a2333", fg=CYAN, activebackground="#25324a", activeforeground="#fff",
            bd=1, relief="solid", padx=5, pady=2, cursor="hand2", command=self.toggle_compact
        )
        self.btn_compact.pack(side="right", padx=(4, 0))

        self.btn_pin = tk.Button(
            top_bar, text="📌 TOPO", font=("Consolas", 7, "bold"),
            bg="#0e2923", fg=NEON, activebackground="#174238", activeforeground="#fff",
            bd=1, relief="solid", padx=5, pady=2, cursor="hand2", command=self.toggle_topmost
        )
        self.btn_pin.pack(side="right")

        # 2. VISOR LCD + OSCILOSCÓPIO EM TEMPO REAL
        lcd_frame = tk.Frame(self.main_frame, bg="#04070b", highlightbackground="#1c2d3d", highlightthickness=1)
        lcd_frame.pack(fill="x", pady=(0, 7))

        self.scope = tk.Canvas(lcd_frame, width=310, height=62, bg="#04070b", highlightthickness=0)
        self.scope.pack(fill="x")

        self.lbl_caption = tk.Label(
            lcd_frame,
            text="Pronto — tudo que o cook45 responder no chat toca aqui.",
            font=("Consolas", 8), fg="#d1fae5", bg="#070d14", anchor="w", padx=6, pady=3
        )
        self.lbl_caption.pack(fill="x")

        # 3. BOTÕES DE TRANSPORTE (MEDIA PLAYER)
        trans_frame = tk.Frame(self.main_frame, bg=CHASSIS)
        trans_frame.pack(fill="x", pady=(0, 6))
        trans_frame.columnconfigure(0, weight=1)
        trans_frame.columnconfigure(1, weight=1)
        trans_frame.columnconfigure(2, weight=1)

        tk.Button(
            trans_frame, text="▶ LER ÚLTIMA", font=("Consolas", 8, "bold"),
            bg="#0d2b22", fg=NEON, activebackground="#164739", activeforeground="#fff",
            bd=1, relief="solid", pady=5, cursor="hand2", command=self.cmd_read_last
        ).grid(row=0, column=0, sticky="ew", padx=(0, 3))

        tk.Button(
            trans_frame, text="⚡ TESTAR", font=("Consolas", 8, "bold"),
            bg="#1b2436", fg="#ffffff", activebackground="#28354f", activeforeground=CYAN,
            bd=1, relief="solid", pady=5, cursor="hand2", command=self.cmd_test_voice
        ).grid(row=0, column=1, sticky="ew", padx=3)

        tk.Button(
            trans_frame, text="⏹ PARAR", font=("Consolas", 8, "bold"),
            bg="#33121b", fg="#ff7088", activebackground="#4d1b29", activeforeground="#fff",
            bd=1, relief="solid", pady=5, cursor="hand2", command=self.cmd_stop
        ).grid(row=0, column=2, sticky="ew", padx=(3, 0))

        # 4. CHAVES RÁPIDAS (VOZ ON/MUTE, AUTO-CHAT, CLIPBOARD CTRL+C)
        pills_frame = tk.Frame(self.main_frame, bg=CHASSIS)
        pills_frame.pack(fill="x", pady=(0, 7))
        pills_frame.columnconfigure(0, weight=1)
        pills_frame.columnconfigure(1, weight=1)
        pills_frame.columnconfigure(2, weight=1)

        self.btn_power = tk.Button(
            pills_frame, text="🔊 VOZ: ON", font=("Consolas", 7, "bold"),
            bg="#0d2b22", fg=NEON, bd=1, relief="solid", pady=4, cursor="hand2",
            command=lambda: self.toggle_flag("enabled")
        )
        self.btn_power.grid(row=0, column=0, sticky="ew", padx=(0, 3))

        self.btn_autochat = tk.Button(
            pills_frame, text="💬 CHAT: AUTO", font=("Consolas", 7, "bold"),
            bg="#0d2b22", fg=NEON, bd=1, relief="solid", pady=4, cursor="hand2",
            command=lambda: self.toggle_flag("auto_read_chat")
        )
        self.btn_autochat.grid(row=0, column=1, sticky="ew", padx=3)

        self.btn_clip = tk.Button(
            pills_frame, text="📋 CTRL+C: OFF", font=("Consolas", 7, "bold"),
            bg="#121824", fg=MUTED, bd=1, relief="solid", pady=4, cursor="hand2",
            command=lambda: self.toggle_flag("clipboard_watch")
        )
        self.btn_clip.grid(row=0, column=2, sticky="ew", padx=(3, 0))

        # 5. CONTAINER EXPANSÍVEL (GAVETAS: TIMBRE, DIGITAR TEXTO, HISTÓRICO)
        self.expand_container = tk.Frame(self.main_frame, bg=CHASSIS)
        self.expand_container.pack(fill="both", expand=True)

        tabs_bar = tk.Frame(self.expand_container, bg=CHASSIS)
        tabs_bar.pack(fill="x", pady=(2, 6))
        tabs_bar.columnconfigure(0, weight=1)
        tabs_bar.columnconfigure(1, weight=1)
        tabs_bar.columnconfigure(2, weight=1)

        self.tab_buttons = {}
        for idx, (tid, label) in enumerate([
            ("voice", "🎛️ VOZ/TOM"),
            ("speak", "🎙️ DIGITAR"),
            ("hist", "📜 HISTÓRICO")
        ]):
            b = tk.Button(
                tabs_bar, text=label, font=("Consolas", 8, "bold"),
                bg="#1d283b" if tid == "voice" else "#111722",
                fg=CYAN if tid == "voice" else MUTED,
                bd=1, relief="solid", pady=4, cursor="hand2",
                command=lambda t=tid: self.switch_tab(t)
            )
            b.grid(row=0, column=idx, sticky="ew", padx=2)
            self.tab_buttons[tid] = b

        # Gaveta 1: Voz / Timbre / Sliders
        self.drawer_voice = tk.Frame(self.expand_container, bg=PANEL, highlightbackground=BORDER, highlightthickness=1, padx=8, pady=8)
        self.drawer_voice.pack(fill="both", expand=True)

        tk.Label(self.drawer_voice, text="TIMBRE / OPERADOR NEURAL COOK45:", font=("Consolas", 7, "bold"), fg=MUTED, bg=PANEL, anchor="w").pack(fill="x")
        self.voice_var = tk.StringVar(value=VOICES[0][0])
        self.combo_voice = ttk.Combobox(
            self.drawer_voice, textvariable=self.voice_var,
            values=[v[0] for v in VOICES], state="readonly", font=("Consolas", 8)
        )
        self.combo_voice.pack(fill="x", pady=(2, 8))
        self.combo_voice.bind("<<ComboboxSelected>>", self.on_voice_selected)

        # Velocidade
        rate_top = tk.Frame(self.drawer_voice, bg=PANEL)
        rate_top.pack(fill="x")
        tk.Label(rate_top, text="VELOCIDADE DA FALA (RATE):", font=("Consolas", 7), fg=MUTED, bg=PANEL).pack(side="left")
        self.lbl_rate_val = tk.Label(rate_top, text="+12%", font=("Consolas", 7, "bold"), fg=NEON, bg=PANEL)
        self.lbl_rate_val.pack(side="right")

        self.scale_rate = tk.Scale(
            self.drawer_voice, from_=-25, to=45, orient="horizontal",
            bg=PANEL, fg=TEXT, troughcolor="#0a0e16", highlightthickness=0,
            bd=0, showvalue=False, command=self.on_slider_move
        )
        self.scale_rate.set(12)
        self.scale_rate.pack(fill="x", pady=(0, 6))
        self.scale_rate.bind("<ButtonRelease-1>", lambda e: self.push_voice_config())

        # Grave (Pitch)
        pitch_top = tk.Frame(self.drawer_voice, bg=PANEL)
        pitch_top.pack(fill="x")
        tk.Label(pitch_top, text="GRAVE / TOM DA VOZ (PITCH):", font=("Consolas", 7), fg=MUTED, bg=PANEL).pack(side="left")
        self.lbl_pitch_val = tk.Label(pitch_top, text="-6Hz", font=("Consolas", 7, "bold"), fg=NEON, bg=PANEL)
        self.lbl_pitch_val.pack(side="right")

        self.scale_pitch = tk.Scale(
            self.drawer_voice, from_=-20, to=15, orient="horizontal",
            bg=PANEL, fg=TEXT, troughcolor="#0a0e16", highlightthickness=0,
            bd=0, showvalue=False, command=self.on_slider_move
        )
        self.scale_pitch.set(-6)
        self.scale_pitch.pack(fill="x", pady=(0, 6))
        self.scale_pitch.bind("<ButtonRelease-1>", lambda e: self.push_voice_config())

        # Volume
        vol_top = tk.Frame(self.drawer_voice, bg=PANEL)
        vol_top.pack(fill="x")
        tk.Label(vol_top, text="VOLUME DE SAÍDA:", font=("Consolas", 7), fg=MUTED, bg=PANEL).pack(side="left")
        self.lbl_vol_val = tk.Label(vol_top, text="100%", font=("Consolas", 7, "bold"), fg=NEON, bg=PANEL)
        self.lbl_vol_val.pack(side="right")

        self.scale_vol = tk.Scale(
            self.drawer_voice, from_=10, to=100, orient="horizontal",
            bg=PANEL, fg=TEXT, troughcolor="#0a0e16", highlightthickness=0,
            bd=0, showvalue=False, command=self.on_slider_move
        )
        self.scale_vol.set(100)
        self.scale_vol.pack(fill="x")
        self.scale_vol.bind("<ButtonRelease-1>", lambda e: self.push_voice_config())

        # Gaveta 2: Digitar / Colar texto manual
        self.drawer_speak = tk.Frame(self.expand_container, bg=PANEL, highlightbackground=BORDER, highlightthickness=1, padx=8, pady=8)
        tk.Label(self.drawer_speak, text="DIGITE OU COLE QUALQUER TEXTO:", font=("Consolas", 7, "bold"), fg=MUTED, bg=PANEL, anchor="w").pack(fill="x", pady=(0, 4))
        self.txt_manual = tk.Text(self.drawer_speak, height=6, bg="#0a0e16", fg=TEXT, insertbackground=NEON, font=("Consolas", 8), relief="solid", bd=1)
        self.txt_manual.pack(fill="both", expand=True, pady=(0, 6))

        btn_manual_row = tk.Frame(self.drawer_speak, bg=PANEL)
        btn_manual_row.pack(fill="x")
        tk.Button(
            btn_manual_row, text="🎙️ FALAR TEXTO AGORA", font=("Consolas", 8, "bold"),
            bg="#0d2b22", fg=NEON, bd=1, relief="solid", pady=5, cursor="hand2",
            command=self.cmd_speak_manual
        ).pack(side="left", fill="x", expand=True, padx=(0, 4))
        tk.Button(
            btn_manual_row, text="LIMPAR", font=("Consolas", 8),
            bg="#1b2436", fg=TEXT, bd=1, relief="solid", padx=8, pady=5, cursor="hand2",
            command=lambda: self.txt_manual.delete("1.0", "end")
        ).pack(side="right")

        # Gaveta 3: Histórico com Replay
        self.drawer_hist = tk.Frame(self.expand_container, bg=PANEL, highlightbackground=BORDER, highlightthickness=1, padx=8, pady=8)
        tk.Label(self.drawer_hist, text="DUPLO CLIQUE PARA REPETIR A FALA:", font=("Consolas", 7, "bold"), fg=MUTED, bg=PANEL, anchor="w").pack(fill="x", pady=(0, 4))
        self.lst_hist = tk.Listbox(
            self.drawer_hist, bg="#0a0e16", fg=TEXT, selectbackground="#1d283b",
            selectforeground=NEON, font=("Consolas", 8), bd=1, relief="solid", highlightthickness=0
        )
        self.lst_hist.pack(fill="both", expand=True, pady=(0, 6))
        self.lst_hist.bind("<Double-Button-1>", self.cmd_replay_selected)

        tk.Button(
            self.drawer_hist, text="▶ OUVIR SELECIONADA NOVAMENTE", font=("Consolas", 8, "bold"),
            bg="#0d2b22", fg=NEON, bd=1, relief="solid", pady=4, cursor="hand2",
            command=self.cmd_replay_selected
        ).pack(fill="x")

    def switch_tab(self, tab_id):
        self.active_tab = tab_id
        for tid, b in self.tab_buttons.items():
            b.configure(
                bg="#1d283b" if tid == tab_id else "#111722",
                fg=CYAN if tid == tab_id else MUTED
            )
        self.drawer_voice.pack_forget()
        self.drawer_speak.pack_forget()
        self.drawer_hist.pack_forget()

        if tab_id == "voice":
            self.drawer_voice.pack(fill="both", expand=True)
        elif tab_id == "speak":
            self.drawer_speak.pack(fill="both", expand=True)
        elif tab_id == "hist":
            self.drawer_hist.pack(fill="both", expand=True)

    def toggle_compact(self):
        self.is_compact = not self.is_compact
        if self.is_compact:
            self.expand_container.pack_forget()
            self.geometry(f"{self.win_w}x{self.win_h_mini}")
            self.btn_compact.configure(text="➕ ABRIR")
        else:
            self.expand_container.pack(fill="both", expand=True)
            self.geometry(f"{self.win_w}x{self.win_h_full}")
            self.btn_compact.configure(text="➖ MINI")

    def toggle_topmost(self):
        self.is_topmost = not self.is_topmost
        self.attributes("-topmost", self.is_topmost)
        if self.is_topmost:
            self.btn_pin.configure(text="📌 TOPO", bg="#0e2923", fg=NEON)
        else:
            self.btn_pin.configure(text="🔓 LIVRE", bg="#1a2333", fg=MUTED)

    def toggle_flag(self, key):
        if key == "enabled":
            self.enabled = not self.enabled
            val = self.enabled
        elif key == "auto_read_chat":
            self.auto_chat = not self.auto_chat
            val = self.auto_chat
        else:
            self.clip_watch = not self.clip_watch
            val = self.clip_watch
        self._update_pill_buttons()
        api_post("/api/config", {key: val})

    def _update_pill_buttons(self):
        self.btn_power.configure(
            text="🔊 VOZ: ON" if self.enabled else "🔇 VOZ: MUTE",
            bg="#0d2b22" if self.enabled else "#33121b",
            fg=NEON if self.enabled else "#ff7088"
        )
        self.btn_autochat.configure(
            text="💬 CHAT: AUTO" if self.auto_chat else "💬 CHAT: OFF",
            bg="#0d2b22" if self.auto_chat else "#121824",
            fg=NEON if self.auto_chat else MUTED
        )
        self.btn_clip.configure(
            text="📋 CTRL+C: ON" if self.clip_watch else "📋 CTRL+C: OFF",
            bg="#0d2b22" if self.clip_watch else "#121824",
            fg=NEON if self.clip_watch else MUTED
        )

    def on_voice_selected(self, event=None):
        sel_label = self.voice_var.get()
        for label, vid, pitch, rate in VOICES:
            if label == sel_label:
                self.scale_pitch.set(pitch)
                self.scale_rate.set(rate)
                self.on_slider_move()
                self.push_voice_config(voice_id=vid)
                break

    def on_slider_move(self, _=None):
        r = int(self.scale_rate.get())
        p = int(self.scale_pitch.get())
        v = int(self.scale_vol.get())
        self.lbl_rate_val.configure(text=f"{'+' if r >= 0 else ''}{r}%")
        self.lbl_pitch_val.configure(text=f"{'+' if p >= 0 else ''}{p}Hz")
        self.lbl_vol_val.configure(text=f"{v}%")

    def push_voice_config(self, voice_id=None):
        if not voice_id:
            sel_label = self.voice_var.get()
            voice_id = "pt-BR-AntonioNeural"
            for label, vid, _, _ in VOICES:
                if label == sel_label:
                    voice_id = vid
                    break
        r = int(self.scale_rate.get())
        p = int(self.scale_pitch.get())
        v = int(self.scale_vol.get())
        api_post("/api/config", {
            "voice": voice_id,
            "rate": f"{'+' if r >= 0 else ''}{r}%",
            "pitch": f"{'+' if p >= 0 else ''}{p}Hz",
            "volume": v
        })

    def cmd_read_last(self):
        api_post("/api/read_last")

    def cmd_test_voice(self):
        sample = "Fala clack! Mini player nativo do cook45 acoplado aqui do lado do chat. Pronto pra ação!"
        self.lbl_caption.configure(text=sample)
        api_post("/api/speak", {"text": sample, "source": "Mini Player", "play_on_host": True})

    def cmd_stop(self):
        api_post("/api/stop")

    def cmd_speak_manual(self):
        text = self.txt_manual.get("1.0", "end").strip()
        if not text:
            return
        self.lbl_caption.configure(text=text[:90])
        api_post("/api/speak", {"text": text, "source": "Manual", "play_on_host": True})

    def cmd_replay_selected(self, event=None):
        sel = self.lst_hist.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx < len(self.history_items):
            item = self.history_items[idx]
            txt = item.get("text", "")
            if txt:
                api_post("/api/speak", {"text": txt, "source": "Replay", "play_on_host": True})

    def _animate_scope(self):
        w = 310
        h = 62
        self.scope.delete("wave")
        pts = []
        color = AMBER if self.speaking else NEON
        for x in range(0, w, 4):
            env = math.sin((x / w) * math.pi)
            if self.speaking:
                amp = (math.sin(x * 0.08 + self.phase * 3.2) * 16 + math.cos(x * 0.19 - self.phase * 4.5) * 9) * env
            else:
                amp = math.sin(x * 0.04 + self.phase) * 2.5 * env
            pts.extend([x, h / 2 + amp])
        if len(pts) >= 4:
            self.scope.create_line(*pts, fill=color, width=2, tags="wave")
        self.phase += 0.22 if self.speaking else 0.06
        self.after(45, self._animate_scope)

    def _poll_daemon(self):
        def _bg():
            data = api_get("/api/state")
            if data and "state" in data:
                self.after(0, lambda: self._apply_state(data["state"]))
        threading.Thread(target=_bg, daemon=True).start()
        self.after(650, self._poll_daemon)

    def _apply_state(self, st):
        self.speaking = bool(st.get("speaking", False))
        self.enabled = bool(st.get("enabled", True))
        self.auto_chat = bool(st.get("auto_read_chat", True))
        self.clip_watch = bool(st.get("clipboard_watch", False))

        if not self.enabled:
            self.led_canvas.itemconfig(self.led_dot, fill=DANGER)
            self.lbl_status.configure(text="MUTE ATIVO (VOZ DESLIGADA)", fg=DANGER)
        elif self.speaking:
            self.led_canvas.itemconfig(self.led_dot, fill=AMBER)
            self.lbl_status.configure(text="FALANDO AGORA NO SEU ÁUDIO...", fg=AMBER)
        else:
            self.led_canvas.itemconfig(self.led_dot, fill=NEON)
            self.lbl_status.configure(text="ONLINE - ESCUTANDO CHAT DO COOK45", fg=NEON)

        curr = st.get("current_text") or ""
        if curr:
            self.lbl_caption.configure(text=curr[:85])

        self._update_pill_buttons()

        hist = st.get("history") or []
        if len(hist) != len(self.history_items):
            self.history_items = hist
            self.lst_hist.delete(0, "end")
            for h in hist:
                t_str = h.get("timestamp", "")
                txt = h.get("text", "")[:42]
                self.lst_hist.insert("end", f"[{t_str}] {txt}...")


if __name__ == "__main__":
    app = Cook45MiniPlayer()
    app.mainloop()
