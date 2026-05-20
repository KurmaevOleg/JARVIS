import os
import queue
import time
import vosk
import sounddevice as sd
import json
from config import MODEL_STT_PATH, SR_STT, BLOCKSIZE
import tts

DEBUG_STT = os.getenv("JARVIS_DEBUG_STT", "").lower() in ("1", "true", "yes")


def initialize_stt():
    if not os.path.exists(MODEL_STT_PATH):
        raise FileNotFoundError(f"STT модель не найдена: {MODEL_STT_PATH}")
    return vosk.Model(MODEL_STT_PATH)


def listen_once(model, stop_event=None) -> str:
    q = queue.Queue()

    def should_stop() -> bool:
        return stop_event is not None and stop_event.is_set()

    # Не открываем поток, если уже идёт остановка или речь ассистента
    while not should_stop() and tts.is_speaking.is_set():
        time.sleep(0.05)

    if should_stop():
        return ""

    def callback(indata, frames, time_info, status):
        if not tts.is_speaking.is_set() and not should_stop():
            q.put(bytes(indata))

    with sd.RawInputStream(
        samplerate=SR_STT,
        blocksize=BLOCKSIZE,
        dtype='int16',
        channels=1,
        callback=callback
    ):
        rec = vosk.KaldiRecognizer(model, SR_STT)
        if DEBUG_STT:
            print("Слушаю...")

        while True:
            if should_stop():
                return ""

            try:
                data = q.get(timeout=0.1)
            except queue.Empty:
                continue

            if should_stop():
                return ""

            # Если ассистент начал говорить — сразу выходим из текущего цикла прослушивания
            if tts.is_speaking.is_set():
                while not q.empty():
                    try:
                        q.get_nowait()
                    except queue.Empty:
                        break
                return ""

            if rec.AcceptWaveform(data):
                result = json.loads(rec.Result())
                text = result.get('text', '').lower().strip()
                if text:
                    if DEBUG_STT:
                        print(f"Распознано: {text}")
                    return text
