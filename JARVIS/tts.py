import torch
import numpy as np
import sounddevice as sd
from config import SR_TTS, DEVICE

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


def speak(model, silence, text: str):
    print(f"Ассистент: {text}")
    audio = model.apply_tts(text=text, speaker='aidar',
                             sample_rate=SR_TTS, put_accent=True, put_yo=True)
    audio_np = np.concatenate([np.array(audio, dtype=np.float32), silence])
    sd.play(audio_np, samplerate=SR_TTS)
    sd.wait()
