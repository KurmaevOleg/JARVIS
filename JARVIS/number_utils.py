# number_utils.py
import re

WORD_TO_NUM = {
    "ноль": 0, "один": 1, "одну": 1, "две": 2, "два": 2, "три": 3, "четыре": 4,
    "пять": 5, "шесть": 6, "семь": 7, "восемь": 8, "девять": 9, "десять": 10,
    "одиннадцать": 11, "двенадцать": 12, "тринадцать": 13, "четырнадцать": 14,
    "пятнадцать": 15, "шестнадцать": 16, "семнадцать": 17, "восемнадцать": 18,
    "девятнадцать": 19, "двадцать": 20, "тридцать": 30, "сорок": 40, "пятьдесят": 50,
    "шестьдесят": 60, "семьдесят": 70, "восемьдесят": 80, "девяносто": 90,
    "сто": 100, "двести": 200, "триста": 300, "четыреста": 400, "пятьсот": 500,
    "шестьсот": 600, "семьсот": 700, "восемьсот": 800, "девятьсот": 900
}

NUM_TO_WORD = {
    0: "ноль", 1: "один", 2: "два", 3: "три", 4: "четыре", 5: "пять",
    6: "шесть", 7: "семь", 8: "восемь", 9: "девять", 10: "десять",
    11: "одиннадцать", 12: "двенадцать", 13: "тринадцать", 14: "четырнадцать",
    15: "пятнадцать", 16: "шестнадцать", 17: "семнадцать", 18: "восемнадцать",
    19: "девятнадцать", 20: "двадцать", 30: "тридцать", 40: "сорок",
    50: "пятьдесят", 60: "шестьдесят", 70: "семьдесят", 80: "восемьдесят",
    90: "девяносто", 100: "сто", 200: "двести", 300: "триста",
    400: "четыреста", 500: "пятьсот", 600: "шестьсот", 700: "семьсот",
    800: "восемьсот", 900: "девятьсот"
}

def parse_number(text: str) -> int | None:
    """Извлекает число из текста (цифрами или словами)."""

    # 1. Сначала ищем цифры
    digit_match = re.search(r'\b(\d+)\b', text)
    if digit_match:
        return int(digit_match.group(1))

    text = text.lower()

    # 2. Сортируем слова по длине (чтобы "двадцать" шло раньше "два")
    for word in sorted(WORD_TO_NUM.keys(), key=len, reverse=True):
        if re.search(rf'\b{word}\b', text):
            return WORD_TO_NUM[word]

    return None

def number_to_words(num: int) -> str:
    """Преобразует целое число в русские слова (до 999)."""
    if num in NUM_TO_WORD:
        return NUM_TO_WORD[num]
    if 20 < num < 100:
        tens = (num // 10) * 10
        units = num % 10
        if units == 0:
            return NUM_TO_WORD[tens]
        return f"{NUM_TO_WORD[tens]} {NUM_TO_WORD[units]}"
    if 100 <= num < 1000:
        hundreds = (num // 100) * 100
        rest = num % 100
        if rest == 0:
            return NUM_TO_WORD[hundreds]
        rest_words = number_to_words(rest)
        return f"{NUM_TO_WORD[hundreds]} {rest_words}"
    return str(num)

def replace_numbers_with_words(text: str) -> str:
    """Заменяет все целые числа в тексте на их словесное представление."""
    def repl(match):
        num = int(match.group(0))
        return number_to_words(num)
    return re.sub(r'\b\d+\b', repl, text)

def replace_numbers_for_speech(text: str) -> str:
    """
    Подготовка текста для озвучки:
    - целые числа -> слова
    - дроби вида 1.9 / 6,4 -> один целых девять / шесть целых четыре
    - проценты оставляем как обычный текст, но число преобразуем
    """
    def decimal_repl(match):
        whole = int(match.group(1))
        frac = match.group(2)
        try:
            whole_words = number_to_words(whole)
            frac_words = " ".join(number_to_words(int(d)) for d in frac)
            return f"{whole_words} целых {frac_words}"
        except Exception:
            return match.group(0)

    # сначала дроби
    text = re.sub(r'\b(\d+)[\.,](\d+)\b', decimal_repl, text)

    # потом обычные целые
    text = replace_numbers_with_words(text)
    return text