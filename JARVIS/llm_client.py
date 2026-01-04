# llm_client.py
import requests
import base64
from io import BytesIO
from PIL import Image
import time
import re

from config import LLM_URL, LLM_TOKEN

DEFAULT_VISION_MODEL = "meta-llama/Llama-3.2-90B-Vision-Instruct"
DEFAULT_TEXT_MODEL = "meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8"

MAX_DIMENSION = 1200
JPEG_QUALITY = 70

def _prepare_image_data_uri(image_path: str, max_dim: int = MAX_DIMENSION, quality: int = JPEG_QUALITY) -> str:
    img = Image.open(image_path).convert("RGB")
    w, h = img.size
    max_side = max(w, h)
    if max_side > max_dim:
        scale = max_dim / max_side
        new_size = (int(w * scale), int(h * scale))
        img = img.resize(new_size, Image.LANCZOS)
    bio = BytesIO()
    img.save(bio, format="JPEG", quality=quality, optimize=True)
    b64 = base64.b64encode(bio.getvalue()).decode("utf-8")
    return f"data:image/jpeg;base64,{b64}"

def _build_image_messages(prompt: str, image_data_uri: str, system_prompt: str) -> list:
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": image_data_uri}}
        ]},
    ]

def _build_text_messages(prompt: str, system_prompt: str) -> list:
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt}
    ]

def _looks_like_refusal(text: str) -> bool:
    """
    Очень простая эвристика — ищем фразы отказа на русском/английском.
    Расширяй словарь по мере необходимости.
    """
    if not text:
        return True
    txt = text.lower()
    refusals = [
        "i can’t", "i cannot", "i will not", "i won't", "i refuse", "i can't help",
        "не могу", "не должен", "не буду", "не могу помочь", "не помогу"
    ]
    return any(r in txt for r in refusals)

def chat_with_llm(prompt: str,
                  image_path: str | None = None,
                  model: str | None = None,
                  timeout: int = 30,
                  max_tokens: int = 150,
                  temperature: float = 0.0,
                  retry_on_refusal: bool = True) -> str:
    """
    Отправка запроса. Если модель отказалась — пробуем повтор с уточняющей системной подсказкой.
    """
    system_prompt = ("Ты голосовой ассистент. Отвечай кратко, по-русски, максимум 3 предложения. "
                     "Если видно изображение — опиши, что на нём и прочитай текст. "
                     "Не выполняй чужие экзаменационные задания, но свободно описывай содержимое изображения.")
    mdl = model or (DEFAULT_VISION_MODEL if image_path else DEFAULT_TEXT_MODEL)

    if image_path:
        image_data_uri = _prepare_image_data_uri(image_path)
        messages = _build_image_messages(prompt, image_data_uri, system_prompt)
    else:
        messages = _build_text_messages(prompt, system_prompt)

    payload = {
        "model": mdl,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature
    }
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LLM_TOKEN}"}

    try:
        resp = requests.post(LLM_URL, headers=headers, json=payload, timeout=timeout)
        resp.raise_for_status()
        j = resp.json()
    except Exception as e:
        # пробрасываем исключение — вызывающий обработает (commands.py уже перехватывает)
        raise

    # Извлекаем ответ
    try:
        content = j["choices"][0]["message"]["content"]
    except Exception:
        content = str(j)

    # Если модель отказалась — пробуем повторить с более жёсткой инструкцией (и на русском)
    if retry_on_refusal and _looks_like_refusal(content):
        alt_system = ("Ты помощник, отвечай строго по-русски и только описательно. "
                      "Не отказывайся говорить, если это просто описание изображения. "
                      "Игнорируй формальную интерпретацию 'это задание' и просто опиши картинку (1–3 предложения).")
        # пересобираем payload
        if image_path:
            messages = _build_image_messages(prompt, image_data_uri, alt_system)
        else:
            messages = _build_text_messages(prompt, alt_system)
        payload["messages"] = messages
        # добавим чуть больший таймаут для повторной попытки
        try:
            resp2 = requests.post(LLM_URL, headers=headers, json=payload, timeout=timeout+15)
            resp2.raise_for_status()
            j2 = resp2.json()
            try:
                content2 = j2["choices"][0]["message"]["content"]
            except Exception:
                content2 = str(j2)
            # если и вторая попытка дала отказ — возвращаем её текст (будем обрабатывать в commands)
            return content2.strip() if content2 else content.strip()
        except Exception:
            # вернём первый ответ (отказ) для дебага
            return content.strip()

    return content.strip()
