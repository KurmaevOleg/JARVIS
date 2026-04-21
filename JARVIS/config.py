import os

# Пути и параметры
MODEL_STT_PATH = os.getenv("MODEL_STT_PATH", "vosk-model-small-ru-0.22")
SR_STT = 16000
SR_TTS = 24000
BLOCKSIZE = 4000
DEVICE = os.getenv("DEVICE", "cpu")  # cpu или cuda

# --- LLM (io.net) для текстовых запросов ---
LLM_URL = os.getenv("LLM_URL", "https://api.intelligence.io.solutions/api/v1/chat/completions")
LLM_TOKEN = ("io-v2-eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJvd25lciI6IjRkZTkyZWNmLWRlMzEtNDRiZC1iZ"
                     "WVmLTNhZTRjNjAyNDkzNiIsImV4cCI6NDkyMDg2ODA1M30.VN9L1ofY-yqhCO4bXLxkL14H5xi-2VVZ9NRVe5Le9uS"
                     "PpPZNhxX3lEqhrcGvAYl9F7E-yMLFPtvyOwkcejZgdA")
LLM_MODEL = "meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8"  # или другая текстовая модель io.net

# --- OpenRouter для Vision ---
OPENROUTER_API_KEY = "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"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_VISION_MODEL = "qwen/qwen2.5-vl-72b-instruct"  # проверенная рабочая модель
