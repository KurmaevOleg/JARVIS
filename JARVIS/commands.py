# commands.py
import os
import json
import time
import platform
import subprocess
import webbrowser
import urllib.parse
import datetime
import tempfile
import re
import zipfile
from xml.sax.saxutils import escape as xml_escape
from number_utils import parse_number

from timer_manager import TimerManager
from keyboard_layout import switch_to_english_layout

# === КОНФИГУРАЦИЯ ===
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FILE_REGISTRY_PATH = os.path.join(BASE_DIR, "file_registry.json")
CREATED_FILES_DIR = os.path.join(os.path.expanduser("~"), "Documents", "JARVIS")

_pyautogui = None


def speak(tts_model, silence, text: str):
    print(f"Ассистент: {text}")


def get_pyautogui():
    global _pyautogui
    if _pyautogui is None:
        import pyautogui

        pyautogui.PAUSE = 0.05
        pyautogui.FAILSAFE = False
        _pyautogui = pyautogui
    return _pyautogui

# === УТИЛИТЫ ОС ===
def get_os_type() -> str:
    return platform.system().lower()

def open_file_with_default(filepath: str) -> bool:
    try:
        os_type = get_os_type()
        if os_type == "windows":
            os.startfile(filepath)
        elif os_type == "darwin":
            subprocess.run(["open", filepath], check=True)
        else:
            subprocess.run(["xdg-open", filepath], check=True)
        return True
    except Exception as e:
        print(f"[ERROR] Открытие файла: {e}")
        return False

# === РЕЕСТР ФАЙЛОВ ===
def load_registry() -> dict:
    if os.path.exists(FILE_REGISTRY_PATH):
        with open(FILE_REGISTRY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_registry(registry: dict) -> None:
    with open(FILE_REGISTRY_PATH, "w", encoding="utf-8") as f:
        json.dump(registry, f, ensure_ascii=False, indent=2)

def register_file(file_path: str, keywords: list[str]) -> list[str]:
    registry = load_registry()
    absolute_path = os.path.abspath(file_path)
    added = []

    for keyword in keywords:
        cleaned_keyword = keyword.strip().lower()
        if cleaned_keyword:
            registry[cleaned_keyword] = absolute_path
            added.append(cleaned_keyword)

    if added:
        save_registry(registry)

    return added

def get_registered_files() -> dict:
    return load_registry()

def _sanitize_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]+', " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:80] or "Новый файл"

def _extract_requested_filename(cmd: str, default_name: str) -> str:
    match = re.search(r"(?:назови|название|под названием|с названием)\s+(.+)", cmd)
    if not match:
        return default_name

    name = match.group(1).strip()
    name = re.sub(r"\b(?:ворд|word|эксель|excel|иксель|таблица|таблицу|текстовый|текстовой|документ|файл)\b", "", name)
    return _sanitize_filename(name)

def _create_minimal_docx(path: str, title: str) -> None:
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""
    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""
    document = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>{xml_escape(title)}</w:t></w:r></w:p>
    <w:p><w:r><w:t></w:t></w:r></w:p>
    <w:sectPr/>
  </w:body>
</w:document>"""

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("word/document.xml", document)

def _create_minimal_xlsx(path: str) -> None:
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>"""
    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""
    workbook = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="Лист1" sheetId="1" r:id="rId1"/></sheets>
</workbook>"""
    workbook_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>"""
    sheet = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData/></worksheet>"""

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)

def create_and_open_file(kind: str, name: str | None = None) -> str:
    os.makedirs(CREATED_FILES_DIR, exist_ok=True)
    base_name = _sanitize_filename(name or f"Новый файл {datetime.datetime.now().strftime('%Y-%m-%d %H-%M-%S')}")

    if kind == "word":
        path = os.path.join(CREATED_FILES_DIR, f"{base_name}.docx")
        _create_minimal_docx(path, base_name)
    elif kind == "excel":
        path = os.path.join(CREATED_FILES_DIR, f"{base_name}.xlsx")
        _create_minimal_xlsx(path)
    else:
        path = os.path.join(CREATED_FILES_DIR, f"{base_name}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("")

    open_file_with_default(path)
    return path

def handle_create_file(cmd: str, tts_model, silence) -> bool:
    if not any(k in cmd for k in ("создай", "создать", "новый файл", "новый документ", "сделай файл")):
        return False

    if any(k in cmd for k in ("ворд", "word", "ворт", "вор", "docx", "документ ворд")):
        kind = "word"
        default_name = "Новый документ"
        spoken_kind = "ворд документ"
    elif any(k in cmd for k in ("эксель", "excel", "иксель", "таблица", "таблицу", "xlsx")):
        kind = "excel"
        default_name = "Новая таблица"
        spoken_kind = "эксель таблица"
    elif any(k in cmd for k in ("текстовый", "текстовой", "текстовый документ", "текстовой документ", "txt", "блокнот")):
        kind = "text"
        default_name = "Новый текстовый документ"
        spoken_kind = "текстовый документ"
    else:
        speak(tts_model, silence, "Уточните тип файла: текстовый документ, ворд документ или эксель таблица.")
        return True

    filename = _extract_requested_filename(cmd, default_name)
    try:
        path = create_and_open_file(kind, filename)
        speak(tts_model, silence, f"Создан и открыт {spoken_kind}: {os.path.basename(path)}")
    except Exception as e:
        speak(tts_model, silence, f"Не удалось создать файл: {e}")
    return True

# === РАБОТА С ФАЙЛАМИ ===
def handle_add_file(tts_model, silence) -> bool:
    speak(tts_model, silence, "Откройте окно приложения и добавьте файл через кнопку Добавить файл.")
    return True

def handle_open_file(cmd: str, tts_model, silence) -> bool:
    if "открой файл" not in cmd:
        return False

    keyword = cmd.replace("открой файл", "").strip().lower()
    if not keyword:
        speak(tts_model, silence, "Укажите ключевое слово после команды 'открой файл'.")
        return True

    registry = load_registry()
    matched_path = registry.get(keyword)

    if not matched_path:
        for kw, path in registry.items():
            if keyword in kw or kw in keyword:
                matched_path = path
                break

    if matched_path and os.path.isfile(matched_path):
        speak(tts_model, silence, f"Открываю файл по ключу: {keyword}")
        open_file_with_default(matched_path)
    else:
        speak(tts_model, silence, f"Файл с ключом '{keyword}' не найден.")
    return True

# === УПРАВЛЕНИЕ ПК ===
def shutdown_pc(confirm: bool = True) -> tuple[bool, str]:
    if confirm:
        return False, "Для выключения скажите: 'выключи компьютер без подтверждения'"
    try:
        os_type = get_os_type()
        if os_type == "windows":
            os.system("shutdown /s /t 5")
        elif os_type == "linux":
            os.system("systemctl poweroff")
        elif os_type == "darwin":
            os.system("sudo shutdown -h now")
        return True, "Компьютер будет выключен через несколько секунд."
    except Exception as e:
        return False, f"Ошибка выключения: {e}"

def reboot_pc(confirm: bool = True) -> tuple[bool, str]:
    if confirm:
        return False, "Для перезагрузки скажите: 'перезагрузи компьютер без подтверждения'"
    try:
        os_type = get_os_type()
        if os_type == "windows":
            os.system("shutdown /r /t 5")
        elif os_type == "linux":
            os.system("systemctl reboot")
        elif os_type == "darwin":
            os.system("sudo shutdown -r now")
        return True, "Компьютер будет перезагружен через несколько секунд."
    except Exception as e:
        return False, f"Ошибка перезагрузки: {e}"

def sleep_pc() -> tuple[bool, str]:
    try:
        os_type = get_os_type()
        if os_type == "windows":
            os.system("rundll32.exe powrprof.dll,SetSuspendState 0,1,0")
        elif os_type == "linux":
            os.system("systemctl suspend")
        elif os_type == "darwin":
            os.system("pmset sleepnow")
        return True, "Перехожу в спящий режим."
    except Exception as e:
        return False, f"Ошибка перехода в сон: {e}"

# === БРАУЗЕР ===
def handle_browser_search(cmd: str, tts_model, silence) -> bool:
    if "открой браузер" not in cmd:
        return False

    query = cmd.replace("открой браузер", "").strip()
    for word in ["поиск", "найти", "в гугле", "в интернете", "гугл"]:
        query = query.replace(word, "").strip()

    if not query:
        speak(tts_model, silence, "Открываю браузер.")
        webbrowser.open("https://google.com")
        return True

    encoded_query = urllib.parse.quote(query)
    speak(tts_model, silence, f"Ищу: {query}")
    webbrowser.open(f"https://google.com/search?q={encoded_query}")
    return True

# === БУФЕР ОБМЕНА ===
def handle_clipboard(cmd: str, tts_model, silence) -> bool:
    cmd_lower = cmd.lower()
    os_type = get_os_type()
    copy_keys = ('command', 'c') if os_type == "darwin" else ('ctrl', 'c')
    paste_keys = ('command', 'v') if os_type == "darwin" else ('ctrl', 'v')

    # Копирование выделенного текста
    if any(k in cmd_lower for k in ["скопируй", "копируй", "скопируй выделенное", "копируй текст"]):
        try:
            pyautogui = get_pyautogui()
            switch_to_english_layout()
            time.sleep(0.15)
            pyautogui.hotkey(*copy_keys)
            time.sleep(0.2)
            speak(tts_model, silence, "Скопировано.")
        except Exception as e:
            speak(tts_model, silence, f"Ошибка копирования: {e}")
        return True

    # Вставка из буфера
    if any(k in cmd_lower for k in ["вставь", "вставь из буфера", "поставь", "вставить"]):
        try:
            pyautogui = get_pyautogui()
            switch_to_english_layout()
            time.sleep(0.15)
            pyautogui.hotkey(*paste_keys)
            speak(tts_model, silence, "Вставлено.")
        except Exception as e:
            speak(tts_model, silence, f"Ошибка вставки: {e}")
        return True

    # Копирование произнесённого текста в буфер
    if any(k in cmd_lower for k in ["скопировать в буфер", "в буфер обмена", "запомни текст"]):
        text = cmd
        for phrase in ["скопировать в буфер", "в буфер обмена", "запомни текст"]:
            if phrase in cmd_lower:
                text = cmd.replace(phrase, "").strip()
                break
        if text and len(text) > 2:
            import pyperclip

            pyperclip.copy(text)
            speak(tts_model, silence, "Текст в буфере.")
        else:
            speak(tts_model, silence, "Укажите текст.")
        return True

    # Очистка буфера
    if any(k in cmd_lower for k in ["очисти буфер", "удали из буфера"]):
        import pyperclip

        pyperclip.copy("")
        speak(tts_model, silence, "Буфер очищен.")
        return True

    return False

# === СКРИНШОТ И АНАЛИЗ ЭКРАНА ===
def take_screenshot(max_side: int = 1024) -> str:
    """Делает скриншот, уменьшает до max_side и сохраняет во временный JPEG."""
    import mss
    from PIL import Image

    with mss.mss() as sct:
        monitor = sct.monitors[1]
        sct_img = sct.grab(monitor)
        img = Image.frombytes("RGB", sct_img.size, sct_img.rgb)
        img.thumbnail((max_side, max_side), Image.LANCZOS)
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
        img.save(tmp.name, format="JPEG", quality=85, optimize=True)
        return tmp.name

def handle_screen_image(tts_model, silence) -> bool:
    try:
        speak(tts_model, silence, "Делаю скриншот и анализирую.")
        path = take_screenshot()
    except Exception as e:
        speak(tts_model, silence, f"Не удалось сделать скриншот: {e}")
        return True

    prompt = "Опиши, что происходит на экране, не более чем в 30 словах. Если есть текст, прочитай его кратко."
    try:
        from llm_client import chat_with_llm

        answer = chat_with_llm(prompt, image_path=path)
    except Exception as e:
        speak(tts_model, silence, f"Ошибка LLM: {e}")
        return True
    finally:
        try:
            os.unlink(path)
        except:
            pass

    if not answer:
        speak(tts_model, silence, "Модель не вернула ответа.")
        return True

    speak(tts_model, silence, answer)
    return True

# === ГЛАВНЫЙ РОУТЕР КОМАНД ===
def process_command(text: str, tts_model, silence, timer_manager: TimerManager) -> bool:
    if not text:
        return True

    cmd = text.lower()
    print(f"Обработка команды: {cmd}")

    # Выход
    if any(k in cmd for k in ("стоп", "выход", "заверши работу")):
        speak(tts_model, silence, "Ассистент завершает работу.")
        return False

    # Режим ожидания (не выключает ассистента, просто прекращает текущий диалог)
    if any(k in cmd for k in ("отойди", "спи", "усни", "хватит")):
        speak(tts_model, silence, "Хорошо, я замолкаю. Скажите 'Джарвис', когда будет нужно.")
        return True  # возвращаемся в режим ожидания wake word

    # 1. Файлы
    if handle_create_file(cmd, tts_model, silence):
        return True
    if "добавить файл" in cmd:
        return handle_add_file(tts_model, silence)
    if "открой файл" in cmd:
        return handle_open_file(cmd, tts_model, silence)

    # 2. Управление ПК
    if any(k in cmd for k in ["выключи компьютер", "заверши работу пк", "выключи пк"]):
        _, msg = shutdown_pc(confirm=("без подтверждения" not in cmd and "подтверждаю" not in cmd and "без подтверждение" not in cmd))
        speak(tts_model, silence, msg)
        return True
    if any(k in cmd for k in ["перезагрузи компьютер", "перезагрузить компьютер", "ребут"]):
        _, msg = reboot_pc(confirm=("без подтверждения" not in cmd and "подтверждаю" not in cmd and "без подтверждение" not in cmd))
        speak(tts_model, silence, msg)
        return True
    if any(k in cmd for k in ["спящий режим", "сон"]):
        _, msg = sleep_pc()
        speak(tts_model, silence, msg)
        return True

    # 3. Браузер
    if "открой браузер" in cmd:
        return handle_browser_search(cmd, tts_model, silence)

    # 4. Буфер обмена
    if handle_clipboard(cmd, tts_model, silence):
        return True

    # 5. Скриншот
    if any(k in cmd for k in ("скриншот", "экран", "что на экране", "прочитай экран")):
        return handle_screen_image(tts_model, silence)

    # 6. Время
    if "время" in cmd:
        now = datetime.datetime.now().strftime("%H:%M")
        speak(tts_model, silence, f"Сейчас {now}.")
        return True

    # 7. Системный мониторинг
    if any(k in cmd for k in ("система", "статус", "ресурсы")):
        import system_monitor

        speak(tts_model, silence, system_monitor.get_system_report())
        return True
    if any(k in cmd for k in ("процессор", "цп", "cpu")):
        import system_monitor

        speak(tts_model, silence, f"Загрузка процессора {system_monitor.get_cpu_usage()}")
        return True
    if any(k in cmd for k in ("память", "оператив", "ram")):
        import system_monitor

        speak(tts_model, silence, system_monitor.get_memory_report())
        return True
    if any(k in cmd for k in ("диск", "место")):
        import system_monitor

        speak(tts_model, silence, f"Диск: {system_monitor.get_disk_usage()}")
        return True
    if any(k in cmd for k in ("сеть", "интернет", "трафик")):
        import system_monitor

        speak(tts_model, silence, f"Скорость сети: {system_monitor.get_network_io()}")
        return True

    # 8. Управление громкостью
    if "громче" in cmd or "сделай громче" in cmd:
        pyautogui = get_pyautogui()
        pyautogui.press('volumeup')
        speak(tts_model, silence, "Громкость увеличена")
        return True
    if "тише" in cmd or "сделай тише" in cmd:
        pyautogui = get_pyautogui()
        pyautogui.press('volumedown')
        speak(tts_model, silence, "Громкость уменьшена")
        return True
    if "без звука" in cmd or "выключи звук" in cmd:
        pyautogui = get_pyautogui()
        pyautogui.press('volumemute')
        speak(tts_model, silence, "Звук выключен")
        return True

    # 9. Заметки
    if "запиши" in cmd or "заметка" in cmd:
        text_to_save = cmd.replace("запиши", "").replace("заметка", "").strip()
        if text_to_save:
            with open("notes.txt", "a", encoding="utf-8") as f:
                f.write(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} - {text_to_save}\n")
            speak(tts_model, silence, f"Записано: {text_to_save}")
        else:
            speak(tts_model, silence, "Что записать?")
        return True

    # 10. Таймеры и напоминания
    timer_match = re.search(r'(?:установи|заведи|запусти)\s+(?:таймер\s+)?(?:на\s+)?(\d+|[а-я]+)\s+(секунд|секунду|минут|минуту)', cmd)
    if timer_match:
        value_str = timer_match.group(1)
        value = int(value_str) if value_str.isdigit() else parse_number(value_str)
        unit = timer_match.group(2)
        if value is None:
            speak(tts_model, silence, "Не удалось распознать число.")
            return True
        seconds = value * 60 if "минут" in unit else value
        timer_manager.add_timer(seconds, f"Таймер на {value} {unit} сработал")
        speak(tts_model, silence, f"Таймер на {value} {unit} установлен")
        return True

    simple_timer = re.search(r'таймер\s+(?:на\s+)?(\d+|[а-я]+)\s*(минут|минуту|секунд|секунду)', cmd)
    if simple_timer:
        value_str = simple_timer.group(1)
        value = int(value_str) if value_str.isdigit() else parse_number(value_str)
        unit = simple_timer.group(2)
        if value is None:
            speak(tts_model, silence, "Не удалось распознать число.")
            return True
        seconds = value * 60 if "минут" in unit else value
        timer_manager.add_timer(seconds, f"Таймер на {value} {unit} сработал")
        speak(tts_model, silence, f"Таймер на {value} {unit} установлен")
        return True

    remind_match = re.search(r'напомни\s+(?:через\s+)?(\d+|[а-я]+)\s+(минут|минуту|секунд|секунду)\s+(.+)', cmd)
    if remind_match:
        value_str = remind_match.group(1)
        value = int(value_str) if value_str.isdigit() else parse_number(value_str)
        unit = remind_match.group(2)
        message = remind_match.group(3).strip()
        if value is None:
            speak(tts_model, silence, "Не удалось распознать число.")
            return True
        seconds = value * 60 if "минут" in unit else value
        timer_manager.add_timer(seconds, f"Напоминание: {message}")
        speak(tts_model, silence, f"Напоминание через {value} {unit} установлено")
        return True

    if any(k in cmd for k in (
        "активные таймеры",
        "активные таймера",
        "активный таймер",
        "сколько таймеров",
        "сколько таймера",
    )):
        count = timer_manager.get_active_count()
        speak(tts_model, silence, f"Активных таймеров и напоминаний: {count}")
        return True

    # 11. Fallback к LLM (текстовый io.net)
    try:
        from llm_client import chat_with_llm

        answer = chat_with_llm(text)
        speak(tts_model, silence, answer)
    except Exception as e:
        speak(tts_model, silence, f"Ошибка обработки: {e}")
    return True
