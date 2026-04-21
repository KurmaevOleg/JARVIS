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
from number_utils import parse_number

import mss
from PIL import Image
import pyperclip
import pyautogui

from tts import speak
from llm_client import chat_with_llm
from timer_manager import TimerManager
import system_monitor

# === КОНФИГУРАЦИЯ ===
FILE_REGISTRY_PATH = "file_registry.json"
SCREENSHOT_DIR = "screenshots"
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

# Оптимизация pyautogui
pyautogui.PAUSE = 0.05
pyautogui.FAILSAFE = False

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

# === РАБОТА С ФАЙЛАМИ ===
def handle_add_file(tts_model, silence) -> bool:
    speak(tts_model, silence, "Введите путь к файлу.")
    print("\n💡 Введите полный путь к файлу (или 'отмена' для выхода):")

    while True:
        try:
            raw_path = input("> ").strip().strip("\"'")
        except EOFError:
            speak(tts_model, silence, "Ввод прерван.")
            return True

        if raw_path.lower() in ("отмена", "cancel", "выход"):
            speak(tts_model, silence, "Добавление файла отменено.")
            return True

        if os.path.isfile(raw_path):
            file_path = os.path.abspath(raw_path)
            break

        print("❌ Файл не найден. Проверьте путь или введите 'отмена'.")
        speak(tts_model, silence, "Файл не найден. Повторите ввод или скажите отмена.")

    speak(tts_model, silence, "Файл найден. Введите ключевые слова через запятую.")
    print("💡 Введите ключевые слова через запятую (например: дискорд, дс, дис):")

    try:
        keywords_input = input("> ").strip()
    except EOFError:
        speak(tts_model, silence, "Ввод прерван.")
        return True

    if not keywords_input:
        speak(tts_model, silence, "Ключевые слова не введены. Отмена.")
        return True

    keywords = [kw.strip().lower() for kw in keywords_input.split(",") if kw.strip()]
    if not keywords:
        speak(tts_model, silence, "Некорректные ключевые слова. Отмена.")
        return True

    registry = load_registry()
    added = []
    for kw in keywords:
        if kw in registry:
            print(f"⚠️ Ключ '{kw}' уже привязан. Перезаписываю.")
        registry[kw] = file_path
        added.append(kw)

    save_registry(registry)
    speak(tts_model, silence, f"Файл добавлен. Ключи: {', '.join(added)}")
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
            pyperclip.copy(text)
            speak(tts_model, silence, "Текст в буфере.")
        else:
            speak(tts_model, silence, "Укажите текст.")
        return True

    # Очистка буфера
    if any(k in cmd_lower for k in ["очисти буфер", "удали из буфера"]):
        pyperclip.copy("")
        speak(tts_model, silence, "Буфер очищен.")
        return True

    return False

# === СКРИНШОТ И АНАЛИЗ ЭКРАНА ===
def take_screenshot(max_side: int = 1024) -> str:
    """Делает скриншот, уменьшает до max_side и сохраняет во временный JPEG."""
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

    # 1. Файлы
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
    if any(k in cmd for k in ["спящий режим", "усни", "сон", "засни"]):
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
        speak(tts_model, silence, system_monitor.get_system_report())
        return True
    if any(k in cmd for k in ("процессор", "цп", "cpu")):
        speak(tts_model, silence, f"Загрузка процессора {system_monitor.get_cpu_usage()}")
        return True
    if any(k in cmd for k in ("память", "оператив", "ram")):
        speak(tts_model, silence, f"Оперативная память: {system_monitor.get_memory_usage()}")
        return True
    if any(k in cmd for k in ("диск", "место")):
        speak(tts_model, silence, f"Диск: {system_monitor.get_disk_usage()}")
        return True
    if any(k in cmd for k in ("сеть", "интернет", "трафик")):
        speak(tts_model, silence, f"Скорость сети: {system_monitor.get_network_io()}")
        return True

    # 8. Управление громкостью
    if "громче" in cmd or "сделай громче" in cmd:
        pyautogui.press('volumeup')
        speak(tts_model, silence, "Громкость увеличена")
        return True
    if "тише" in cmd or "сделай тише" in cmd:
        pyautogui.press('volumedown')
        speak(tts_model, silence, "Громкость уменьшена")
        return True
    if "без звука" in cmd or "выключи звук" in cmd:
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

    if "активные таймеры" in cmd or "сколько таймеров" in cmd:
        count = timer_manager.get_active_count()
        speak(tts_model, silence, f"Активных таймеров и напоминаний: {count}")
        return True

    # 11. Fallback к LLM (текстовый io.net)
    try:
        answer = chat_with_llm(text)
        speak(tts_model, silence, answer)
    except Exception as e:
        speak(tts_model, silence, f"Ошибка обработки: {e}")
    return True