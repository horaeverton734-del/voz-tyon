import os
import sys
import time
import ctypes
import subprocess

user32 = ctypes.windll.user32

def find_edge_or_chrome():
    # Prioriza Microsoft Edge para rodar em processo 100% separado do Chrome principal do clack
    candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return "msedge"

def lock_mini_player_topmost(pinned: bool = True):
    HWND_TOPMOST = -1
    HWND_NOTOPMOST = -2
    SWP_SHOWWINDOW = 0x0040
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    matched = []

    def enum_cb(hwnd, lparam):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                title = buf.value
                if "MINI PLAYER COOK45" in title or "TYON-V45 // MINI" in title:
                    matched.append(hwnd)
        return True

    cb = WNDENUMPROC(enum_cb)
    user32.EnumWindows(cb, 0)

    screen_w = user32.GetSystemMetrics(0)
    width, height = 368, 560
    x = max(10, screen_w - width - 18)
    y = 65
    z_flag = HWND_TOPMOST if pinned else HWND_NOTOPMOST

    for hwnd in matched:
        user32.SetWindowPos(hwnd, z_flag, x, y, width, height, SWP_SHOWWINDOW)
    return len(matched)

def main():
    exe = find_edge_or_chrome()
    # Usa o link da nuvem do Render se solicitado, ou o servidor local híbrido
    url = "https://voz-tyon.onrender.com/?popup=1"
    if "--local" in sys.argv:
        url = "http://localhost:8090/?popup=1"

    profile_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mini_profile_cloud")
    os.makedirs(profile_dir, exist_ok=True)

    screen_w = user32.GetSystemMetrics(0)
    width, height = 368, 560
    x = max(10, screen_w - width - 18)
    y = 65

    args = [
        exe,
        f"--app={url}",
        f"--user-data-dir={profile_dir}",
        f"--window-size={width},{height}",
        f"--window-position={x},{y}",
        "--disable-extensions",
        "--no-first-run"
    ]

    subprocess.Popen(args)

    # Aguarda a janela abrir e trava como Always-On-Top (HWND_TOPMOST)
    for _ in range(35):
        time.sleep(0.25)
        if lock_mini_player_topmost(True) > 0:
            time.sleep(0.4)
            lock_mini_player_topmost(True)
            print("[MINI PLAYER CLOUD] Janela independente acoplada e fixada Sempre no Topo (HWND_TOPMOST)!")
            break

if __name__ == "__main__":
    main()
