#config.py
import os

# Пути и параметры
MODEL_STT_PATH = os.getenv("MODEL_STT_PATH", "vosk-model-small-ru-0.22")
SR_STT = 16000
SR_TTS = 24000
BLOCKSIZE = 4000
DEVICE = os.getenv("DEVICE", "cpu")

LLM_URL = os.getenv("LLM_URL", "https://api.intelligence.io.solutions/api/v1/chat/completions")
LLM_MODEL = "meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8"

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_VISION_MODEL = "qwen/qwen2.5-vl-72b-instruct"
