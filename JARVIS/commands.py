import mss
from PIL import Image
import os
import webbrowser
import datetime
from tts import speak
from llm_client import chat_with_llm

SCREENSHOT_DIR = "screenshots"
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

def take_screenshot() -> str:
    filename = os.path.join(SCREENSHOT_DIR, f"screenshot_{datetime.datetime.now():%Y%m%d_%H%M%S}.png")
    with mss.mss() as sct:
        monitor = sct.monitors[1]  # основной монитор
        sct_img = sct.grab(monitor)
        img = Image.frombytes("RGB", sct_img.size, sct_img.rgb)
        img.save(filename)
    return filename

def handle_screen_image(tts_model, silence):
    try:
        speak(tts_model, silence, "Делаю скриншот и посылаю его в модель для анализа.")
        path = take_screenshot()
    except Exception as e:
        speak(tts_model, silence, f"Не удалось сделать скриншот: {e}")
        return True

    # Вопрос/инструкция к модели — можно менять
    prompt = "Дай краткий анализ по изображению. 1-3 строки"

    try:
        answer = chat_with_llm(prompt, image_path=path)
    except Exception as e:
        # сетевые ошибки, таймауты и т. п.
        speak(tts_model, silence, f"Ошибка при обращении к LLM: {e}")
        return True

    if not answer:
        speak(tts_model, silence, "Модель не вернула ответа.")
        return True

    # Выводим результат
    speak(tts_model, silence, answer)
    return True

def process_command(text: str, tts_model, silence) -> bool:
    if not text:
        speak(tts_model, silence, "Скажи что-нибудь.")
        return True
    cmd = text.lower()
    if any(k in cmd for k in ("стоп", "выход")):
        speak(tts_model, silence, "Ассистент завершает работу.")
        return False
    if "открой браузер" in cmd:
        speak(tts_model, silence, "Открываю браузер.")
        webbrowser.open("https://google.com")
        return True
    if "время" in cmd:
        now = datetime.datetime.now().strftime("%H:%M")
        speak(tts_model, silence, f"Сейчас {now}.")
        return True
    if any(k in cmd for k in ("скриншот", "экран", "что на экране", "прочитай экран")):
        return handle_screen_image(tts_model, silence)

    
    answer = chat_with_llm(text)
    speak(tts_model, silence, answer)
    return True