import re
import threading
import gc

import numpy as np
import sounddevice as sd
import torch

from config import (
    SR_TTS,
    DEVICE,
    TORCH_NUM_THREADS,
    TORCH_NUM_INTEROP_THREADS,
    TTS_MAX_CHARS,
    TTS_MODEL_SPEAKER,
    TTS_PUT_ACCENT,
    TTS_PUT_YO,
    TTS_SPEAKER,
    TTS_WARMUP_ENABLED,
)
from number_utils import replace_numbers_for_speech

# Ассистент либо говорит, либо слушает
is_speaking = threading.Event()
_speak_lock = threading.Lock()


def initialize_tts(speaker: str = TTS_MODEL_SPEAKER):
    torch.set_grad_enabled(False)
    torch.set_num_threads(TORCH_NUM_THREADS)
    try:
        torch.set_num_interop_threads(TORCH_NUM_INTEROP_THREADS)
    except RuntimeError:
        pass

    model, _ = torch.hub.load(
        repo_or_dir='snakers4/silero-models',
        model='silero_tts', language='ru', speaker=speaker, trust_repo=True
    )
    model.to(torch.device(DEVICE))
    gc.collect()
    silence = np.zeros(int(0.2 * SR_TTS), dtype=np.float32)
    return model, silence


def synthesize_tts(model, text: str):
    with torch.inference_mode():
        return model.apply_tts(
            text=text,
            speaker=TTS_SPEAKER,
            sample_rate=SR_TTS,
            put_accent=TTS_PUT_ACCENT,
            put_yo=TTS_PUT_YO,
        )


def warmup_tts(model, silence):
    if not TTS_WARMUP_ENABLED:
        return

    _ = synthesize_tts(model, "привет")
    sd.play(silence, samplerate=SR_TTS)
    sd.wait()
    del _
    gc.collect()


def _normalize_for_tts(text: str) -> str:
    text = text.replace("\n", " ")
    text = text.replace("\r", " ")
    text = re.sub(r"\s+", " ", text)
    text = replace_numbers_for_speech(text)
    text = re.sub(r"[^\wа-яА-Яa-zA-Z0-9 .,!?—-]", "", text)
    return text[:TTS_MAX_CHARS]


def speak(model, silence, text: str):
    print(f"Ассистент: {text}")
    safe = _normalize_for_tts(text)

    with _speak_lock:
        is_speaking.set()
        try:
            audio = synthesize_tts(model, safe)
            audio_np = np.concatenate([np.array(audio, dtype=np.float32), silence])
            sd.play(audio_np, samplerate=SR_TTS)
            sd.wait()
        finally:
            try:
                del audio
                del audio_np
            except UnboundLocalError:
                pass
            gc.collect()
            is_speaking.clear()
