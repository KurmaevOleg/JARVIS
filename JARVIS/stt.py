# stt.py
import os
import queue
import vosk
import sounddevice as sd
import json
from config import MODEL_STT_PATH, SR_STT, BLOCKSIZE
import tts

def initialize_stt():
    if not os.path.exists(MODEL_STT_PATH):
        raise FileNotFoundError(f"STT модель не найдена: {MODEL_STT_PATH}")
    return vosk.Model(MODEL_STT_PATH)

def listen_once(model) -> str:
    q = queue.Queue()

    def callback(indata, frames, time_info, status):
        if not tts.is_speaking.is_set():
            q.put(bytes(indata))

    with sd.RawInputStream(
        samplerate=SR_STT,
        blocksize=BLOCKSIZE,
        dtype='int16',
        channels=1,
        callback=callback
    ):
        rec = vosk.KaldiRecognizer(model, SR_STT)
        print("Слушаю...")

        while True:
            try:
                data = q.get(timeout=1)
            except queue.Empty:
                continue

            if rec.AcceptWaveform(data):
                result = json.loads(rec.Result())
                text = result.get('text', '').lower().strip()
                if text:
                    print(f"Распознано: {text}")
                    return text
                # если пусто — не выходим, а продолжаем слушать