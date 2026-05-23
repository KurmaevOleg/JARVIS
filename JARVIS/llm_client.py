# llm_client.py
import base64
import requests
from io import BytesIO
from PIL import Image
from openai import OpenAI
from config import (
    LLM_URL, LLM_MODEL,
    OPENROUTER_BASE_URL, OPENROUTER_VISION_MODEL
)
from secret_store import (
    LLM_TOKEN as LLM_TOKEN_SECRET,
    OPENROUTER_API_KEY as OPENROUTER_API_KEY_SECRET,
    get_secret,
)

# Список fallback моделей для vision (первая основная, затем запасные)
VISION_MODELS_FALLBACK = [
    OPENROUTER_VISION_MODEL,                 # qwen/qwen2.5-vl-72b-instruct
    "openai/gpt-4o-mini",
]

def _limit_words(text: str, max_words: int = 50) -> str:
    """Обрезает текст до указанного количества слов."""
    words = text.split()
    if len(words) <= max_words:
        return text
    return ' '.join(words[:max_words]) + '...'

def _require_secret(spec) -> str:
    value = get_secret(spec)
    if not value:
        raise RuntimeError(f"Не задан {spec.label}. Откройте в приложении «Ключи доступа» и сохраните ключи.")
    return value

def _openrouter_client() -> OpenAI:
    return OpenAI(
        base_url=OPENROUTER_BASE_URL,
        api_key=_require_secret(OPENROUTER_API_KEY_SECRET)
    )

def _query_vision_model(model_name: str, prompt: str, data_uri: str) -> str:
    """Один запрос к указанной vision-модели OpenRouter."""
    response = _openrouter_client().chat.completions.create(
        model=model_name,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_uri}}
                ]
            }
        ],
        max_tokens=350,
        temperature=0.0,
        extra_headers={
            "HTTP-Referer": "https://github.com/olegjarvis/jarvis",
            "X-Title": "JARVIS Assistant"
        }
    )
    answer = response.choices[0].message.content
    return answer.strip() if answer else ""

def chat_with_llm(prompt: str, image_path: str = None) -> str:
    """
    Универсальная функция:
    - image_path не None → отправляет изображение в OpenRouter Vision с fallback,
      обрезает ответ до 50 слов.
    - иначе → текстовый запрос через io.net.
    """
    if image_path:
        # Vision-запрос с fallback
        try:
            img = Image.open(image_path).convert("RGB")
            buffer = BytesIO()
            img.save(buffer, format="JPEG", quality=85, optimize=True)
            img_bytes = buffer.getvalue()
            img_base64 = base64.b64encode(img_bytes).decode("utf-8")
            data_uri = f"data:image/jpeg;base64,{img_base64}"

            last_error = None
            for model in VISION_MODELS_FALLBACK:
                try:
                    print(f"[Vision] Пробую модель: {model}")
                    answer = _query_vision_model(model, prompt, data_uri)
                    if answer:
                        short = _limit_words(answer, max_words=50)
                        print(f"[Vision] Ответ ({model}): {short}")
                        return short
                    else:
                        last_error = "пустой ответ"
                except Exception as e:
                    last_error = str(e)
                    print(f"[Vision] Ошибка с {model}: {e}")
                    continue

            raise Exception(f"Все модели не ответили: {last_error}")

        except Exception as e:
            raise Exception(f"Ошибка Vision: {e}")

    else:
        # Текстовый запрос через io.net
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {_require_secret(LLM_TOKEN_SECRET)}"
        }
        payload = {
            "model": LLM_MODEL,
            "messages": [
                {"role": "system", "content": "Ты голосовой ассистент. Отвечай кратко, по-русски, 1-3 предложения."},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 150,
            "temperature": 0.0
        }
        try:
            resp = requests.post(LLM_URL, headers=headers, json=payload, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"].strip()
            return content
        except Exception as e:
            raise Exception(f"Ошибка io.net: {e}")
