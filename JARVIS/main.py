from stt import initialize_stt, listen_once
from tts import initialize_tts, warmup_tts, speak
from commands import process_command
from utils import log

def main():
    stt_model = initialize_stt()
    tts_model, silence = initialize_tts()
    warmup_tts(tts_model, silence)

    speak(tts_model, silence, "Ассистент готов к работе.")
    try:
        while True:
            text = listen_once(stt_model)
            if not process_command(text, tts_model, silence):
                break
    except KeyboardInterrupt:
        log("Завершение по Ctrl+C")

if __name__ == "__main__":
    main()
