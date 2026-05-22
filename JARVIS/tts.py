import re
import threading
import gc

import numpy as np
import sounddevice as sd
import torch

from config import SR_TTS, DEVICE, TORCH_NUM_THREADS, TORCH_NUM_INTEROP_THREADS
from number_utils import replace_numbers_for_speech

# Ассистент либо говорит, либо слушает
is_speaking = threading.Event()
_speak_lock = threading.Lock()


def initialize_tts(speaker: str = 'v4_ru'):
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


def warmup_tts(model, silence):
    with torch.inference_mode():
        _ = model.apply_tts(
            text="привет",
            speaker='aidar',
            sample_rate=SR_TTS,
            put_accent=True,
            put_yo=True
        )
    sd.play(silence, samplerate=SR_TTS)
    sd.wait()
    gc.collect()


def _normalize_for_tts(text: str) -> str:
    text = text.replace("\n", " ")
    text = text.replace("\r", " ")
    text = re.sub(r"\s+", " ", text)
    text = replace_numbers_for_speech(text)
    text = re.sub(r"[^\wа-яА-Яa-zA-Z0-9 .,!?—-]", "", text)
    return text[:800]


def speak(model, silence, text: str):
    print(f"Ассистент: {text}")
    safe = _normalize_for_tts(text)

    with _speak_lock:
        is_speaking.set()
        try:
            with torch.inference_mode():
                audio = model.apply_tts(
                    text=safe,
                    speaker='aidar',
                    sample_rate=SR_TTS,
                    put_accent=True,
                    put_yo=True
                )
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
