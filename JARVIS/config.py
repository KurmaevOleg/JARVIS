#config.py
import os

# Пути и параметры
MODEL_STT_PATH = os.getenv("MODEL_STT_PATH", "vosk-model-small-ru-0.22")
SR_STT = 16000
SR_TTS = 24000
BLOCKSIZE = 4000
DEVICE = os.getenv("DEVICE", "cpu")
TORCH_NUM_THREADS = int(os.getenv("TORCH_NUM_THREADS", "2"))
TORCH_NUM_INTEROP_THREADS = int(os.getenv("TORCH_NUM_INTEROP_THREADS", "1"))
STT_RECOGNIZER_RESET_SECONDS = float(os.getenv("STT_RECOGNIZER_RESET_SECONDS", "20"))
STT_MIN_AUDIO_RMS = int(os.getenv("STT_MIN_AUDIO_RMS", "300"))
STT_SILENCE_TAIL_BLOCKS = int(os.getenv("STT_SILENCE_TAIL_BLOCKS", "6"))

LLM_URL = os.getenv("LLM_URL", "https://api.intelligence.io.solutions/api/v1/chat/completions")
LLM_MODEL = "meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8"

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_VISION_MODEL = "qwen/qwen2.5-vl-72b-instruct"
