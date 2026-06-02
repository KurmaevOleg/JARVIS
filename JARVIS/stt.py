import os
import queue
import time
import audioop
from collections import deque

import vosk
import sounddevice as sd
import json
from config import (
    MODEL_STT_PATH,
    SR_STT,
    BLOCKSIZE,
    STT_MIN_AUDIO_RMS,
    STT_NOISE_RMS_ALPHA,
    STT_NOISE_RMS_MULTIPLIER,
    STT_PRE_ROLL_BLOCKS,
    STT_QUEUE_MAX_BLOCKS,
    STT_SILENCE_TAIL_BLOCKS,
    STT_START_TRIGGER_BLOCKS,
    STT_VAD_ENABLED,
)
import tts

DEBUG_STT = os.getenv("JARVIS_DEBUG_STT", "").lower() in ("1", "true", "yes")
_END_OF_UTTERANCE = object()


def initialize_stt():
    if not os.path.exists(MODEL_STT_PATH):
        raise FileNotFoundError(f"STT модель не найдена: {MODEL_STT_PATH}")
    return vosk.Model(MODEL_STT_PATH)


class SpeechListener:
    def __init__(self, model, stop_event=None):
        self.model = model
        self.stop_event = stop_event
        self.queue = queue.Queue(maxsize=STT_QUEUE_MAX_BLOCKS)
        self.recognizer = vosk.KaldiRecognizer(model, SR_STT)
        self.stream = None
        self._voice_active = False
        self._silence_tail_blocks = 0
        self._noise_rms = float(STT_MIN_AUDIO_RMS)
        self._last_rms = 0
        self._last_threshold = STT_MIN_AUDIO_RMS
        self._pre_roll = deque(maxlen=max(0, STT_PRE_ROLL_BLOCKS))
        self._speech_start_blocks = 0

    def should_stop(self) -> bool:
        return self.stop_event is not None and self.stop_event.is_set()

    def _callback(self, indata, frames, time_info, status):
        if self.should_stop() or tts.is_speaking.is_set():
            return

        data = bytes(indata)
        if not STT_VAD_ENABLED or STT_MIN_AUDIO_RMS <= 0:
            self._put_audio(data)
            return

        level = audioop.rms(data, 2)
        self._last_rms = level
        threshold = self._current_threshold()
        self._last_threshold = threshold

        if level < threshold:
            self._speech_start_blocks = 0
            self._remember_background(level)
            if not self._voice_active:
                self._pre_roll.append(data)
                return
            if self._silence_tail_blocks <= 0:
                self._voice_active = False
                self._pre_roll.clear()
                self._put_end_marker()
                return
            self._silence_tail_blocks -= 1
        else:
            if not self._voice_active:
                self._speech_start_blocks += 1
                self._pre_roll.append(data)
                if self._speech_start_blocks < STT_START_TRIGGER_BLOCKS:
                    return
                self._flush_pre_roll()
                self._speech_start_blocks = 0
                self._voice_active = True
                self._silence_tail_blocks = STT_SILENCE_TAIL_BLOCKS
                return
            self._voice_active = True
            self._silence_tail_blocks = STT_SILENCE_TAIL_BLOCKS

        self._put_audio(data)

    def _current_threshold(self) -> int:
        adaptive = int(self._noise_rms * STT_NOISE_RMS_MULTIPLIER)
        return max(STT_MIN_AUDIO_RMS, adaptive)

    def _remember_background(self, level: int):
        if self._voice_active:
            return
        if self._noise_rms <= 0:
            self._noise_rms = float(level)
            return
        alpha = min(1.0, max(0.0, STT_NOISE_RMS_ALPHA))
        self._noise_rms = (self._noise_rms * (1.0 - alpha)) + (level * alpha)

    def _flush_pre_roll(self):
        while self._pre_roll:
            self._put_audio(self._pre_roll.popleft())

    def _put_audio(self, data: bytes):
        try:
            self.queue.put_nowait(data)
        except queue.Full:
            self._clear_queue()
            try:
                self.queue.put_nowait(data)
            except queue.Full:
                pass

    def _put_end_marker(self):
        try:
            self.queue.put_nowait(_END_OF_UTTERANCE)
        except queue.Full:
            self._clear_queue()
            try:
                self.queue.put_nowait(_END_OF_UTTERANCE)
            except queue.Full:
                pass

    def _clear_queue(self):
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except queue.Empty:
                break

    def _finish_utterance(self, clear_queue: bool = True):
        if clear_queue:
            self._clear_queue()
        self._voice_active = False
        self._silence_tail_blocks = 0
        self._pre_roll.clear()
        self._speech_start_blocks = 0

    @staticmethod
    def _text_from_result(raw: str) -> str:
        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            return ""
        return result.get('text', '').lower().strip()

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

    def listen_once(self, timeout_seconds: float | None = None) -> str:
        deadline = time.monotonic() + timeout_seconds if timeout_seconds and timeout_seconds > 0 else None
        got_audio = False

        def timed_out() -> bool:
            return not got_audio and deadline is not None and time.monotonic() >= deadline

        while not self.should_stop() and tts.is_speaking.is_set():
            if timed_out():
                return ""
            self._clear_queue()
            time.sleep(0.05)

        if self.should_stop():
            return ""

        if DEBUG_STT:
            print("Слушаю...")

        while True:
            if self.should_stop():
                return ""
            if timed_out():
                return ""

            try:
                wait_time = 0.1
                if deadline is not None:
                    wait_time = max(0.01, min(wait_time, deadline - time.monotonic()))
                data = self.queue.get(timeout=wait_time)
            except queue.Empty:
                continue

            if self.should_stop():
                return ""

            if tts.is_speaking.is_set():
                self._finish_utterance()
                return ""

            if data is _END_OF_UTTERANCE:
                text = self._text_from_result(self.recognizer.Result())
                self._finish_utterance(clear_queue=False)
                if text:
                    if DEBUG_STT:
                        print(f"Распознано: {text}")
                    return text
                continue

            got_audio = True
            if self.recognizer.AcceptWaveform(data):
                text = self._text_from_result(self.recognizer.Result())
                self._finish_utterance()
                if text:
                    if DEBUG_STT:
                        print(f"Распознано: {text}")
                    return text


def listen_once(model, stop_event=None) -> str:
    with SpeechListener(model, stop_event=stop_event) as listener:
        return listener.listen_once()
