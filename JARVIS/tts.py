import torch
import numpy as np
import sounddevice as sd
from config import SR_TTS, DEVICE
import re

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
    # Убираем всё, что Silero не любит
    text = text.replace("\n", " ")
    text = text.replace("\r", " ")
    text = re.sub(r"\s+", " ", text)

    # Убираем странные символы
    text = re.sub(r"[^\wа-яА-Яa-zA-Z0-9 .,!?—-]", "", text)

    # Silero падает на длинных строках
    return text[:800]   # 800 символов безопасно


def speak(model, silence, text: str):
    safe = _normalize_for_tts(text)

    print(f"Ассистент: {safe}")

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