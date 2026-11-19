"""Monitor de bateria de periféricos Bluetooth — ícone na bandeja do Windows.

Lê o nível de bateria que o Windows já expõe para dispositivos Bluetooth
(mouse, teclado, fones...) e avisa quando ficar crítico, com som opcional.
"""
import ctypes
import json
import os
import re
import subprocess
import sys
import threading
import winreg
import winsound
from pathlib import Path

import pystray
from PIL import Image, ImageDraw, ImageFont

APP_NAME = "BatteryMonitor"
CONFIG_DIR = Path(os.environ.get("APPDATA", Path.home())) / APP_NAME
CONFIG_FILE = CONFIG_DIR / "config.json"
DEFAULTS = {"language": "auto", "critical": 15, "sound_enabled": True, "sound_file": "", "interval": 60}

PS_SCRIPT = r"""
$k='{104EA319-6EE2-4701-BD47-8DDBF425BBE5} 2'
$all = Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -like 'BTH*' }
$all | ForEach-Object {
  $p = Get-PnpDeviceProperty -InstanceId $_.InstanceId -KeyName $k -ErrorAction SilentlyContinue
  if ($p -and $null -ne $p.Data) {
    $m = [regex]::Match($_.InstanceId.ToUpper(), '(?:DEV_|&0&)([0-9A-F]{12})(?:\b|_)')
    $addr = $m.Groups[1].Value
    $cod = 0; $hid = $false; $pname = $_.FriendlyName; $conn = $true
    if ($addr) {
      $par = $all | Where-Object { $_.InstanceId -like "*DEV_$addr*" -and $_.InstanceId -notlike '*{*' } | Select-Object -First 1
      if ($par) {
        $pname = $par.FriendlyName
        $cn = Get-PnpDeviceProperty -InstanceId $par.InstanceId -KeyName '{83DA6326-97A6-4088-9453-A1923F573B29} 15' -ErrorAction SilentlyContinue
        if ($cn -and $null -ne $cn.Data) { $conn = [bool]$cn.Data }
        $c = Get-PnpDeviceProperty -InstanceId $par.InstanceId -KeyName 'DEVPKEY_Bluetooth_ClassOfDevice' -ErrorAction SilentlyContinue
        if ($c -and $null -ne $c.Data) { $cod = [int]$c.Data }
      }
      $hid = [bool]($all | Where-Object { $_.InstanceId -like "*00001812*$addr*" })
    }
    [pscustomobject]@{ id=$_.InstanceId; name=$pname; level=[int]$p.Data; cod=$cod; hid=$hid; conn=$conn }
  }
} | ConvertTo-Json -Compress
"""


STRINGS = {
    "pt": {
        "none": "Nenhum dispositivo com bateria", "refresh": "Atualizar agora", "critical": "Nível crítico",
        "sound": "Som no alerta", "choose": "Escolher som (.wav)...", "default": "Usar som padrão",
        "test": "Testar alerta crítico", "startup": "Iniciar com o Windows", "quit": "Sair",
        "title": "Bateria crítica", "msg": "{name} está com {level}% de bateria. Hora de carregar!",
        "dialog": "Som de alerta", "device": "Dispositivo", "language": "Idioma", "auto": "Automático (Windows)",
    },
    "en": {
        "none": "No devices with battery", "refresh": "Refresh now", "critical": "Critical level",
        "sound": "Alert sound", "choose": "Choose sound (.wav)...", "default": "Use default sound",
        "test": "Test critical alert", "startup": "Start with Windows", "quit": "Quit",
        "title": "Critical battery", "msg": "{name} is at {level}% battery. Time to charge!",
        "dialog": "Alert sound", "device": "Device", "language": "Language", "auto": "Automatic (Windows)",
    },
    "es": {
        "none": "Ningún dispositivo con batería", "refresh": "Actualizar ahora", "critical": "Nivel crítico",
        "sound": "Sonido de alerta", "choose": "Elegir sonido (.wav)...", "default": "Usar sonido predeterminado",
        "test": "Probar alerta crítica", "startup": "Iniciar con Windows", "quit": "Salir",
        "title": "Batería crítica", "msg": "{name} tiene {level}% de batería. ¡Hora de cargar!",
        "dialog": "Sonido de alerta", "device": "Dispositivo", "language": "Idioma", "auto": "Automático (Windows)",
    },
}


def detect_language():
    """Idioma da interface do Windows (pt/en/es); usa inglês se não houver tradução."""
    try:
        lang = ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF
        return {0x16: "pt", 0x0A: "es", 0x09: "en"}.get(lang, "en")
    except Exception:
        return "en"


LANG = detect_language()
LANG_NAMES = {"pt": "Português", "en": "English", "es": "Español"}


def apply_language(choice):
    """choice: 'auto' ou código de idioma."""
    global LANG
    LANG = choice if choice in STRINGS else detect_language()


def t(key, **kw):
    return STRINGS[LANG][key].format(**kw)


def promote_tray_icon():
    """Fixa o ícone na barra (em vez de escondê-lo na seta ^).

    O Windows guarda a escolha em HKCU/Control Panel/NotifyIconSettings, uma entrada por .exe.
    Só mexe em entradas novas (sem IsPromoted), então quem desafixar manualmente é respeitado.
    """
    if not getattr(sys, "frozen", False):
        return
    exe = os.path.normcase(os.path.abspath(sys.executable))
    base = r"Control Panel\NotifyIconSettings"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, base) as root:
            for i in range(winreg.QueryInfoKey(root)[0]):
                try:
                    with winreg.OpenKey(root, winreg.EnumKey(root, i), 0,
                                        winreg.KEY_READ | winreg.KEY_SET_VALUE) as k:
                        path = os.path.normcase(winreg.QueryValueEx(k, "ExecutablePath")[0])
                        if path != exe:
                            continue
                        try:
                            winreg.QueryValueEx(k, "IsPromoted")
                        except FileNotFoundError:
                            winreg.SetValueEx(k, "IsPromoted", 0, winreg.REG_DWORD, 1)
                except OSError:
                    continue
    except OSError:
        pass


def load_config():
    cfg = dict(DEFAULTS)
    try:
        cfg.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
    except Exception:
        pass
    return cfg


def save_config(cfg):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def classify(name, cod, hid):
    n = (name or "").lower()
    if re.search(r"keyboard|teclado|\bkb\b|keys", n): return "keyboard"
    if re.search(r"mouse|\bmx\b", n): return "mouse"
    if re.search(r"pad|controller|joy|xbox|dualsense|dualshock", n): return "gamepad"
    if re.search(r"head|fone|buds|pods|ear|tws|qcy|anc", n): return "headphones"
    if re.search(r"speaker|caixa|soundbar|boom", n): return "speaker"
    major, minor = (cod >> 8) & 0x1F, (cod >> 2) & 0x3F
    if major == 4:
        return "speaker" if minor in (5, 7) else "headphones"
    if major == 5:
        if cod & 0x40: return "keyboard"
        if cod & 0x80: return "mouse"
        return "gamepad"
    if hid:
        return "mouse"
    return "generic"


def read_batteries():
    """Retorna {endereço: (nome, nível, tipo)} dos dispositivos Bluetooth com bateria."""
    out = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", PS_SCRIPT],
        capture_output=True, text=True, encoding="utf-8", creationflags=0x08000000, timeout=90,
    ).stdout.strip()
    if not out:
        return {}
    data = json.loads(out)
    if isinstance(data, dict):
        data = [data]
    devices = {}
    for d in data:
        if not d.get("conn", True) and not d.get("hid"):
            continue  # pareado mas não conectado (mouse/teclado HID são exceção: o Windows não reporta bem)
        m = re.search(r"(?:DEV_|&0&)([0-9A-F]{12})(?:\b|_)", d["id"].upper())
        addr = m.group(1) if m else d["id"]
        name = re.sub(r"\s*Hands-Free( AG)?$", "", d["name"] or t("device")).strip()
        devices[addr] = (name, d["level"], classify(name, d["cod"], d["hid"]))
    return devices


def _glyph(d, kind):
    """Desenha o ícone do periférico em branco numa tela 128x128 (área y 6..94)."""
    W = "white"
    if kind == "headphones":
        d.arc((22, 8, 106, 92), 180, 360, fill=W, width=10)
        d.rounded_rectangle((12, 46, 40, 92), 9, fill=W)
        d.rounded_rectangle((88, 46, 116, 92), 9, fill=W)
    elif kind == "mouse":
        d.rounded_rectangle((34, 6, 94, 96), 30, outline=W, width=8)
        d.line((64, 8, 64, 42), fill=W, width=7)
        d.line((34, 42, 94, 42), fill=W, width=7)
    elif kind == "keyboard":
        d.rounded_rectangle((6, 22, 122, 84), 10, outline=W, width=7)
        for y in (34, 50):
            for x in range(16, 108, 18):
                d.rectangle((x, y, x + 10, y + 8), fill=W)
        d.rectangle((32, 68, 96, 76), fill=W)
    elif kind == "speaker":
        d.rounded_rectangle((26, 6, 102, 96), 14, outline=W, width=8)
        d.ellipse((46, 18, 82, 40), fill=W)
        d.ellipse((38, 48, 90, 88), outline=W, width=8)
    elif kind == "gamepad":
        d.rounded_rectangle((6, 24, 122, 90), 30, fill=W)
        d.rectangle((26, 44, 54, 54), fill="black"); d.rectangle((35, 35, 45, 63), fill="black")
        d.ellipse((82, 38, 94, 50), fill="black"); d.ellipse((98, 52, 110, 64), fill="black")
    else:  # genérico: círculo com ponto
        d.ellipse((20, 6, 108, 94), outline=W, width=9)
        d.ellipse((50, 36, 78, 64), fill=W)


def make_icon(level, critical, kind="generic"):
    S = 128
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)
    _glyph(dr, kind)
    # barra de nível na base: verde / laranja / vermelha
    color = (120, 120, 120) if level is None else (
        (235, 60, 60) if level <= critical else (240, 170, 30) if level <= 30 else (50, 200, 90))
    dr.rounded_rectangle((6, 104, 122, 124), 9, fill=(70, 70, 70, 255))
    if level:
        w = max(20, int(116 * level / 100))
        dr.rounded_rectangle((6, 104, 6 + w, 124), 9, fill=color + (255,))
    return img.resize((64, 64), Image.LANCZOS)


class App:
    def __init__(self):
        self.cfg = load_config()
        apply_language(self.cfg["language"])
        self.devices = {}
        self.alerted = set()
        self.stop = threading.Event()
        self.icons = {}  # endereço -> ícone de bandeja (um por dispositivo)
        self.placeholder = None
        self.lock = threading.Lock()

    # ---------- sons e alertas ----------
    def play_sound(self):
        f = self.cfg["sound_file"]
        try:
            if f and Path(f).is_file():
                winsound.PlaySound(f, winsound.SND_FILENAME | winsound.SND_ASYNC)
            else:
                winsound.PlaySound("SystemHand", winsound.SND_ALIAS | winsound.SND_ASYNC)
        except Exception:
            winsound.MessageBeep(winsound.MB_ICONHAND)

    def check_alerts(self):
        crit = self.cfg["critical"]
        for addr, (name, level, _k) in self.devices.items():
            if level <= crit and addr not in self.alerted:
                self.alerted.add(addr)
                try:
                    self.icons[addr].notify(t("msg", name=name, level=level), t("title"))
                except Exception:
                    pass
                if self.cfg["sound_enabled"]:
                    self.play_sound()
            elif level > crit + 5:
                self.alerted.discard(addr)  # recarregou: rearma o aviso

    # ---------- atualização ----------
    def refresh(self, *_):
        try:
            self.devices = read_batteries()
        except Exception:
            return
        self.apply_ui()
        self.check_alerts()

    def apply_ui(self):
        """Redesenha ícones e menus com os dados já lidos (rápido, sem consultar o Windows)."""
        crit = self.cfg["critical"]
        created = False
        with self.lock:
            if self.stop.is_set():
                return
            for addr, (name, lv, kind) in self.devices.items():
                img, title = make_icon(lv, crit, kind), f"{name}: {lv}%"
                ic = self.icons.get(addr)
                if ic is None:
                    ic = pystray.Icon(f"{APP_NAME}-{addr}", img, title, self.build_menu())
                    self.icons[addr] = ic
                    ic.run_detached()
                    created = True
                else:
                    ic.icon, ic.title, ic.menu = img, title, self.build_menu()
                    ic.update_menu()
            for addr in [a for a in self.icons if a not in self.devices]:
                self.icons.pop(addr).stop()
            if not self.devices and self.placeholder is None:
                self.placeholder = pystray.Icon(APP_NAME, make_icon(None, crit),
                                                t("none"), self.build_menu())
                self.placeholder.run_detached()
            elif self.devices and self.placeholder is not None:
                self.placeholder.stop()
                self.placeholder = None
        if created:
            self.stop.wait(1.5)  # deixa os ícones aparecerem antes de notificar
            promote_tray_icon()

    def apply_ui_async(self):
        """Usado pelos itens do menu: nunca bloqueia o clique."""
        threading.Thread(target=self.apply_ui, daemon=True).start()

    def loop(self):
        while not self.stop.is_set():
            self.refresh()
            self.stop.wait(self.cfg["interval"])

    # ---------- menu ----------
    def build_menu(self):
        Item, Menu = pystray.MenuItem, pystray.Menu
        items = [Item(f"{n}: {lv}%", None, enabled=False) for n, lv, _k in self.devices.values()]
        if not items:
            items = [Item(t("none"), None, enabled=False)]
        items += [
            Menu.SEPARATOR,
            Item(t("refresh"), lambda: threading.Thread(target=self.refresh, daemon=True).start()),
            Item(t("critical"), Menu(*[
                Item(f"{v}%", self.set_critical(v), checked=lambda _i, v=v: self.cfg["critical"] == v, radio=True)
                for v in (10, 15, 20, 25, 30)])),
            Item(t("sound"), self.toggle_sound, checked=lambda _i: self.cfg["sound_enabled"]),
            Item(t("choose"), self.choose_sound),
            Item(t("default"), self.reset_sound),
            Item(t("test"), self.test_alert),
            Item(t("language"), Menu(
                Item(t("auto"), self.set_language("auto"), checked=lambda _i: self.cfg["language"] == "auto", radio=True),
                *[Item(n, self.set_language(c), checked=lambda _i, c=c: self.cfg["language"] == c, radio=True)
                  for c, n in LANG_NAMES.items()])),
            Menu.SEPARATOR,
            Item(t("startup"), self.toggle_startup, checked=lambda _i: self.startup_enabled()),
            Item(t("quit"), self.quit),
        ]
        return Menu(*items)

    def test_alert(self):
        ic = next(iter(self.icons.values()), None) or self.placeholder
        try:
            ic.notify(t("msg", name=next(iter(self.devices.values()), (t("device"),))[0], level=5), t("title"))
        except Exception:
            pass
        if self.cfg["sound_enabled"]:
            self.play_sound()

    def set_language(self, code):
        def fn():
            self.cfg["language"] = code
            save_config(self.cfg)
            apply_language(code)
            self.apply_ui_async()
        return fn

    def set_critical(self, v):
        def fn():
            self.cfg["critical"] = v
            save_config(self.cfg)
            self.alerted.clear()
            self.apply_ui_async()
            threading.Thread(target=self.check_alerts, daemon=True).start()
        return fn

    def toggle_sound(self):
        self.cfg["sound_enabled"] = not self.cfg["sound_enabled"]
        save_config(self.cfg)

    def choose_sound(self):
        def pick():
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            f = filedialog.askopenfilename(title=t("dialog"), filetypes=[("WAV", "*.wav")])
            root.destroy()
            if f:
                self.cfg["sound_file"] = f
                save_config(self.cfg)
                self.play_sound()
        threading.Thread(target=pick, daemon=True).start()

    def reset_sound(self):
        self.cfg["sound_file"] = ""
        save_config(self.cfg)

    # ---------- iniciar com o Windows ----------
    RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

    def startup_enabled(self):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.RUN_KEY) as k:
                winreg.QueryValueEx(k, APP_NAME)
                return True
        except OSError:
            return False

    def toggle_startup(self):
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if self.startup_enabled():
                winreg.DeleteValue(k, APP_NAME)
            else:
                if getattr(sys, "frozen", False):
                    cmd = f'"{sys.executable}"'
                else:
                    pyw = Path(sys.executable).with_name("pythonw.exe")
                    cmd = f'"{pyw}" "{Path(__file__).resolve()}"'
                winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, cmd)

    def quit(self):
        with self.lock:
            self.stop.set()
            for ic in list(self.icons.values()) + ([self.placeholder] if self.placeholder else []):
                ic.stop()

    def run(self):
        threading.Thread(target=self.loop, daemon=True).start()
        self.stop.wait()
        import time
        time.sleep(0.5)


if __name__ == "__main__":
    # instância única
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\BatteryMonitorSingleton")
    if ctypes.windll.kernel32.GetLastError() == 183:
        sys.exit(0)
    App().run()
