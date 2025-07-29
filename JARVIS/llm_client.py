import requests
from config import LLM_URL, LLM_TOKEN

def chat_with_llm(prompt: str) -> str:
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LLM_TOKEN}"
    }
    payload = {
        "model": "meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8",
        "messages": [
            {"role": "system", "content": "Ты голосовой ассистент, отвечай кратко."},
            {"role": "user", "content": prompt}
        ]
    }
    resp = requests.post(LLM_URL, headers=headers, json=payload, timeout=10)
    resp.raise_for_status()
    return resp.json()['choices'][0]['message']['content'].strip()