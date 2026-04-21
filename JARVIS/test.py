#!/usr/bin/env python3
"""
Тест БЕСПЛАТНЫХ vision-моделей OpenRouter.
Проверяет, какие модели с суффиксом :free действительно работают и сколько времени занимает ответ.
"""

import base64
import io
import time
from PIL import Image, ImageDraw, ImageFont
from openai import OpenAI
from config import OPENROUTER_API_KEY, OPENROUTER_BASE_URL

# ---------- СПИСОК БЕСПЛАТНЫХ МОДЕЛЕЙ ДЛЯ ТЕСТА ----------
FREE_VISION_MODELS = [
    "qwen/qwen2.5-vl-32b-instruct:free",
    "google/gemma-3-4b-it:free",
    "meta-llama/llama-3.2-11b-vision-instruct:free",
    "openrouter/free",  # Роутер бесплатных моделей
]


# ---------- УТИЛИТЫ ----------
def create_test_image(width=400, height=300) -> bytes:
    """Создаёт простое тестовое изображение."""
    img = Image.new('RGB', (width, height), color='white')
    draw = ImageDraw.Draw(img)
    draw.ellipse((100, 50, 300, 250), fill='red', outline='black', width=3)
    try:
        font = ImageFont.load_default()
    except:
        font = None
    draw.text((120, 270), "Free Model Test", fill='black', font=font)

    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='JPEG')
    return img_byte_arr.getvalue()


def encode_image_to_base64(image_bytes: bytes) -> str:
    """Кодирует изображение в формат data URI."""
    return f"data:image/jpeg;base64,{base64.b64encode(image_bytes).decode('utf-8')}"


def test_free_model(client: OpenAI, model_name: str, prompt: str, image_data_uri: str) -> tuple[bool, float, str]:
    """Отправляет запрос к модели и возвращает (успех, время_ответа, ответ/ошибка)."""
    start_time = time.time()
    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": image_data_uri}}
                    ]
                }
            ],
            max_tokens=200,
            temperature=0.0,
            extra_headers={
                "HTTP-Referer": "https://github.com/yourusername/jarvis-assistant",
                "X-Title": "JARVIS Assistant"
            }
        )
        elapsed = time.time() - start_time
        answer = response.choices[0].message.content.strip()
        return True, elapsed, answer
    except Exception as e:
        elapsed = time.time() - start_time
        return False, elapsed, str(e)


# ---------- ГЛАВНАЯ ФУНКЦИЯ ТЕСТИРОВАНИЯ ----------
def main():
    print("=== Тест БЕСПЛАТНЫХ Vision-моделей OpenRouter ===\n")

    # 1. Инициализация клиента
    client = OpenAI(base_url=OPENROUTER_BASE_URL, api_key=OPENROUTER_API_KEY)
    print("✅ Клиент инициализирован\n")

    # 2. Подготовка изображения
    image_bytes = create_test_image()
    image_data_uri = encode_image_to_base64(image_bytes)
    print("✅ Тестовое изображение подготовлено\n")

    prompt = "Опиши, что нарисовано на картинке, в 10 словах."

    # 3. Тестирование каждой модели
    print("Результаты тестирования бесплатных моделей:")
    print("-" * 60)

    for model in FREE_VISION_MODELS:
        print(f"Тест: {model}")
        success, elapsed, result = test_free_model(client, model, prompt, image_data_uri)

        if success:
            print(f"  ✅ УСПЕХ! Время: {elapsed:.2f} сек.")
            print(f"  Ответ: {result[:100]}...")
        else:
            print(f"  ❌ ОШИБКА! Время: {elapsed:.2f} сек.")
            print(f"  Текст ошибки: {result[:100]}...")
        print()

    print("-" * 60)
    print("=== Тест завершён ===")


if __name__ == "__main__":
    main()