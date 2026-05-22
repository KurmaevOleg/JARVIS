import os
import queue
import time
import gc
import audioop
import vosk
import sounddevice as sd
import json
from config import (
    MODEL_STT_PATH,
    SR_STT,
    BLOCKSIZE,
    STT_MIN_AUDIO_RMS,
    STT_RECOGNIZER_RESET_SECONDS,
    STT_SILENCE_TAIL_BLOCKS,
)
import tts

DEBUG_STT = os.getenv("JARVIS_DEBUG_STT", "").lower() in ("1", "true", "yes")


def initialize_stt():
    if not os.path.exists(MODEL_STT_PATH):
        raise FileNotFoundError(f"STT модель не найдена: {MODEL_STT_PATH}")
    return vosk.Model(MODEL_STT_PATH)


class SpeechListener:
    def __init__(self, model, stop_event=None):
        self.model = model
        self.stop_event = stop_event
        self.queue = queue.Queue(maxsize=4)
        self.recognizer = vosk.KaldiRecognizer(model, SR_STT)
        self.stream = None
        self._last_reset_at = time.monotonic()
        self._voice_active = False
        self._silence_tail_blocks = 0

    def should_stop(self) -> bool:
        return self.stop_event is not None and self.stop_event.is_set()

    def _callback(self, indata, frames, time_info, status):
        if self.should_stop() or tts.is_speaking.is_set():
            return

        data = bytes(indata)
        level = audioop.rms(data, 2)
        if level < STT_MIN_AUDIO_RMS:
            if not self._voice_active:
                return
            if self._silence_tail_blocks <= 0:
                self._voice_active = False
                return
            self._silence_tail_blocks -= 1
        else:
            self._voice_active = True
            self._silence_tail_blocks = STT_SILENCE_TAIL_BLOCKS

        try:
            self.queue.put_nowait(data)
        except queue.Full:
            self._clear_queue()

    def _clear_queue(self):
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except queue.Empty:
                break

    def _reset_recognizer(self):
        try:
            if self.recognizer is not None:
                self.recognizer.FinalResult()
        except Exception:
            pass
        self.recognizer = vosk.KaldiRecognizer(self.model, SR_STT)
        self._clear_queue()
        self._last_reset_at = time.monotonic()
        self._voice_active = False
        self._silence_tail_blocks = 0
        gc.collect()

    def __enter__(self):
        self.stream = sd.RawInputStream(
            samplerate=SR_STT,
            blocksize=BLOCKSIZE,
            dtype='int16',
            channels=1,
            callback=self._callback
        )
        self.stream.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.stream is not None:
            self.stream.__exit__(exc_type, exc, tb)
            self.stream = None

    def listen_once(self) -> str:
        while not self.should_stop() and tts.is_speaking.is_set():
            self._clear_queue()
            time.sleep(0.05)

        if self.should_stop():
            return ""

        if DEBUG_STT:
            print("Слушаю...")

        while True:
            if self.should_stop():
                return ""

            try:
                data = self.queue.get(timeout=0.1)
            except queue.Empty:
                if time.monotonic() - self._last_reset_at >= STT_RECOGNIZER_RESET_SECONDS:
                    self._reset_recognizer()
                    if DEBUG_STT:
                        print("STT recognizer idle reset")
                continue

            if self.should_stop():
                return ""

            if tts.is_speaking.is_set():
                self._clear_queue()
                self._reset_recognizer()
                return ""

            if time.monotonic() - self._last_reset_at >= STT_RECOGNIZER_RESET_SECONDS:
                self._reset_recognizer()
                if DEBUG_STT:
                    print("STT recognizer reset")
                return ""

            if self.recognizer.AcceptWaveform(data):
                result = json.loads(self.recognizer.Result())
                text = result.get('text', '').lower().strip()
                self._reset_recognizer()
                if text:
                    if DEBUG_STT:
                        print(f"Распознано: {text}")
                    return text


def listen_once(model, stop_event=None) -> str:
    with SpeechListener(model, stop_event=stop_event) as listener:
        return listener.listen_once()
