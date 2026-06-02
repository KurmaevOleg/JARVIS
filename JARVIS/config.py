#config.py
import os

# Пути и параметры
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_STT_PATH = os.getenv("MODEL_STT_PATH", os.path.join(BASE_DIR, "vosk-model-small-ru-0.22"))
SR_STT = 16000
BLOCKSIZE = int(os.getenv("BLOCKSIZE", "2000"))
STT_MIN_AUDIO_RMS = int(os.getenv("STT_MIN_AUDIO_RMS", "220"))
STT_SILENCE_TAIL_BLOCKS = int(os.getenv("STT_SILENCE_TAIL_BLOCKS", "6"))
STT_QUEUE_MAX_BLOCKS = int(os.getenv("STT_QUEUE_MAX_BLOCKS", "16"))
STT_VAD_ENABLED = os.getenv("STT_VAD_ENABLED", "1").lower() in ("1", "true", "yes", "on")
STT_NOISE_RMS_MULTIPLIER = float(os.getenv("STT_NOISE_RMS_MULTIPLIER", "1.6"))
STT_NOISE_RMS_ALPHA = float(os.getenv("STT_NOISE_RMS_ALPHA", "0.05"))
STT_PRE_ROLL_BLOCKS = int(os.getenv("STT_PRE_ROLL_BLOCKS", "4"))
STT_START_TRIGGER_BLOCKS = int(os.getenv("STT_START_TRIGGER_BLOCKS", "2"))
STT_RESTART_AFTER_RESPONSES = int(os.getenv("STT_RESTART_AFTER_RESPONSES", "3"))
STT_IDLE_RESTART_SECONDS = float(os.getenv("STT_IDLE_RESTART_SECONDS", "180"))
STT_LISTEN_POLL_SECONDS = float(os.getenv("STT_LISTEN_POLL_SECONDS", "1"))
TTS_VOICE_NAME = os.getenv("TTS_VOICE_NAME", "Microsoft Pavel")
TTS_POWERSHELL = os.getenv("TTS_POWERSHELL", "powershell.exe")
TTS_MAX_CHARS = int(os.getenv("TTS_MAX_CHARS", "800"))
TTS_STARTUP_TIMEOUT = float(os.getenv("TTS_STARTUP_TIMEOUT", "10"))
TTS_REQUEST_TIMEOUT = float(os.getenv("TTS_REQUEST_TIMEOUT", "60"))

LLM_URL = os.getenv("LLM_URL", "https://api.intelligence.io.solutions/api/v1/chat/completions")
LLM_MODEL = "meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8"

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_VISION_MODEL = "qwen/qwen2.5-vl-72b-instruct"
