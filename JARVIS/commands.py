import webbrowser
import datetime
from tts import speak
from llm_client import chat_with_llm

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
    
    answer = chat_with_llm(text)
    speak(tts_model, silence, answer)
    return True