import numpy as np
import threading
import queue
import time
import json
import os
import sys
import tkinter as tk
from faster_whisper import WhisperModel
from PIL import Image, ImageDraw, ImageFont
import pyaudiowpatch as pyaudio

try:
    import win32gui
    import win32con
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False
    print("pywin32 не установлен — режим 'сквозных кликов' недоступен.")

try:
    import keyboard
    HAS_KEYBOARD = True
except ImportError:
    HAS_KEYBOARD = False
    print("Для глобальных горячих клавиш установите: pip install keyboard")

try:
    import pystray
    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False
    print("Для трея установите: pip install pystray")

# ============ Пути и константы ============
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, 'config.json')
ICON_PATH = os.path.join(BASE_DIR, 'app_icon.ico')

APP_NAME = "Real-time online subtitles"
APP_AUTHORS = "Nataly Taly & Echo"
APP_VERSION = "1.0"

# ============ Настройки по умолчанию ============
DEFAULT_CONFIG = {
    "model": "large-v3",
    "language": "ru",
    "font_size": 18,
    "alpha": 0.75,
    "color_index": 0,
    "window_geometry": "",
    "max_lines": 10,
    "capture_device": "",
    "blacklist": [
        "субтитры сделал",
        "субтитры подогнал",
        "dimatorzok",
        "симон",
        "перевод:",
        "синхронизация:",
        "редактор:",
        "корректор:",
        "продолжение следует",
        "подпишись на канал",
        "подписывайтесь на канал",
        "спасибо за просмотр",
        "ставьте лайк",
    ],
}

COLOR_PALETTE = [
    ("Жёлтый",   '#ffb84d'),
    ("Зелёный",  '#00ff44'),
    ("Красный",  '#ff2a2a'),
    ("Голубой",  '#00e5ff'),
    ("Белый",    '#ffffff'),
]

# ============ Config ============
def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
            for k, v in DEFAULT_CONFIG.items():
                if k not in data:
                    data[k] = v
            return data
        except Exception as e:
            print(f"Ошибка чтения config.json: {e}. Использую дефолт.")
    return dict(DEFAULT_CONFIG)

def save_config(cfg):
    try:
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Ошибка сохранения config.json: {e}")

CFG = load_config()
BLACKLIST = [s.lower() for s in CFG.get("blacklist", [])]

def is_blacklisted(text):
    if not BLACKLIST:
        return False
    low = text.lower()
    return any(bad in low for bad in BLACKLIST)

MODEL_SIZE = CFG["model"]
LANGUAGE = CFG["language"]
FONT_SIZE = CFG["font_size"]
ALPHA = CFG["alpha"]
COLOR_INDEX = CFG["color_index"]
MAX_LINES = CFG["max_lines"]
SAVED_GEOMETRY = CFG["window_geometry"]

DEVICE = "cuda"
COMPUTE_TYPE = "float16"
SAMPLE_RATE = 16000
CHUNK_DURATION = 3.0

BG_COLOR = 'black'
PANEL_BG = '#0a0a0a'
PANEL_BG_ACTIVE = '#1a1a1a'
FONT_FAMILY = 'Segoe UI'
FONT_STYLE = 'bold'
ALPHA_STEP = 0.05
ALPHA_MIN = 0.1
ALPHA_MAX = 1.0

PANEL_WIDTH = 42
ACCENT_COLOR = (255, 184, 77, 255)

# ============ Загрузка модели ============
print(f"Загрузка модели {MODEL_SIZE} на {DEVICE}...")
model = WhisperModel(MODEL_SIZE, device=DEVICE, compute_type=COMPUTE_TYPE)
print("Модель загружена.\n")

# ============ Поиск loopback через PyAudioWPatch ============
def find_loopback_device(cfg):
    p = pyaudio.PyAudio()
    user_device = cfg.get("capture_device", "").strip()

    if user_device:
        for lb in p.get_loopback_device_info_generator():
            if user_device.lower() in lb['name'].lower():
                print(f"[config] Найдено устройство: {lb['name']}")
                return p, lb
        print(f"[config] '{user_device}' не найдено, авто-выбор.")

    try:
        default_lb = p.get_default_wasapi_loopback()
        print(f"Loopback по умолчанию: {default_lb['name']}")
        return p, default_lb
    except Exception as e:
        print(f"Default loopback недоступен: {e}")

    for lb in p.get_loopback_device_info_generator():
        print(f"Использую первый доступный loopback: {lb['name']}")
        return p, lb

    print("Loopback-устройства не найдены.")
    p.terminate()
    sys.exit(1)

audio_p, loopback_device = find_loopback_device(CFG)
print(f"Захват звука: {loopback_device['name']}")
print(f"Частота устройства: {loopback_device['defaultSampleRate']} Гц\n")

# ============ Очередь аудио ============
audio_queue = queue.Queue()

# ============ Иконки ============
def create_tray_image():
    size = 64
    img = Image.new('RGBA', (size, size), (0, 0, 0, 255))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arialbd.ttf", 48)
    except:
        font = ImageFont.load_default()
    text = "S"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw.text(((size - tw) / 2 - bbox[0], (size - th) / 2 - bbox[1]),
              text, fill=ACCENT_COLOR, font=font)
    return img

def create_app_icon_image(size=256):
    img = Image.new('RGBA', (size, size), (0, 0, 0, 255))
    draw = ImageDraw.Draw(img)
    margin = size // 12
    ring_width = size // 14
    draw.ellipse(
        [margin, margin, size - margin, size - margin],
        outline=ACCENT_COLOR, width=ring_width
    )
    try:
        font_size = int(size * 0.55)
        font = ImageFont.truetype("arialbd.ttf", font_size)
    except:
        font = ImageFont.load_default()
    text = "S"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw.text(
        ((size - tw) / 2 - bbox[0], (size - th) / 2 - bbox[1]),
        text, fill=ACCENT_COLOR, font=font
    )
    return img

def ensure_icon_file():
    if not os.path.exists(ICON_PATH):
        try:
            img = create_app_icon_image(256)
            img.save(
                ICON_PATH, format='ICO',
                sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
            )
            print(f"Иконка создана: {ICON_PATH}")
        except Exception as e:
            print(f"Не удалось создать иконку: {e}")

# ============ Оверлей ============
class SubtitleOverlay:
    def __init__(self):
        ensure_icon_file()

        self.root = tk.Tk()
        self.root.title(APP_NAME)
        try:
            self.root.iconbitmap(ICON_PATH)
        except Exception as e:
            print(f"Не удалось установить иконку окна: {e}")

        self.root.overrideredirect(True)
        self.root.attributes('-topmost', True)
        self.alpha = ALPHA
        self.root.attributes('-alpha', self.alpha)
        self.root.configure(bg=BG_COLOR)

        if SAVED_GEOMETRY:
            try:
                self.root.geometry(SAVED_GEOMETRY)
            except:
                self._set_default_geometry()
        else:
            self._set_default_geometry()

        self.root.focus_force()

        self.font_size = FONT_SIZE
        self.clickthrough = False
        self.color_index = COLOR_INDEX
        self.text_color = COLOR_PALETTE[self.color_index][1]
        self.language = LANGUAGE
        self.tray_icon = None
        self.paused = False

        container = tk.Frame(self.root, bg=BG_COLOR)
        container.pack(fill=tk.BOTH, expand=True)
        container.grid_columnconfigure(0, weight=1)
        container.grid_columnconfigure(1, weight=0, minsize=PANEL_WIDTH)
        container.grid_rowconfigure(0, weight=1)

        self.text = tk.Text(
            container, wrap=tk.WORD,
            bg=BG_COLOR, fg=self.text_color,
            font=(FONT_FAMILY, self.font_size, FONT_STYLE),
            bd=0, highlightthickness=0,
            insertbackground=self.text_color,
            selectbackground='#444444', selectforeground=self.text_color,
        )
        self.text.grid(row=0, column=0, sticky='nsew', padx=(10, 5), pady=10)
        self.text.config(state=tk.DISABLED)

        self.lines = []

        self.panel = tk.Frame(container, bg=PANEL_BG, width=PANEL_WIDTH)
        self.panel.grid(row=0, column=1, sticky='ns', padx=(0, 5), pady=10)
        self.panel.grid_propagate(False)

        self.drag_handle = tk.Label(
            self.panel, text="⠿", bg=PANEL_BG, fg=self.text_color,
            font=('Segoe UI', 14, 'bold'), cursor='fleur'
        )
        self.drag_handle.pack(side=tk.TOP, pady=(6, 8))

        def make_btn(text, cmd):
            b = tk.Button(
                self.panel, text=text, command=cmd,
                bg=PANEL_BG, fg=self.text_color, bd=0,
                font=('Segoe UI', 10, 'bold'),
                activebackground=PANEL_BG_ACTIVE, activeforeground=self.text_color,
                relief=tk.FLAT, cursor='hand2'
            )
            b.pack(side=tk.TOP, pady=2, padx=4, fill=tk.X)
            return b

        self.buttons = []
        self.buttons.append(make_btn("A+", lambda: self.change_font_size(2)))
        self.buttons.append(make_btn("A−", lambda: self.change_font_size(-2)))
        self.buttons.append(make_btn("☀+", lambda: self.change_alpha(+ALPHA_STEP)))
        self.buttons.append(make_btn("☀−", lambda: self.change_alpha(-ALPHA_STEP)))
        self.buttons.append(make_btn("🎨", self.cycle_color))
        self.btn_pause = make_btn("⏸", self.toggle_pause)
        self.buttons.append(self.btn_pause)
        self.buttons.append(make_btn("?", self.show_help))
        self.buttons.append(make_btn("–", self.minimize_to_tray))
        self.buttons.append(make_btn("✕", self.quit_app))

        for widget in (self.panel, self.drag_handle):
            widget.bind('<Button-1>', self.start_move)
            widget.bind('<B1-Motion>', self.do_move)

        self._drag_x = 0
        self._drag_y = 0

        self.resize_grip = tk.Label(
            container, text="◢", bg=BG_COLOR, fg=self.text_color,
            font=('Segoe UI', 12, 'bold'), cursor='bottom_right_corner'
        )
        self.resize_grip.place(relx=1.0, rely=1.0, anchor='se', x=-2, y=-2)
        self.resize_grip.bind('<Button-1>', self.start_resize)
        self.resize_grip.bind('<B1-Motion>', self.do_resize)
        self._resize_x = 0
        self._resize_y = 0

        self.menu = tk.Menu(
            self.root, tearoff=0, bg='black', fg=self.text_color,
            activebackground='#333333', activeforeground=self.text_color,
            font=('Segoe UI', 10)
        )
        self.menu.add_command(label="Копировать выделенное", command=self.copy_selection)
        self.menu.add_command(label="Копировать всё", command=self.copy_all)
        self.menu.add_command(label="Копировать последнюю строку", command=self.copy_last_line)
        self.menu.add_separator()
        self.menu.add_command(label="⏸ Пауза / ▶ Возобновить (Ctrl+Alt+Shift+P)", command=self.toggle_pause)
        self.menu.add_separator()
        self.menu.add_command(label="Шрифт больше (A+)", command=lambda: self.change_font_size(2))
        self.menu.add_command(label="Шрифт меньше (A−)", command=lambda: self.change_font_size(-2))
        self.menu.add_separator()
        self.menu.add_command(label="Ярче (☀+)", command=lambda: self.change_alpha(+ALPHA_STEP))
        self.menu.add_command(label="Прозрачнее (☀−)", command=lambda: self.change_alpha(-ALPHA_STEP))
        self.menu.add_separator()

        self.color_menu = tk.Menu(self.menu, tearoff=0, bg='black', fg=self.text_color,
                                  activebackground='#333333', activeforeground=self.text_color,
                                  font=('Segoe UI', 10))
        for i, (name, code) in enumerate(COLOR_PALETTE):
            self.color_menu.add_command(
                label=f"● {name}",
                foreground=code,
                command=lambda idx=i: self.set_color(idx)
            )
        self.menu.add_cascade(label="Цвет текста", menu=self.color_menu)

        self.lang_menu = tk.Menu(self.menu, tearoff=0, bg='black', fg=self.text_color,
                                 activebackground='#333333', activeforeground=self.text_color,
                                 font=('Segoe UI', 10))
        for code, name in [("ru", "Русский"), ("en", "English"), ("auto", "Авто")]:
            self.lang_menu.add_command(label=name, command=lambda c=code: self.set_language(c))
        self.menu.add_cascade(label="Язык", menu=self.lang_menu)

        self.menu.add_separator()
        self.menu.add_command(label="❓ Справка (?)", command=self.show_help)
        self.menu.add_separator()
        self.menu.add_command(label=f"Модель: {MODEL_SIZE}", state=tk.DISABLED)
        self.menu.add_separator()
        self.menu.add_command(label="Свернуть в трей (–)", command=self.minimize_to_tray)
        self.menu.add_command(label="Сквозной режим (Ctrl+Alt+Shift+C)", command=self.toggle_clickthrough)
        self.menu.add_separator()
        self.menu.add_command(label="Выход (Ctrl+Alt+Shift+Q)", command=self.quit_app)

        self.text.bind('<Button-3>', self.show_menu)
        self.panel.bind('<Button-3>', self.show_menu)
        self.drag_handle.bind('<Button-3>', self.show_menu)

        self.root.bind_all('<Control-Alt-Shift-Q>', lambda e: self.quit_app())
        self.root.bind_all('<Control-Alt-Shift-C>', lambda e: self.toggle_clickthrough())
        self.root.bind_all('<Control-Alt-Shift-M>', lambda e: self.minimize_to_tray())
        self.root.bind_all('<Control-Alt-Shift-P>', lambda e: self.toggle_pause())
        self.root.bind_all('<Control-Alt-Shift-H>', lambda e: self.toggle_visibility())
        self.root.bind_all('<Control-Alt-Up>', lambda e: self.change_font_size(2))
        self.root.bind_all('<Control-Alt-Down>', lambda e: self.change_font_size(-2))
        self.root.bind_all('<Control-Alt-Prior>', lambda e: self.change_alpha(+ALPHA_STEP))
        self.root.bind_all('<Control-Alt-Next>',  lambda e: self.change_alpha(-ALPHA_STEP))
        for i in range(5):
            self.root.bind_all(f'<Control-Alt-Shift-{i+1}>',
                               lambda e, idx=i: self.set_color(idx))

        if HAS_KEYBOARD:
            keyboard.add_hotkey('ctrl+alt+shift+q', lambda: self.root.after(0, self.quit_app))
            keyboard.add_hotkey('ctrl+alt+shift+c', lambda: self.root.after(0, self.toggle_clickthrough))
            keyboard.add_hotkey('ctrl+alt+shift+m', lambda: self.root.after(0, self.minimize_to_tray))
            keyboard.add_hotkey('ctrl+alt+shift+p', lambda: self.root.after(0, self.toggle_pause))
            keyboard.add_hotkey('ctrl+alt+shift+h', lambda: self.root.after(0, self.toggle_visibility))
            keyboard.add_hotkey('ctrl+alt+up',      lambda: self.root.after(0, lambda: self.change_font_size(2)))
            keyboard.add_hotkey('ctrl+alt+down',    lambda: self.root.after(0, lambda: self.change_font_size(-2)))
            keyboard.add_hotkey('ctrl+alt+page up',   lambda: self.root.after(0, lambda: self.change_alpha(+ALPHA_STEP)))
            keyboard.add_hotkey('ctrl+alt+page down', lambda: self.root.after(0, lambda: self.change_alpha(-ALPHA_STEP)))

        self.visible = True
        self.root.protocol("WM_DELETE_WINDOW", self.quit_app)

    def _set_default_geometry(self):
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        win_w, win_h = 900, 350
        x = (screen_w - win_w) // 2
        y = screen_h - win_h - 60
        self.root.geometry(f"{win_w}x{win_h}+{x}+{y}")

    def start_move(self, event):
        self._drag_x = event.x_root
        self._drag_y = event.y_root

    def do_move(self, event):
        dx = event.x_root - self._drag_x
        dy = event.y_root - self._drag_y
        x = self.root.winfo_x() + dx
        y = self.root.winfo_y() + dy
        self.root.geometry(f"+{x}+{y}")
        self._drag_x = event.x_root
        self._drag_y = event.y_root

    def start_resize(self, event):
        self._resize_x = event.x_root
        self._resize_y = event.y_root

    def do_resize(self, event):
        dx = event.x_root - self._resize_x
        dy = event.y_root - self._resize_y
        new_w = self.root.winfo_width() + dx
        new_h = self.root.winfo_height() + dy
        if new_w > 300 and new_h > 100:
            self.root.geometry(f"{new_w}x{new_h}")
        self._resize_x = event.x_root
        self._resize_y = event.y_root

    def change_font_size(self, delta):
        self.font_size = max(10, min(72, self.font_size + delta))
        self.text.config(font=(FONT_FAMILY, self.font_size, FONT_STYLE))
        self.save_current_config()

    def change_alpha(self, delta):
        self.alpha = max(ALPHA_MIN, min(ALPHA_MAX, self.alpha + delta))
        self.root.attributes('-alpha', self.alpha)
        self.save_current_config()

    def set_color(self, index):
        if 0 <= index < len(COLOR_PALETTE):
            self.color_index = index
            name, code = COLOR_PALETTE[index]
            self.text_color = code
            self.text.config(fg=code, insertbackground=code, selectforeground=code)
            for b in self.buttons:
                b.config(fg=code, activeforeground=code)
            self.drag_handle.config(fg=code)
            self.resize_grip.config(fg=code)
            self.menu.config(fg=code, activeforeground=code)
            self.color_menu.config(fg=code, activeforeground=code)
            self.lang_menu.config(fg=code, activeforeground=code)
            self.save_current_config()

    def cycle_color(self):
        self.set_color((self.color_index + 1) % len(COLOR_PALETTE))

    def set_language(self, code):
        self.language = code
        CFG["language"] = code
        save_config(CFG)

    def toggle_pause(self):
        self.paused = not self.paused
        self.btn_pause.config(text="▶" if self.paused else "⏸")
        if not self.paused:
            self._render_lines()

    def toggle_clickthrough(self):
        if not HAS_WIN32:
            return
        hwnd = self.root.winfo_id()
        parent = win32gui.GetParent(hwnd)
        target = parent if parent else hwnd
        ex_style = win32gui.GetWindowLong(target, win32con.GWL_EXSTYLE)
        if self.clickthrough:
            ex_style &= ~win32con.WS_EX_TRANSPARENT
            self.clickthrough = False
        else:
            ex_style |= win32con.WS_EX_LAYERED | win32con.WS_EX_TRANSPARENT
            self.clickthrough = True
        win32gui.SetWindowLong(target, win32con.GWL_EXSTYLE, ex_style)

    def copy_selection(self):
        try:
            selected = self.text.get(tk.SEL_FIRST, tk.SEL_LAST)
            self.root.clipboard_clear()
            self.root.clipboard_append(selected)
        except tk.TclError:
            pass

    def copy_all(self):
        text = "\n".join(self.lines)
        self.root.clipboard_clear()
        self.root.clipboard_append(text)

    def copy_last_line(self):
        if self.lines:
            self.root.clipboard_clear()
            self.root.clipboard_append(self.lines[-1])

    def toggle_visibility(self, event=None):
        if self.visible:
            self.root.withdraw()
        else:
            self.root.deiconify()
            self.root.attributes('-topmost', True)
        self.visible = not self.visible

    def show_help(self):
        win = tk.Toplevel(self.root)
        win.title(f"Справка — {APP_NAME}")
        win.geometry("680x680")
        win.minsize(500, 500)
        win.configure(bg='#1a1a1a')
        try:
            win.iconbitmap(ICON_PATH)
        except:
            pass

        tk.Label(win, text=APP_NAME, bg='#1a1a1a', fg='#ffb84d',
                 font=('Segoe UI', 16, 'bold')).pack(pady=(15, 3))
        tk.Label(win, text=f"Версия {APP_VERSION}", bg='#1a1a1a', fg='#aaaaaa',
                 font=('Segoe UI', 9, 'italic')).pack(pady=(0, 2))
        tk.Label(win, text=f"Авторы: {APP_AUTHORS}", bg='#1a1a1a', fg='#cccccc',
                 font=('Segoe UI', 10, 'italic')).pack(pady=(0, 12))

        help_text = (
            "ГОРЯЧИЕ КЛАВИШИ\n"
            "─────────────────────────────────────────────\n"
            "  Ctrl+Alt+Shift+C     — сквозной режим\n"
            "  Ctrl+Alt+Shift+M     — свернуть в трей\n"
            "  Ctrl+Alt+Shift+P     — пауза / возобновить\n"
            "  Ctrl+Alt+Shift+H     — скрыть / показать оверлей\n"
            "  Ctrl+Alt+Shift+Q     — выход\n"
            "  Ctrl+Alt+↑ / ↓       — размер шрифта\n"
            "  Ctrl+Alt+PgUp / PgDn — прозрачность\n"
            "  Ctrl+Alt+Shift+1..5  — цвет текста\n"
            "\n"
            "КНОПКИ НА ПАНЕЛИ\n"
            "─────────────────────────────────────────────\n"
            "  ⠿   — перетаскивание\n"
            "  A+  — увеличить шрифт\n"
            "  A−  — уменьшить шрифт\n"
            "  ☀+  — ярче\n"
            "  ☀−  — прозрачнее\n"
            "  🎨  — сменить цвет\n"
            "  ⏸   — пауза / ▶ продолжить\n"
            "  ?   — справка\n"
            "  –   — свернуть в трей\n"
            "  ✕   — выход\n"
            "\n"
            "МЫШЬ\n"
            "─────────────────────────────────────────────\n"
            "  ЛКМ по тексту       — выделить\n"
            "  Ctrl+C              — копировать выделенное\n"
            "  ПКМ                 — контекстное меню\n"
            "  Уголок ◢ (справа)   — изменить размер окна\n"
            "  Панель / ⠿          — перетаскивание\n"
            "\n"
            "НАСТРОЙКА ЗАХВАТА ЗВУКА\n"
            "─────────────────────────────────────────────\n"
            "  По умолчанию — loopback динамиков.\n"
            "  Для ручного выбора открой config.json и впиши\n"
            "  часть имени устройства в \"capture_device\".\n"
            "  Например: \"Realtek\", \"CABLE Input\", \"GA271\".\n"
            "\n"
            "ФАЙЛЫ\n"
            "─────────────────────────────────────────────\n"
            "  config.json   — настройки\n"
            "  app_icon.ico  — иконка приложения\n"
        )

        text_widget = tk.Text(win, wrap=tk.WORD, font=('Consolas', 10),
                              bg='#0a0a0a', fg='#e0e0e0', bd=0,
                              highlightthickness=0, padx=12, pady=10)
        text_widget.pack(fill=tk.BOTH, expand=True, padx=15, pady=(0, 10))
        text_widget.insert(tk.END, help_text)
        text_widget.config(state=tk.DISABLED)

        tk.Button(win, text="Закрыть", command=win.destroy,
                  bg='#1a1a1a', fg='#ffb84d', bd=0,
                  font=('Segoe UI', 11, 'bold'),
                  activebackground='#333333', activeforeground='#ffb84d',
                  padx=20, pady=6, cursor='hand2').pack(pady=(0, 15))

    def show_menu(self, event):
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    def minimize_to_tray(self):
        if not HAS_TRAY:
            return
        self.root.withdraw()
        self._create_tray_icon()

    def _create_tray_icon(self):
        if self.tray_icon is not None:
            return
        image = create_tray_image()
        menu = pystray.Menu(
            pystray.MenuItem("Показать", self._restore_from_tray, default=True),
            pystray.MenuItem("Выход", self._quit_from_tray),
        )
        self.tray_icon = pystray.Icon(APP_NAME, image, APP_NAME, menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def _restore_from_tray(self, icon=None, item=None):
        if self.tray_icon is not None:
            try:
                self.tray_icon.stop()
            except:
                pass
            self.tray_icon = None
        self.root.after(0, self._show_window)

    def _show_window(self):
        self.root.deiconify()
        self.root.attributes('-topmost', True)
        self.visible = True

    def _quit_from_tray(self, icon=None, item=None):
        if self.tray_icon is not None:
            try:
                self.tray_icon.stop()
            except:
                pass
        self.root.after(0, self.quit_app)

    def save_current_config(self):
        CFG["font_size"] = self.font_size
        CFG["alpha"] = self.alpha
        CFG["color_index"] = self.color_index
        CFG["window_geometry"] = self.root.geometry()
        CFG["language"] = self.language
        save_config(CFG)

    def quit_app(self):
        try:
            self.save_current_config()
        except:
            pass
        if HAS_KEYBOARD:
            try:
                keyboard.unhook_all()
            except:
                pass
        if self.tray_icon is not None:
            try:
                self.tray_icon.stop()
            except:
                pass
        try:
            audio_p.terminate()
        except:
            pass
        try:
            self.root.destroy()
        except:
            pass
        os._exit(0)

    def add_line(self, text):
        self.root.after(0, self._add_line_main, text)

    def _add_line_main(self, text):
        self.lines.append(text)
        if len(self.lines) > MAX_LINES:
            self.lines = self.lines[-MAX_LINES:]
        if self.paused:
            return
        self._render_lines()

    def _render_lines(self):
        self.text.config(state=tk.NORMAL)
        self.text.delete('1.0', tk.END)
        self.text.insert(tk.END, "\n".join(self.lines))
        self.text.see(tk.END)
        self.text.config(state=tk.DISABLED)

    def run(self):
        self.root.mainloop()
             
# ============ Захват аудио через PyAudioWPatch ============
def capture_audio():
    """Захват звука через WASAPI loopback (PyAudioWPatch)."""
    device_rate = int(loopback_device['defaultSampleRate'])
    channels = loopback_device['maxInputChannels']

    # Ресемплинг: 48000 → 16000 = делим на 3 (если 44100 → на 2.75625)
    ratio = device_rate / SAMPLE_RATE

    stream = audio_p.open(
        format=pyaudio.paFloat32,
        channels=channels,
        rate=device_rate,
        input=True,
        input_device_index=loopback_device['index'],
        frames_per_buffer=int(device_rate * CHUNK_DURATION),
    )

    print(f"Поток открыт: {device_rate} Гц, каналов: {channels}, ресемплинг x{ratio:.2f}")

    try:
        while True:
            # Читаем CHUNK_DURATION секунд
            frames_to_read = int(device_rate * CHUNK_DURATION)
            data = stream.read(frames_to_read, exception_on_overflow=False)

            # Байты → numpy float32
            audio_array = np.frombuffer(data, dtype=np.float32)

            # Многоканальный → моно
            if channels > 1:
                audio_array = audio_array.reshape(-1, channels).mean(axis=1)

            # Ресемплинг в 16000 Гц через линейную интерполяцию
            if ratio != 1.0:
                target_len = int(len(audio_array) / ratio)
                indices = np.linspace(0, len(audio_array) - 1, target_len)
                audio_array = np.interp(indices, np.arange(len(audio_array)), audio_array)

            audio_queue.put(audio_array)
    except Exception as e:
        print(f"Ошибка захвата: {e}")
    finally:
        stream.stop_stream()
        stream.close()

# ============ Распознавание ============
def recognize_audio(overlay):
    while True:
        audio_data = audio_queue.get()
        audio_mono = audio_data.astype(np.float32)

        # Пропуск тишины
        if np.abs(audio_mono).mean() < 0.001:
            continue

        try:
            lang = overlay.language if overlay.language != "auto" else None
            segments, info = model.transcribe(
                audio_mono,
                language=lang,
                beam_size=5,
                vad_filter=True,
                condition_on_previous_text=False,
            )
            text = " ".join(seg.text.strip() for seg in segments).strip()
            if text:
                if is_blacklisted(text):
                    print(f"[{time.strftime('%H:%M:%S')}] [ОТФИЛЬТРОВАНО] {text}")
                    continue
                print(f"[{time.strftime('%H:%M:%S')}] {text}")
                overlay.add_line(text)
        except Exception as e:
            print(f"Ошибка распознавания: {e}")

# ============ Запуск ============
if __name__ == "__main__":
    print("=" * 62)
    print(f"  {APP_NAME}  v{APP_VERSION}")
    print(f"  Авторы: {APP_AUTHORS}")
    print("=" * 62)
    print(f"Модель: {MODEL_SIZE}")
    print(f"Язык: {LANGUAGE}")
    print(f"Шрифт: {FONT_SIZE}, цвет: {COLOR_PALETTE[COLOR_INDEX][0]}, прозрачность: {ALPHA}")
    print(f"Config: {CONFIG_PATH}")
    print()
    print("Перетаскивание — за панель справа или за ⠿.")
    print("Выделение текста — мышкой. Ctrl+C — копировать.")
    print("Пауза — кнопка ⏸ или Ctrl+Alt+Shift+P.")
    print("Правый клик — меню. Кнопка ? — справка.")
    print("--- ГОРЯЧИЕ КЛАВИШИ ---")
    print("Ctrl+Alt+Shift+C — сквозной режим. Ctrl+Alt+Shift+M — в трей.")
    print("Ctrl+Alt+Shift+P — пауза. Ctrl+Alt+Shift+Q — выход.")
    print("Ctrl+Alt+↑/↓ — шрифт. Ctrl+Alt+PgUp/PgDn — прозрачность.")
    print("Ctrl+Alt+Shift+1..5 — цвет.")
    print("=" * 62)

    overlay = SubtitleOverlay()

    capture_thread = threading.Thread(target=capture_audio, daemon=True)
    capture_thread.start()

    recognize_thread = threading.Thread(target=recognize_audio, args=(overlay,), daemon=True)
    recognize_thread.start()

    overlay.run()