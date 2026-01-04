import os

# Пути и параметры
MODEL_STT_PATH = os.getenv("MODEL_STT_PATH", "vosk-model-small-ru-0.22")
SR_STT = 16000
SR_TTS = 24000
BLOCKSIZE = 4000
DEVICE = os.getenv("DEVICE", "cpu")  # cpu или cuda

# LLM API
LLM_URL = os.getenv("LLM_URL", "https://api.intelligence.io.solutions/api/v1/chat/completions")
LLM_TOKEN = ("io-v2-eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJvd25lciI6IjRkZTkyZWNmLWRlMzEtNDRiZC1iZ"
                     "WVmLTNhZTRjNjAyNDkzNiIsImV4cCI6NDkyMDg2ODA1M30.VN9L1ofY-yqhCO4bXLxkL14H5xi-2VVZ9NRVe5Le9uS"
                     "PpPZNhxX3lEqhrcGvAYl9F7E-yMLFPtvyOwkcejZgdA")