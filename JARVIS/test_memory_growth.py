#!/usr/bin/env python3
"""
Диагностика постоянного роста памяти JARVIS по источникам.

Примеры:
    python JARVIS/test_memory_growth.py --scenario baseline --seconds 120
    python JARVIS/test_memory_growth.py --scenario mic-raw --seconds 120
    python JARVIS/test_memory_growth.py --scenario synthetic-vosk --seconds 120
    python JARVIS/test_memory_growth.py --scenario listener --seconds 120
    python JARVIS/test_memory_growth.py --scenario listener --seconds 120 --stt-rms-threshold 300
    python JARVIS/test_memory_growth.py --scenario tts-helper --seconds 120 --tts-synth-interval 10

Как читать результат:
    - Растет Python heap: вероятна Python-структура, очередь, лог, список, кеш.
    - Растет RSS/private, но Python heap почти стоит: вероятна native-память
      расширений или дочернего процесса: Vosk, PortAudio/sounddevice, PowerShell TTS.
    - mic-raw стабилен, listener растет: вероятен Vosk recognizer или логика SpeechListener.
    - synthetic-vosk растет без микрофона: рост внутри Vosk recognizer.
    - tts-helper растет в child RSS: рост внутри постоянного PowerShell/OneCore helper.
"""

from __future__ import annotations

import argparse
import ctypes
import gc
import json
import os
import random
import sys
import tempfile
import threading
import time
import tracemalloc
import warnings
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Callable

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
warnings.filterwarnings("ignore", category=DeprecationWarning, message="'audioop' is deprecated.*")

try:
    import psutil
except ImportError:
    psutil = None


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

MB = 1024 * 1024
PROCESS = psutil.Process(os.getpid()) if psutil is not None else None


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
class MemorySample:
    second: float
    rss_mb: float
    private_mb: float | None
    py_heap_mb: float
    py_peak_mb: float
    native_delta_mb: float
    child_rss_mb: float
    handles: int | None
    threads: int | None
    details: dict[str, Any]


def windows_memory_info() -> tuple[int, int]:
    if os.name != "nt":
        return 0, 0

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
        return 0, 0
    return int(counters.WorkingSetSize), int(counters.PrivateUsage)


def process_memory() -> tuple[float, float | None]:
    if PROCESS is not None:
        rss = PROCESS.memory_info().rss / MB
        private = None
        try:
            info = PROCESS.memory_full_info()
            private_value = getattr(info, "uss", None)
            if private_value is not None:
                private = private_value / MB
        except (psutil.Error, AttributeError):
            pass
        return rss, private

    working_set, private_usage = windows_memory_info()
    return working_set / MB, private_usage / MB if private_usage else None


def child_rss_mb() -> float:
    if PROCESS is None:
        return 0.0

    total = 0
    try:
        for child in PROCESS.children(recursive=True):
            try:
                total += child.memory_info().rss
            except psutil.Error:
                pass
    except psutil.Error:
        return 0.0
    return total / MB


def handle_count() -> int | None:
    if PROCESS is None:
        return None
    try:
        return PROCESS.num_handles() if hasattr(PROCESS, "num_handles") else None
    except psutil.Error:
        return None


def thread_count() -> int | None:
    if PROCESS is None:
        return None
    try:
        return PROCESS.num_threads()
    except psutil.Error:
        return None


def slope_mb_per_min(samples: list[MemorySample], getter: Callable[[MemorySample], float]) -> float:
    if len(samples) < 2:
        return 0.0
    first = samples[0]
    last = samples[-1]
    seconds = max(0.001, last.second - first.second)
    return (getter(last) - getter(first)) / seconds * 60.0


class GrowthProfiler:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.samples: list[MemorySample] = []
        self._baseline_rss: float | None = None
        self._baseline_py: float | None = None

    def sample(self, second: float, details: dict[str, Any] | None = None) -> None:
        if self.args.gc_each_sample:
            gc.collect()

        rss, private = process_memory()
        py_current, py_peak = tracemalloc.get_traced_memory()
        py_mb = py_current / MB
        py_peak_mb = py_peak / MB

        if self._baseline_rss is None:
            self._baseline_rss = rss
            self._baseline_py = py_mb

        native_delta = (rss - self._baseline_rss) - (py_mb - (self._baseline_py or 0.0))
        sample = MemorySample(
            second=second,
            rss_mb=rss,
            private_mb=private,
            py_heap_mb=py_mb,
            py_peak_mb=py_peak_mb,
            native_delta_mb=native_delta,
            child_rss_mb=child_rss_mb(),
            handles=handle_count(),
            threads=thread_count(),
            details=details or {},
        )
        self.samples.append(sample)
        print_sample(sample, self.samples[0])

    def finish(self, scenario: str) -> None:
        if not self.samples:
            return

        first = self.samples[0]
        last = self.samples[-1]
        rss_delta = last.rss_mb - first.rss_mb
        private_delta = None if first.private_mb is None or last.private_mb is None else last.private_mb - first.private_mb
        py_delta = last.py_heap_mb - first.py_heap_mb
        child_delta = last.child_rss_mb - first.child_rss_mb
        native_delta = rss_delta - py_delta

        print()
        print("=== Итог сценария ===")
        print(f"Сценарий: {scenario}")
        print(f"RSS: {first.rss_mb:.1f} -> {last.rss_mb:.1f} МБ, рост {rss_delta:.1f} МБ")
        if private_delta is not None:
            print(f"Private: {first.private_mb:.1f} -> {last.private_mb:.1f} МБ, рост {private_delta:.1f} МБ")
        print(f"Python heap: {first.py_heap_mb:.1f} -> {last.py_heap_mb:.1f} МБ, рост {py_delta:.1f} МБ")
        print(f"Native/не Python оценка: рост {native_delta:.1f} МБ")
        print(f"Child RSS: {first.child_rss_mb:.1f} -> {last.child_rss_mb:.1f} МБ, рост {child_delta:.1f} МБ")
        print(f"Скорость RSS: {slope_mb_per_min(self.samples, lambda s: s.rss_mb):.1f} МБ/мин")
        print(f"Скорость Python heap: {slope_mb_per_min(self.samples, lambda s: s.py_heap_mb):.1f} МБ/мин")
        print(f"Скорость child RSS: {slope_mb_per_min(self.samples, lambda s: s.child_rss_mb):.1f} МБ/мин")
        print_diagnosis(rss_delta, py_delta, child_delta, scenario)

        if self.args.json_report:
            path = Path(self.args.json_report).resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "scenario": scenario,
                "args": vars(self.args),
                "samples": [asdict(sample) for sample in self.samples],
                "summary": {
                    "rss_delta_mb": rss_delta,
                    "private_delta_mb": private_delta,
                    "python_heap_delta_mb": py_delta,
                    "native_delta_estimate_mb": native_delta,
                    "child_rss_delta_mb": child_delta,
                },
            }
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"JSON-отчет: {path}")


def format_private(value: float | None) -> str:
    return f"{value:>9.1f}" if value is not None else f"{'n/a':>9}"


def details_text(details: dict[str, Any]) -> str:
    if not details:
        return ""
    parts = []
    for key, value in details.items():
        if isinstance(value, float):
            parts.append(f"{key}={value:.1f}")
        else:
            parts.append(f"{key}={value}")
    text = ", ".join(parts)
    return text[:90]


def print_header() -> None:
    print()
    print(
        f"{'Сек':>6} {'RSS':>8} {'dRSS':>8} {'Private':>9} "
        f"{'PyHeap':>8} {'dPy':>8} {'NativeD':>9} {'Child':>8} "
        f"{'Handles':>8} {'Thr':>5}  Детали"
    )
    print("-" * 118)


def print_sample(sample: MemorySample, first: MemorySample) -> None:
    print(
        f"{sample.second:>6.0f} "
        f"{sample.rss_mb:>8.1f} "
        f"{sample.rss_mb - first.rss_mb:>8.1f} "
        f"{format_private(sample.private_mb)} "
        f"{sample.py_heap_mb:>8.1f} "
        f"{sample.py_heap_mb - first.py_heap_mb:>8.1f} "
        f"{sample.native_delta_mb:>9.1f} "
        f"{sample.child_rss_mb:>8.1f} "
        f"{str(sample.handles if sample.handles is not None else 'n/a'):>8} "
        f"{str(sample.threads if sample.threads is not None else 'n/a'):>5}  "
        f"{details_text(sample.details)}"
    )


def print_diagnosis(rss_delta: float, py_delta: float, child_delta: float, scenario: str) -> None:
    print()
    print("=== Быстрая интерпретация ===")
    if abs(rss_delta) < 3:
        print("Рост RSS небольшой. На этом сценарии явной утечки не видно.")
        return

    if child_delta > max(5.0, rss_delta * 0.4):
        print("Заметно растет дочерний процесс. Проверь TTS helper PowerShell/OneCore.")
    elif py_delta > max(3.0, rss_delta * 0.4):
        print("Заметно растет Python heap. Ищи Python-накопление: очередь, список, кеш, лог, изображения.")
    else:
        print("RSS/private растет сильнее Python heap. Вероятен native-рост: Vosk, PortAudio/sounddevice или системная библиотека.")

    if scenario == "listener":
        print("Если mic-raw стабилен, а listener растет, главный подозреваемый - Vosk recognizer или подача постоянной тишины/шума в него.")
    elif scenario == "synthetic-vosk":
        print("Если здесь есть рост без микрофона, причина внутри Vosk recognizer или способа подачи блоков.")
    elif scenario == "mic-raw":
        print("Если здесь есть рост без Vosk, причина ближе к sounddevice/PortAudio или драйверу микрофона.")
    elif scenario == "tts-helper":
        print("Если растет child RSS, причина в постоянном PowerShell/OneCore helper.")


def run_timed(
    args: argparse.Namespace,
    profiler: GrowthProfiler,
    details: Callable[[], dict[str, Any]],
    tick: Callable[[], None] | None = None,
) -> None:
    print_header()
    started = time.monotonic()
    next_sample = started

    while True:
        now = time.monotonic()
        elapsed = now - started
        if elapsed >= args.seconds:
            break

        if tick is not None:
            tick()

        if now >= next_sample:
            profiler.sample(elapsed, details())
            next_sample = now + args.interval

        time.sleep(args.loop_sleep)

    profiler.sample(args.seconds, details())


def scenario_baseline(args: argparse.Namespace, profiler: GrowthProfiler) -> None:
    run_timed(args, profiler, details=lambda: {})


def scenario_tts_helper(args: argparse.Namespace, profiler: GrowthProfiler) -> None:
    import tts

    engine = tts.initialize_tts()
    synth_count = 0
    last_synth = 0.0
    temp_paths: list[str] = []

    def tick() -> None:
        nonlocal synth_count, last_synth
        if args.tts_synth_interval <= 0:
            return
        now = time.monotonic()
        if now - last_synth < args.tts_synth_interval:
            return
        last_synth = now
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        tmp_path = tmp.name
        tmp.close()
        tts.synthesize_tts(engine, f"Проверка памяти номер {synth_count + 1}", tmp_path)
        temp_paths.append(tmp_path)
        synth_count += 1

    def details() -> dict[str, Any]:
        helper = getattr(engine, "_process", None)
        helper_pid = getattr(helper, "pid", None)
        helper_rss = 0.0
        if helper_pid and psutil is not None:
            try:
                helper_rss = psutil.Process(helper_pid).memory_info().rss / MB
            except psutil.Error:
                helper_rss = 0.0
        return {"helper_pid": helper_pid or 0, "helper_rss": helper_rss, "synth": synth_count}

    try:
        run_timed(args, profiler, details=details, tick=tick)
    finally:
        engine.close()
        for path in temp_paths:
            try:
                os.unlink(path)
            except OSError:
                pass


def scenario_mic_raw(args: argparse.Namespace, profiler: GrowthProfiler) -> None:
    import audioop
    import sounddevice as sd
    from config import BLOCKSIZE, SR_STT

    counters = {"blocks": 0, "bytes_mb": 0.0, "avg_rms": 0.0}
    rms_total = 0

    def callback(indata, frames, time_info, status) -> None:
        nonlocal rms_total
        data = bytes(indata)
        counters["blocks"] += 1
        counters["bytes_mb"] += len(data) / MB
        try:
            rms_total += audioop.rms(data, 2)
            counters["avg_rms"] = rms_total / max(1, counters["blocks"])
        except audioop.error:
            pass

    def details() -> dict[str, Any]:
        return dict(counters)

    with sd.RawInputStream(
        samplerate=SR_STT,
        blocksize=args.blocksize or BLOCKSIZE,
        dtype="int16",
        channels=1,
        callback=callback,
    ):
        run_timed(args, profiler, details=details)


def make_audio_block(args: argparse.Namespace) -> bytes:
    from config import BLOCKSIZE

    blocksize = args.blocksize or BLOCKSIZE
    if args.synthetic_audio == "noise":
        rng = random.Random(args.seed)
        samples = bytearray()
        for _ in range(blocksize):
            value = rng.randint(-args.noise_level, args.noise_level)
            samples.extend(int(value).to_bytes(2, "little", signed=True))
        return bytes(samples)
    return bytes(blocksize * 2)


def scenario_synthetic_vosk(args: argparse.Namespace, profiler: GrowthProfiler) -> None:
    import vosk
    from config import MODEL_STT_PATH, SR_STT, BLOCKSIZE

    if not os.path.exists(MODEL_STT_PATH):
        raise FileNotFoundError(f"STT модель не найдена: {MODEL_STT_PATH}")

    model = vosk.Model(MODEL_STT_PATH)
    recognizer = vosk.KaldiRecognizer(model, SR_STT)
    block = make_audio_block(args)
    block_duration = (args.blocksize or BLOCKSIZE) / SR_STT
    counters = {"blocks": 0, "accepts": 0, "results": 0, "resets": 0, "audio": args.synthetic_audio}
    next_feed = time.monotonic()
    next_reset = time.monotonic() + args.recognizer_reset_interval if args.recognizer_reset_interval > 0 else None

    def tick() -> None:
        nonlocal recognizer, next_feed, next_reset
        now = time.monotonic()
        if next_reset is not None and now >= next_reset:
            recognizer = vosk.KaldiRecognizer(model, SR_STT)
            counters["resets"] += 1
            next_reset = now + args.recognizer_reset_interval

        feeds = 0
        max_feeds = 1 if args.synthetic_realtime else args.synthetic_burst
        while feeds < max_feeds and (not args.synthetic_realtime or now >= next_feed):
            accepted = recognizer.AcceptWaveform(block)
            counters["blocks"] += 1
            if accepted:
                counters["accepts"] += 1
                _ = recognizer.Result()
                counters["results"] += 1
            feeds += 1
            if args.synthetic_realtime:
                next_feed += block_duration

    def details() -> dict[str, Any]:
        return dict(counters)

    run_timed(args, profiler, details=details, tick=tick)


def scenario_listener(args: argparse.Namespace, profiler: GrowthProfiler) -> None:
    import stt

    if args.stt_rms_threshold is not None:
        stt.STT_MIN_AUDIO_RMS = args.stt_rms_threshold
    if args.stt_vad_enabled is not None:
        stt.STT_VAD_ENABLED = args.stt_vad_enabled
    if args.stt_noise_multiplier is not None:
        stt.STT_NOISE_RMS_MULTIPLIER = args.stt_noise_multiplier
    if args.stt_noise_alpha is not None:
        stt.STT_NOISE_RMS_ALPHA = args.stt_noise_alpha
    if args.stt_pre_roll_blocks is not None:
        stt.STT_PRE_ROLL_BLOCKS = args.stt_pre_roll_blocks
    if args.stt_start_trigger_blocks is not None:
        stt.STT_START_TRIGGER_BLOCKS = args.stt_start_trigger_blocks
    if args.blocksize is not None:
        stt.BLOCKSIZE = args.blocksize
    if args.queue_max_blocks is not None:
        stt.STT_QUEUE_MAX_BLOCKS = args.queue_max_blocks

    model = stt.initialize_stt()
    stop_event = threading.Event()
    listener = stt.SpeechListener(model, stop_event=stop_event)
    counters = {"blocks": 0, "bytes_mb": 0.0, "texts": 0, "ends": 0}
    original_put_audio = listener._put_audio
    original_put_end_marker = listener._put_end_marker

    def counted_put_audio(data: bytes) -> None:
        counters["blocks"] += 1
        counters["bytes_mb"] += len(data) / MB
        original_put_audio(data)

    def counted_put_end_marker() -> None:
        counters["ends"] += 1
        original_put_end_marker()

    listener._put_audio = counted_put_audio
    listener._put_end_marker = counted_put_end_marker

    def listen_loop() -> None:
        with listener:
            while not stop_event.is_set():
                text = listener.listen_once()
                if text:
                    counters["texts"] += 1

    thread = threading.Thread(target=listen_loop, name="jarvis-growth-listener", daemon=True)

    def details() -> dict[str, Any]:
        return {
            "last_rms": listener._last_rms,
            "thr": listener._last_threshold,
            "noise": listener._noise_rms,
            "pre": len(listener._pre_roll),
            "start": listener._speech_start_blocks,
            "vad": int(stt.STT_VAD_ENABLED),
            "min_rms": stt.STT_MIN_AUDIO_RMS,
            **counters,
            "queue": listener.queue.qsize(),
            "voice_active": int(listener._voice_active),
        }

    try:
        thread.start()
        run_timed(args, profiler, details=details)
    finally:
        stop_event.set()
        thread.join(timeout=5)


SCENARIOS: dict[str, Callable[[argparse.Namespace, GrowthProfiler], None]] = {
    "baseline": scenario_baseline,
    "tts-helper": scenario_tts_helper,
    "mic-raw": scenario_mic_raw,
    "synthetic-vosk": scenario_synthetic_vosk,
    "listener": scenario_listener,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ищет источник постоянного роста памяти JARVIS.")
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), default="listener", help="Что именно тестировать.")
    parser.add_argument("--seconds", type=int, default=120, help="Длительность сценария.")
    parser.add_argument("--interval", type=int, default=10, help="Интервал вывода метрик.")
    parser.add_argument("--loop-sleep", type=float, default=0.02, help="Пауза внутреннего цикла теста.")
    parser.add_argument("--json-report", default="", help="Куда сохранить подробный JSON-отчет.")
    parser.add_argument("--no-gc-each-sample", dest="gc_each_sample", action="store_false", help="Не вызывать gc.collect перед замером.")
    parser.set_defaults(gc_each_sample=True)

    parser.add_argument("--stt-rms-threshold", type=int, default=None, help="Переопределить STT_MIN_AUDIO_RMS для listener.")
    parser.add_argument("--stt-vad-enabled", action="store_true", default=None, help="Включить VAD в listener.")
    parser.add_argument("--no-stt-vad", dest="stt_vad_enabled", action="store_false", help="Выключить VAD в listener.")
    parser.add_argument("--stt-noise-multiplier", type=float, default=None, help="Переопределить STT_NOISE_RMS_MULTIPLIER.")
    parser.add_argument("--stt-noise-alpha", type=float, default=None, help="Переопределить STT_NOISE_RMS_ALPHA.")
    parser.add_argument("--stt-pre-roll-blocks", type=int, default=None, help="Переопределить STT_PRE_ROLL_BLOCKS.")
    parser.add_argument("--stt-start-trigger-blocks", type=int, default=None, help="Переопределить STT_START_TRIGGER_BLOCKS.")
    parser.add_argument("--blocksize", type=int, default=None, help="Переопределить BLOCKSIZE для mic/listener/synthetic.")
    parser.add_argument("--queue-max-blocks", type=int, default=None, help="Переопределить размер очереди listener.")

    parser.add_argument("--synthetic-audio", choices=("silence", "noise"), default="silence", help="Тип искусственного аудио для Vosk.")
    parser.add_argument("--synthetic-realtime", action="store_true", default=True, help="Кормить Vosk примерно в реальном времени.")
    parser.add_argument("--synthetic-fast", dest="synthetic_realtime", action="store_false", help="Кормить Vosk быстрее реального времени.")
    parser.add_argument("--synthetic-burst", type=int, default=50, help="Сколько блоков за тик в --synthetic-fast.")
    parser.add_argument("--noise-level", type=int, default=400, help="Амплитуда шума для --synthetic-audio noise.")
    parser.add_argument("--seed", type=int, default=42, help="Seed для синтетического шума.")
    parser.add_argument("--recognizer-reset-interval", type=float, default=0.0, help="Пересоздавать recognizer каждые N секунд в synthetic-vosk.")

    parser.add_argument("--tts-synth-interval", type=float, default=0.0, help="Как часто делать TTS-синтез в tts-helper.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    tracemalloc.start(25)

    print("=== Диагностика роста памяти JARVIS ===")
    print(f"Python: {sys.executable}")
    print(f"PID: {os.getpid()}")
    print(f"Рабочая папка: {os.getcwd()}")
    print(f"Сценарий: {args.scenario}")
    print(f"Длительность: {args.seconds} сек, интервал: {args.interval} сек")

    profiler = GrowthProfiler(args)
    scenario = SCENARIOS[args.scenario]
    try:
        scenario(args, profiler)
    finally:
        profiler.finish(args.scenario)


if __name__ == "__main__":
    main()
