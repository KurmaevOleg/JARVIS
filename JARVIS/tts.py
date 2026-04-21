import re
import threading

import numpy as np
import sounddevice as sd
import torch

from config import SR_TTS, DEVICE
from number_utils import replace_numbers_for_speech

is_speaking = threading.Event()

def initialize_tts(speaker: str = 'v4_ru'):
    model, _ = torch.hub.load(
        repo_or_dir='snakers4/silero-models',
        model='silero_tts', language='ru', speaker=speaker, trust_repo=True
    )
    model.to(torch.device(DEVICE))
    silence = np.zeros(int(0.2 * SR_TTS), dtype=np.float32)
    return model, silence

def warmup_tts(model, silence):
    _ = model.apply_tts(text="привет", speaker='aidar',
                        sample_rate=SR_TTS, put_accent=True, put_yo=True)
    sd.play(silence, samplerate=SR_TTS)
    sd.wait()

def _normalize_for_tts(text: str) -> str:
    text = text.replace("\n", " ")
    text = text.replace("\r", " ")
    text = re.sub(r"\s+", " ", text)
    text = replace_numbers_for_speech(text)
    text = re.sub(r"[^\wа-яА-Яa-zA-Z0-9 .,!?—-]", "", text)
    return text[:800]

def speak(model, silence, text: str):
    print(f"Ассистент: {text}")  # на экран — как есть
    safe = _normalize_for_tts(text)  # в речь — с преобразованием чисел

    is_speaking.set()
    try:
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
        is_speaking.clear()