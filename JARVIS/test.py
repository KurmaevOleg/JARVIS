#!/usr/bin/env python3
"""
Диагностика памяти JARVIS.

Запуск:
    python JARVIS/test.py
    python JARVIS/test.py --idle-seconds 120
    python JARVIS/test.py --skip-tts
    python JARVIS/test.py --skip-main
    python JARVIS/test.py --check-commands
"""

from __future__ import annotations

import argparse
import ctypes
import gc
import importlib
import os
import sys
import tempfile
import threading
import time
import traceback
from dataclasses import dataclass
from typing import Any, Callable

try:
    import psutil
except ImportError:
    psutil = None


MB = 1024 * 1024
PROCESS = psutil.Process(os.getpid()) if psutil is not None else None
KEEPALIVE: dict[str, Any] = {}


class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("PageFaultCount", ctypes.c_ulong),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
        ("PrivateUsage", ctypes.c_size_t),
    ]


@dataclass
class StepResult:
    name: str
    before_mb: float
    after_mb: float
    delta_mb: float
    seconds: float
    status: str


def windows_memory_info() -> tuple[int, int]:
    if os.name != "nt":
        raise RuntimeError("psutil не установлен, а fallback памяти доступен только на Windows.")

    counters = PROCESS_MEMORY_COUNTERS_EX()
    counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS_EX)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    psapi.GetProcessMemoryInfo.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(PROCESS_MEMORY_COUNTERS_EX),
        ctypes.c_ulong,
    ]
    psapi.GetProcessMemoryInfo.restype = ctypes.c_bool
    handle = kernel32.GetCurrentProcess()
    ok = psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb)
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    return int(counters.WorkingSetSize), int(counters.PrivateUsage)


def memory_mb() -> float:
    gc.collect()
    if PROCESS is not None:
        return PROCESS.memory_info().rss / MB
    working_set, _ = windows_memory_info()
    return working_set / MB


def private_mb() -> float | None:
    if PROCESS is None:
        return None

    try:
        info = PROCESS.memory_full_info()
    except (psutil.Error, AttributeError):
        return None

    value = getattr(info, "uss", None)
    if value is None:
        return None
    return value / MB


def process_rss_mb(pid: int | None) -> float | None:
    if PROCESS is None or not pid:
        return None

    try:
        return psutil.Process(pid).memory_info().rss / MB
    except psutil.Error:
        return None


def print_step_header() -> None:
    print()
    print(f"{'Этап':<42} {'До, МБ':>10} {'После, МБ':>12} {'Рост, МБ':>10} {'Время, с':>10}  Статус")
    print("-" * 104)


def print_step(result: StepResult) -> None:
    print(
        f"{result.name:<42} "
        f"{result.before_mb:>10.1f} "
        f"{result.after_mb:>12.1f} "
        f"{result.delta_mb:>10.1f} "
        f"{result.seconds:>10.2f}  "
        f"{result.status}"
    )


def measure(name: str, action: Callable[[], Any], keep_as: str | None = None) -> Any:
    before = memory_mb()
    started = time.perf_counter()
    status = "ok"
    result = None

    try:
        result = action()
        if keep_as is not None:
            KEEPALIVE[keep_as] = result
    except Exception as exc:
        status = f"error: {exc}"
        if os.getenv("JARVIS_TEST_TRACEBACK"):
            traceback.print_exc()

    if keep_as is None:
        result = None

    elapsed = time.perf_counter() - started
    after = memory_mb()
    print_step(StepResult(name, before, after, after - before, elapsed, status))
    return result


def import_module(name: str) -> Any:
    module = importlib.import_module(name)
    KEEPALIVE[f"module:{name}"] = module
    return module


def profile_idle_listener(listener: Any, stop_event: threading.Event, seconds: int, sample_interval: int) -> None:
    if seconds <= 0:
        return

    print()
    print(f"Проверка простоя микрофона: {seconds} сек. Интервал: {sample_interval} сек.")
    print(f"{'Секунда':>8} {'RSS, МБ':>10} {'Рост, МБ':>10} {'Private, МБ':>12}")
    print("-" * 46)

    errors: list[str] = []

    def listen_loop() -> None:
        try:
            with listener:
                while not stop_event.is_set():
                    listener.listen_once()
        except Exception as exc:
            errors.append(str(exc))

    baseline = memory_mb()
    thread = threading.Thread(target=listen_loop, name="jarvis-memory-listener", daemon=True)
    thread.start()

    started = time.monotonic()
    next_sample = started
    try:
        while True:
            now = time.monotonic()
            elapsed = int(now - started)
            if elapsed >= seconds:
                break
            if now >= next_sample:
                current = memory_mb()
                private = private_mb()
                private_text = f"{private:>12.1f}" if private is not None else f"{'n/a':>12}"
                print(f"{elapsed:>8} {current:>10.1f} {current - baseline:>10.1f} {private_text}")
                next_sample = now + sample_interval
            time.sleep(0.2)
    finally:
        stop_event.set()
        thread.join(timeout=5)

    current = memory_mb()
    private = private_mb()
    private_text = f"{private:>12.1f}" if private is not None else f"{'n/a':>12}"
    print(f"{seconds:>8} {current:>10.1f} {current - baseline:>10.1f} {private_text}")

    if errors:
        print(f"Ошибка во время простоя микрофона: {errors[0]}")


def check_command_routing() -> None:
    commands = import_module("commands")
    calls: list[tuple[str, str | None]] = []
    spoken: list[str] = []

    original_create = commands.create_and_open_file
    original_speak = commands.speak

    def fake_create(kind: str, name: str | None = None) -> str:
        calls.append((kind, name))
        return os.path.join(commands.CREATED_FILES_DIR, f"test.{ {'word': 'docx', 'excel': 'xlsx'}.get(kind, 'txt') }")

    def fake_speak(_tts_model, _silence, text: str) -> None:
        spoken.append(text)

    commands.create_and_open_file = fake_create
    commands.speak = fake_speak
    try:
        for phrase in ("дай ворот документ", "создай борт документ", "создай документ"):
            before = len(calls)
            handled = commands.handle_create_file(phrase, None, None)
            if not handled or len(calls) == before or calls[-1][0] != "word":
                raise AssertionError(f"Команда не распознана как Word/docx: {phrase}")

        for phrase in ("да иксэль таблицу", "дай эксель таблицу", "создай иксэль таблицу"):
            before = len(calls)
            handled = commands.handle_create_file(phrase, None, None)
            if not handled or len(calls) == before or calls[-1][0] != "excel":
                raise AssertionError(f"Команда не распознана как Excel/xlsx: {phrase}")

        screen_cases = {
            "что на экране": "",
            "прочитай экран": "",
            "сделай скриншот и опиши что за ошибка": "опиши что за ошибка",
            "сделай снимок экрана и расскажи как найти кнопку сохранить": "расскажи как найти кнопку сохранить",
            "найди кнопку настройки на экране": "найди кнопку настройки",
        }
        for phrase, expected in screen_cases.items():
            actual = commands.extract_screen_query(phrase)
            if actual != expected:
                raise AssertionError(f"Неверный screen-запрос: {phrase!r} -> {actual!r}, ожидалось {expected!r}")
    finally:
        commands.create_and_open_file = original_create
        commands.speak = original_speak

    print()
    print("Проверка команд: ok")
    print("Ослышки Word/Excel и screen-запросы маршрутизируются правильно.")


def run_memory_profile(args: argparse.Namespace) -> None:
    print("=== Диагностика памяти JARVIS ===")
    print(f"Python: {sys.executable}")
    print(f"PID: {os.getpid()}")
    print(f"Рабочая папка: {os.getcwd()}")
    private = private_mb()
    if private is not None:
        print(f"Стартовая память: RSS {memory_mb():.1f} МБ, private {private:.1f} МБ")
    else:
        print(f"Стартовая память: RSS {memory_mb():.1f} МБ")

    print_step_header()
    measure("Базовый процесс", lambda: None)

    config = measure("Импорт config", lambda: import_module("config"), keep_as="config")
    if config is not None:
        print(
            "Настройки: "
            f"STT_MIN_AUDIO_RMS={config.STT_MIN_AUDIO_RMS}, "
            f"BLOCKSIZE={config.BLOCKSIZE}, "
            f"STT_QUEUE_MAX_BLOCKS={config.STT_QUEUE_MAX_BLOCKS}, "
            f"STT_VAD_ENABLED={config.STT_VAD_ENABLED}, "
            f"STT_NOISE_RMS_MULTIPLIER={config.STT_NOISE_RMS_MULTIPLIER}, "
            f"STT_PRE_ROLL_BLOCKS={config.STT_PRE_ROLL_BLOCKS}, "
            f"STT_START_TRIGGER_BLOCKS={config.STT_START_TRIGGER_BLOCKS}, "
            f"TTS_VOICE_NAME={config.TTS_VOICE_NAME}, "
            f"TTS_MAX_CHARS={config.TTS_MAX_CHARS}"
        )

    tts_module = measure("Импорт tts (Microsoft OneCore)", lambda: import_module("tts"), keep_as="tts_module")
    stt_module = measure("Импорт stt (vosk/sounddevice)", lambda: import_module("stt"), keep_as="stt_module")
    commands_module = measure("Импорт commands", lambda: import_module("commands"), keep_as="commands_module")
    measure("Импорт assistant_worker/PyQt", lambda: import_module("assistant_worker"), keep_as="worker_module")

    if not args.skip_main:
        measure("Импорт main GUI", lambda: import_module("main"), keep_as="main_module")

    if args.check_commands and commands_module is not None:
        measure("Проверка маршрутизации команд", check_command_routing)

    stt_model = None
    listener = None
    stop_event = threading.Event()

    if not args.skip_stt and stt_module is not None:
        stt_model = measure("Загрузка STT модели Vosk", stt_module.initialize_stt, keep_as="stt_model")
        if stt_model is not None:
            listener = measure(
                "Создание SpeechListener/recognizer",
                lambda: stt_module.SpeechListener(stt_model, stop_event=stop_event),
                keep_as="speech_listener",
            )

    if not args.skip_tts and tts_module is not None:
        tts_engine = measure("Инициализация TTS Microsoft Pavel", tts_module.initialize_tts, keep_as="tts_engine")
        if tts_engine is not None and not args.skip_first_synth:
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
            tmp_path = tmp.name
            tmp.close()
            try:
                measure(
                    "Пробный синтез TTS без проигрывания",
                    lambda: tts_module.synthesize_tts(tts_engine, "ассистент готов", tmp_path),
                )
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
            helper = getattr(tts_engine, "_process", None)
            helper_rss = process_rss_mb(getattr(helper, "pid", None))
            if helper_rss is not None:
                print(f"TTS helper PowerShell RSS: {helper_rss:.1f} МБ")

    if listener is not None and args.idle_seconds > 0:
        profile_idle_listener(listener, stop_event, args.idle_seconds, args.sample_interval)

    print()
    print("=== Итог ===")
    private = private_mb()
    if private is not None:
        print(f"Финальная память: RSS {memory_mb():.1f} МБ, private {private:.1f} МБ")
    else:
        print(f"Финальная память: RSS {memory_mb():.1f} МБ")
    print("Смотрите строки с самым большим 'Рост, МБ' и рост RSS в простое микрофона.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Профилирование памяти JARVIS по этапам запуска.")
    parser.add_argument("--idle-seconds", type=int, default=60, help="Сколько секунд слушать микрофон в простое.")
    parser.add_argument("--sample-interval", type=int, default=10, help="Интервал печати памяти в простое.")
    parser.add_argument("--skip-stt", action="store_true", help="Не загружать Vosk/STT.")
    parser.add_argument("--skip-tts", action="store_true", help="Не инициализировать Microsoft Pavel TTS.")
    parser.add_argument("--skip-first-synth", action="store_true", help="Не измерять пробный TTS-синтез.")
    parser.add_argument("--skip-main", action="store_true", help="Не импортировать main.py/QtWidgets.")
    parser.add_argument("--check-commands", action="store_true", help="Проверить ослышки команд создания Word/Excel.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    run_memory_profile(args)


if __name__ == "__main__":
    main()
