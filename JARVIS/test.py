import base64, requests
from JARVIS.config import LLM_TOKEN

with open("screenshot.png", "rb") as f:
    img_b64 = base64.b64encode(f.read()).decode("utf-8")

data = {
    "model": "meta-llama/Llama-3.2-90B-Vision-Instruct",
    "messages": [
        {"role": "system", "content": "Ты мульти-модальная модель, анализируй картинку."},
        {"role": "user", "content": [
            {"type": "text", "text": "Опиши, что на изображении и прочитай текст, если он есть."},
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{img_b64}"}
            }
        ]}
    ]
}

resp = requests.post(
    "https://api.intelligence.io.solutions/api/v1/chat/completions",
    headers={"Authorization": f"Bearer {LLM_TOKEN}", "Content-Type": "application/json"},
    json=data
)
print(resp.json())
