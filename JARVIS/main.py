# main.py
from stt import initialize_stt, listen_once
from tts import initialize_tts, warmup_tts, speak
from commands import process_command
from timer_manager import TimerManager
from utils import log
import time

def main():
    stt_model = initialize_stt()
    tts_model, silence = initialize_tts()
    warmup_tts(tts_model, silence)

    def speak_callback(text):
        # Эта функция будет вызвана из фонового потока!
        print(f"[Таймер] Озвучиваю: {text}")
        speak(tts_model, silence, text)

    timer_manager = TimerManager(speak_callback)
    timer_manager.start()

    speak(tts_model, silence, "Ассистент готов к работе.")
    try:
        while True:
            text = listen_once(stt_model)
            if not process_command(text, tts_model, silence, timer_manager):
                break
    except KeyboardInterrupt:
        timer_manager.stop()
        log("Завершение по Ctrl+C")

if __name__ == "__main__":
    main()