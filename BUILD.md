# 📦 Сборка LiveSubtitles / Building LiveSubtitles

## ⚙️ Требования / Requirements

- **Python 3.10+** — [python.org](https://www.python.org/downloads/)
- **NVIDIA GPU** с драйверами CUDA 12
- **Windows 10/11 x64**
- **Git** — [git-scm.com](https://git-scm.com/)

---

## 📥 Установка зависимостей

```bash
pip install -r requirements.txt
```

---

## ▶️ Запуск из исходников

```bash
python live_overlay.py
```

При первом запуске модель `large-v3` (~3 ГБ) скачается автоматически в:

```
C:\Users\<user>\.cache\huggingface\
```

---

## 🔨 Сборка .exe (PyInstaller)

```bash
pyinstaller --onedir --noconsole --icon=app_icon.ico ^
  --name=LiveSubtitles ^
  --collect-all ctranslate2 ^
  --collect-all faster_whisper ^
  --collect-all pyaudiowpatch ^
  --collect-all pystray ^
  --collect-all deep_translator ^
  live_overlay.py
```

Готовый `.exe` появится в папке `dist/LiveSubtitles/`.

---

## 📦 Сборка установщика (Inno Setup)

1. Установите [Inno Setup](https://jrsoftware.org/isdl.php).
2. Откройте `LiveSubtitles_installer.iss` в Inno Setup Compiler.
3. **Замените пути** в начале скрипта на свои:

```ini
#define SourcePath "путь\к\dist\LiveSubtitles"
#define IconPath "путь\к\app_icon.ico"
```

4. Нажмите **F9** (Compile) — установщик появится в папке `installer/`.

---

## 🛠 Конфигурация

Все настройки хранятся в `config.json` рядом с `.exe`.

| Поле | Значение |
|------|----------|
| `model` | `large-v3`, `medium`, `small` |
| `language` | `ru`, `en`, `auto` |
| `capture_device` | пусто = авто; иначе — часть имени устройства |
| `font_size`, `alpha`, `color_index` | настройки оверлея |
| `blacklist` | фразы, которые не показывать |

---

## 📁 Структура проекта

```
LiveSubtitles/
├── live_overlay.py              ← основной код
├── config.json                  ← настройки
├── app_icon.ico                 ← иконка
├── requirements.txt             ← зависимости
├── BUILD.md                     ← этот файл
├── README.md                    ← описание
├── LICENSE                      ← лицензия MIT
├── LiveSubtitles_installer.iss  ← скрипт установщика
├── dist/                        ← собранный .exe (не в git)
└── installer/                   ← готовый установщик (не в git)
```

---

## 📜 Лицензия

MIT License — см. [LICENSE](LICENSE).

© 2026 **Nataly Taly & Echo**
