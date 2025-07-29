import os

# Пути и параметры
MODEL_STT_PATH = os.getenv("MODEL_STT_PATH", "vosk-model-small-ru-0.22")
SR_STT = 16000
SR_TTS = 24000
BLOCKSIZE = 4000
DEVICE = os.getenv("DEVICE", "cpu")  # cpu или cuda

# LLM API
LLM_URL = os.getenv("LLM_URL", "https://api.intelligence.io.solutions/api/v1/chat/completions")
LLM_TOKEN = ("io-v2-eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJvd25lciI6IjA4ZjI3MDhhLWNlZGItNGJjYy1iYjc0LTg3Nzk4ZmZlNjk"
             "xMCIsImV4cCI6NDkwNjc2Mjg0NX0.lZsysp2ZNYAdV1htzfWnX-8uef5HGi7Z_qlzEVsPLxFvvj7i9oVpy3-o0pXGGtZLFYf-41kfv78g6UTDNkFSow")