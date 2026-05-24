#!/usr/bin/env python3
"""
Тест локальных движков озвучки с замером памяти.

Примеры:
    python JARVIS/test_tts_local.py
    python JARVIS/test_tts_local.py --quick
    python JARVIS/test_tts_local.py --engines sapi-powershell,piper,silero
    python JARVIS/test_tts_local.py --voice-dir C:\voices\piper
"""

from __future__ import annotations

import argparse
import ctypes
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import psutil
except ImportError:
    psutil = None


SCRIPT_PATH = Path(__file__).resolve()
BASE_DIR = SCRIPT_PATH.parent
PROJECT_DIR = BASE_DIR.parent
OUTPUT_DIR = BASE_DIR / "tts_test_outputs"
MARKER = "JARVIS_TTS_RESULT_JSON="
MB = 1024 * 1024
DEFAULT_TEXT = (
    "Привет, я Джарвис. Проверяю локальную озвучку, скорость ответа "
    "и потребление оперативной памяти."
)
DEFAULT_SILERO_SPEAKERS = ("aidar", "baya", "kseniya", "xenia", "eugene")
DEFAULT_ENGINES = (
    "sapi-powershell",
    "pyttsx3",
    "win32com",
    "piper",
    "espeak-ng",
    "rhvoice-test",
    "silero",
)


@dataclass
class Candidate:
    engine: str
    label: str
    voice_id: str = ""
    voice_name: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


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


def memory_mb() -> float:
    if psutil is not None:
        return psutil.Process(os.getpid()).memory_info().rss / MB
    working_set, _ = windows_memory_info()
    return working_set / MB


def process_tree_rss_mb(pid: int) -> float:
    if psutil is None:
        return 0.0

    try:
        process = psutil.Process(pid)
        total = process.memory_info().rss
        for child in process.children(recursive=True):
            try:
                total += child.memory_info().rss
            except psutil.Error:
                pass
        return total / MB
    except psutil.Error:
        return 0.0


def safe_filename(text: str, limit: int = 90) -> str:
    text = re.sub(r'[<>:"/\\|?*]+', "_", text)
    text = re.sub(r"\s+", "_", text.strip())
    text = re.sub(r"_+", "_", text)
    return (text[:limit].strip("._ ") or "voice")


def shorten(text: str, limit: int) -> str:
    text = str(text or "")
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"


def emit_json(payload: dict[str, Any]) -> None:
    print(MARKER + json.dumps(payload, ensure_ascii=False))


def parse_marker_output(stdout: str) -> dict[str, Any]:
    for line in reversed(stdout.splitlines()):
        if line.startswith(MARKER):
            return json.loads(line[len(MARKER):])
    raise RuntimeError("Дочерний процесс не вернул JSON-результат.")


def run_child_json(args: list[str], timeout: int) -> dict[str, Any]:
    cmd = [sys.executable, str(SCRIPT_PATH), *args]
    completed = subprocess.run(
        cmd,
        cwd=str(PROJECT_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    try:
        result = parse_marker_output(completed.stdout)
    except Exception as exc:
        result = {
            "status": f"error: {exc}",
            "stdout_tail": completed.stdout[-600:],
            "stderr_tail": completed.stderr[-600:],
        }
    result.setdefault("returncode", completed.returncode)
    if completed.stderr and "stderr_tail" not in result:
        result["stderr_tail"] = completed.stderr[-600:]
    return result


def run_external_with_peak(
    cmd: list[str],
    timeout: int,
    stdin_text: str | None = None,
) -> tuple[int, float, str, str]:
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE if stdin_text is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=creationflags,
    )
    if stdin_text is not None and process.stdin is not None:
        process.stdin.write(stdin_text.encode("utf-8"))
        process.stdin.close()

    started = time.monotonic()
    peak_mb = process_tree_rss_mb(process.pid)
    while process.poll() is None:
        peak_mb = max(peak_mb, process_tree_rss_mb(process.pid))
        if time.monotonic() - started > timeout:
            process.kill()
            return -1, peak_mb, "", f"timeout after {timeout}s"
        time.sleep(0.05)

    stdout = process.stdout.read().decode("utf-8", errors="replace") if process.stdout else ""
    stderr = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
    peak_mb = max(peak_mb, process_tree_rss_mb(process.pid))
    return process.returncode, peak_mb, stdout, stderr


def write_wav(path: Path, audio: Any, sample_rate: int) -> None:
    import numpy as np

    if hasattr(audio, "detach"):
        audio = audio.detach().cpu().numpy()
    data = np.asarray(audio, dtype=np.float32).reshape(-1)
    data = np.clip(data, -1.0, 1.0)
    pcm = (data * 32767).astype(np.int16)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm.tobytes())


def child_result_base(args: argparse.Namespace) -> dict[str, Any]:
    start = memory_mb()
    return {
        "engine": args._engine,
        "label": args._label,
        "voice_id": args._voice_id,
        "voice_name": args._voice_name,
        "output": args._output,
        "status": "ok",
        "rss_start_mb": start,
        "rss_after_import_mb": start,
        "rss_after_init_mb": start,
        "rss_after_synth_mb": start,
        "peak_mb": start,
        "external_peak_mb": 0.0,
        "seconds": 0.0,
        "output_exists": False,
    }


def mark(result: dict[str, Any], key: str) -> None:
    current = memory_mb()
    result[key] = current
    result["peak_mb"] = max(float(result.get("peak_mb", 0.0)), current)


def run_child_silero(args: argparse.Namespace, result: dict[str, Any], extra: dict[str, Any]) -> None:
    sys.path.insert(0, str(BASE_DIR))
    mark(result, "rss_before_import_mb")
    import torch
    import numpy as np
    import sounddevice  # noqa: F401

    from config import DEVICE, SR_TTS, TORCH_NUM_INTEROP_THREADS, TORCH_NUM_THREADS

    mark(result, "rss_after_import_mb")
    torch.set_grad_enabled(False)
    torch.set_num_threads(TORCH_NUM_THREADS)
    try:
        torch.set_num_interop_threads(TORCH_NUM_INTEROP_THREADS)
    except RuntimeError:
        pass

    model_speaker = extra.get("model_speaker", "v4_ru")
    voice = args._voice_id or extra.get("voice", "aidar")
    model, _ = torch.hub.load(
        repo_or_dir="snakers4/silero-models",
        model="silero_tts",
        language="ru",
        speaker=model_speaker,
        trust_repo=True,
    )
    model.to(torch.device(DEVICE))
    mark(result, "rss_after_init_mb")

    with torch.inference_mode():
        audio = model.apply_tts(
            text=args.text,
            speaker=voice,
            sample_rate=SR_TTS,
            put_accent=True,
            put_yo=True,
        )
    _ = np.asarray(audio, dtype=np.float32)
    write_wav(Path(args._output), audio, SR_TTS)
    mark(result, "rss_after_synth_mb")


def run_child_pyttsx3(args: argparse.Namespace, result: dict[str, Any]) -> None:
    import pyttsx3

    mark(result, "rss_after_import_mb")
    engine = pyttsx3.init()
    if args._voice_id:
        engine.setProperty("voice", args._voice_id)
    mark(result, "rss_after_init_mb")
    engine.save_to_file(args.text, args._output)
    engine.runAndWait()
    engine.stop()
    mark(result, "rss_after_synth_mb")


def run_child_win32com(args: argparse.Namespace, result: dict[str, Any]) -> None:
    import win32com.client

    mark(result, "rss_after_import_mb")
    voice = win32com.client.Dispatch("SAPI.SpVoice")
    if args._voice_id or args._voice_name:
        target = args._voice_id or args._voice_name
        for token in voice.GetVoices():
            if target == token.Id or target in token.GetDescription():
                voice.Voice = token
                break
    stream = win32com.client.Dispatch("SAPI.SpFileStream")
    mark(result, "rss_after_init_mb")
    stream.Open(args._output, 3, False)
    voice.AudioOutputStream = stream
    voice.Speak(args.text)
    stream.Close()
    mark(result, "rss_after_synth_mb")


def run_child_sapi_powershell(args: argparse.Namespace, result: dict[str, Any], extra: dict[str, Any]) -> None:
    powershell = extra["powershell"]
    script = """
param([string]$VoiceName, [string]$OutputPath, [string]$Text)
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
if ($VoiceName) { $s.SelectVoice($VoiceName) }
$s.SetOutputToWaveFile($OutputPath)
$s.Speak($Text) | Out-Null
$s.Dispose()
"""
    with tempfile.NamedTemporaryFile("w", suffix=".ps1", delete=False, encoding="utf-8") as tmp:
        tmp.write(script)
        script_path = tmp.name
    try:
        command = [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            script_path,
            "-VoiceName",
            args._voice_name,
            "-OutputPath",
            args._output,
            "-Text",
            args.text,
        ]
        mark(result, "rss_after_import_mb")
        mark(result, "rss_after_init_mb")
        returncode, peak_mb, stdout, stderr = run_external_with_peak(command, args.timeout)
        result["external_peak_mb"] = peak_mb
        result["peak_mb"] = max(result["peak_mb"], peak_mb)
        result["stdout_tail"] = stdout[-300:]
        result["stderr_tail"] = stderr[-300:]
        if returncode != 0:
            raise RuntimeError(f"PowerShell вернул код {returncode}: {stderr[-300:]}")
        mark(result, "rss_after_synth_mb")
    finally:
        try:
            os.unlink(script_path)
        except OSError:
            pass


def run_child_piper(args: argparse.Namespace, result: dict[str, Any], extra: dict[str, Any]) -> None:
    command = [
        extra["piper_bin"],
        "--model",
        extra["model_path"],
        "--output_file",
        args._output,
    ]
    mark(result, "rss_after_import_mb")
    mark(result, "rss_after_init_mb")
    returncode, peak_mb, stdout, stderr = run_external_with_peak(command, args.timeout, stdin_text=args.text)
    result["external_peak_mb"] = peak_mb
    result["peak_mb"] = max(result["peak_mb"], peak_mb)
    result["stdout_tail"] = stdout[-300:]
    result["stderr_tail"] = stderr[-300:]
    if returncode != 0:
        raise RuntimeError(f"Piper вернул код {returncode}: {stderr[-300:]}")
    mark(result, "rss_after_synth_mb")


def run_child_espeak(args: argparse.Namespace, result: dict[str, Any], extra: dict[str, Any]) -> None:
    command = [extra["espeak_bin"], "-v", extra.get("voice", "ru"), "-w", args._output, args.text]
    mark(result, "rss_after_import_mb")
    mark(result, "rss_after_init_mb")
    returncode, peak_mb, stdout, stderr = run_external_with_peak(command, args.timeout)
    result["external_peak_mb"] = peak_mb
    result["peak_mb"] = max(result["peak_mb"], peak_mb)
    result["stdout_tail"] = stdout[-300:]
    result["stderr_tail"] = stderr[-300:]
    if returncode != 0:
        raise RuntimeError(f"eSpeak NG вернул код {returncode}: {stderr[-300:]}")
    mark(result, "rss_after_synth_mb")


def run_child_rhvoice(args: argparse.Namespace, result: dict[str, Any], extra: dict[str, Any]) -> None:
    command = [extra["rhvoice_bin"], "-o", args._output, args.text]
    mark(result, "rss_after_import_mb")
    mark(result, "rss_after_init_mb")
    returncode, peak_mb, stdout, stderr = run_external_with_peak(command, args.timeout)
    result["external_peak_mb"] = peak_mb
    result["peak_mb"] = max(result["peak_mb"], peak_mb)
    result["stdout_tail"] = stdout[-300:]
    result["stderr_tail"] = stderr[-300:]
    if returncode != 0:
        raise RuntimeError(f"RHVoice-test вернул код {returncode}: {stderr[-300:]}")
    mark(result, "rss_after_synth_mb")


def child_run(args: argparse.Namespace) -> None:
    result = child_result_base(args)
    started = time.perf_counter()
    extra = json.loads(args._extra_json or "{}")
    try:
        Path(args._output).parent.mkdir(parents=True, exist_ok=True)
        if args._engine == "silero":
            run_child_silero(args, result, extra)
        elif args._engine == "pyttsx3":
            run_child_pyttsx3(args, result)
        elif args._engine == "win32com":
            run_child_win32com(args, result)
        elif args._engine == "sapi-powershell":
            run_child_sapi_powershell(args, result, extra)
        elif args._engine == "piper":
            run_child_piper(args, result, extra)
        elif args._engine == "espeak-ng":
            run_child_espeak(args, result, extra)
        elif args._engine == "rhvoice-test":
            run_child_rhvoice(args, result, extra)
        else:
            raise RuntimeError(f"Неизвестный движок: {args._engine}")
    except Exception as exc:
        result["status"] = f"error: {exc}"
        result["traceback"] = traceback.format_exc()[-1200:]
    finally:
        result["seconds"] = time.perf_counter() - started
        result["output_exists"] = Path(args._output).exists()
        emit_json(result)


def list_pyttsx3_voices() -> None:
    try:
        import pyttsx3

        engine = pyttsx3.init()
        voices = []
        for voice in engine.getProperty("voices") or []:
            voices.append(
                {
                    "id": getattr(voice, "id", ""),
                    "name": getattr(voice, "name", ""),
                    "languages": [str(item) for item in getattr(voice, "languages", []) or []],
                }
            )
        engine.stop()
        emit_json({"status": "ok", "voices": voices})
    except Exception as exc:
        emit_json({"status": f"error: {exc}", "voices": []})


def list_win32com_voices() -> None:
    try:
        import win32com.client

        voice = win32com.client.Dispatch("SAPI.SpVoice")
        voices = []
        for token in voice.GetVoices():
            voices.append({"id": token.Id, "name": token.GetDescription()})
        emit_json({"status": "ok", "voices": voices})
    except Exception as exc:
        emit_json({"status": f"error: {exc}", "voices": []})


def list_sapi_powershell_voices(powershell: str, timeout: int) -> tuple[list[dict[str, Any]], str | None]:
    command = """
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.GetInstalledVoices() | ForEach-Object {
    [PSCustomObject]@{
        Name = $_.VoiceInfo.Name
        Culture = $_.VoiceInfo.Culture.Name
        Gender = $_.VoiceInfo.Gender.ToString()
        Age = $_.VoiceInfo.Age.ToString()
        Description = $_.VoiceInfo.Description
    }
} | ConvertTo-Json -Compress
"""
    try:
        completed = subprocess.run(
            [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        if completed.returncode != 0:
            return [], completed.stderr.strip() or f"код {completed.returncode}"
        raw = completed.stdout.strip()
        if not raw:
            return [], "SAPI не вернул список голосов"
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            parsed = [parsed]
        return parsed, None
    except Exception as exc:
        return [], str(exc)


def list_python_voices(kind: str, timeout: int) -> tuple[list[dict[str, Any]], str | None]:
    result = run_child_json([f"--_list-{kind}"], timeout)
    if str(result.get("status", "")).startswith("ok"):
        return result.get("voices", []), None
    return [], result.get("status", "unknown error")


def find_executable(explicit: str | None, names: tuple[str, ...]) -> str | None:
    if explicit:
        path = Path(explicit)
        if path.is_file():
            return str(path)
        found = shutil.which(explicit)
        if found:
            return found
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return None


def default_voice_dirs() -> list[Path]:
    home = Path.home()
    dirs = [
        BASE_DIR / "voices",
        PROJECT_DIR / "voices",
        PROJECT_DIR / "models",
        home / "Documents" / "piper",
        home / "Downloads",
        home / "AppData" / "Local" / "piper",
        home / ".local" / "share" / "piper",
    ]
    return [path for path in dirs if path.exists()]


def find_piper_voices(extra_dirs: list[str], max_voices: int) -> list[Path]:
    dirs = [Path(item) for item in extra_dirs if item]
    dirs.extend(default_voice_dirs())
    seen: set[Path] = set()
    voices: list[Path] = []
    for folder in dirs:
        if not folder.exists():
            continue
        try:
            matches = folder.rglob("*.onnx") if folder.is_dir() else [folder]
            for path in matches:
                path = path.resolve()
                if path in seen:
                    continue
                seen.add(path)
                voices.append(path)
                if len(voices) >= max_voices:
                    return voices
        except OSError:
            continue
    return voices


def selected_engines(args: argparse.Namespace) -> set[str]:
    if args.engines.strip().lower() == "all":
        return set(DEFAULT_ENGINES)
    return {item.strip().lower() for item in args.engines.split(",") if item.strip()}


def build_candidates(args: argparse.Namespace) -> tuple[list[Candidate], list[str]]:
    engines = selected_engines(args)
    skipped: list[str] = []
    candidates: list[Candidate] = []
    max_voices = 1 if args.quick else args.max_voices

    if "sapi-powershell" in engines:
        powershell = find_executable(args.powershell_bin, ("powershell.exe", "powershell", "pwsh.exe", "pwsh"))
        if powershell:
            voices, error = list_sapi_powershell_voices(powershell, args.timeout)
            if voices:
                for voice in voices[:max_voices]:
                    name = voice.get("Name") or voice.get("Description") or "default"
                    culture = voice.get("Culture") or ""
                    label = f"SAPI PowerShell | {name} {culture}".strip()
                    candidates.append(
                        Candidate(
                            engine="sapi-powershell",
                            label=label,
                            voice_name=name,
                            extra={"powershell": powershell},
                        )
                    )
            else:
                skipped.append(f"sapi-powershell: {error or 'голоса не найдены'}")
        else:
            skipped.append("sapi-powershell: powershell/pwsh не найден")

    if "pyttsx3" in engines:
        if importlib.util.find_spec("pyttsx3") is None:
            skipped.append("pyttsx3: пакет не установлен")
        else:
            voices, error = list_python_voices("pyttsx3", args.timeout)
            if voices:
                for voice in voices[:max_voices]:
                    name = voice.get("name") or voice.get("id") or "default"
                    candidates.append(
                        Candidate(
                            engine="pyttsx3",
                            label=f"pyttsx3 | {name}",
                            voice_id=voice.get("id", ""),
                            voice_name=name,
                        )
                    )
            else:
                skipped.append(f"pyttsx3: {error or 'голоса не найдены'}")

    if "win32com" in engines:
        if importlib.util.find_spec("win32com") is None:
            skipped.append("win32com: pywin32 не установлен")
        else:
            voices, error = list_python_voices("win32com", args.timeout)
            if voices:
                for voice in voices[:max_voices]:
                    name = voice.get("name") or voice.get("id") or "default"
                    candidates.append(
                        Candidate(
                            engine="win32com",
                            label=f"win32com SAPI | {name}",
                            voice_id=voice.get("id", ""),
                            voice_name=name,
                        )
                    )
            else:
                skipped.append(f"win32com: {error or 'голоса не найдены'}")

    if "piper" in engines:
        piper = find_executable(args.piper_bin, ("piper.exe", "piper"))
        voices = find_piper_voices(args.voice_dir, max_voices)
        if not piper:
            skipped.append("piper: piper.exe не найден в PATH или --piper-bin")
        elif not voices:
            skipped.append("piper: .onnx голоса не найдены, укажите --voice-dir")
        else:
            for voice_path in voices:
                candidates.append(
                    Candidate(
                        engine="piper",
                        label=f"Piper | {voice_path.stem}",
                        voice_id=str(voice_path),
                        voice_name=voice_path.stem,
                        extra={"piper_bin": piper, "model_path": str(voice_path)},
                    )
                )

    if "espeak-ng" in engines:
        espeak = find_executable(args.espeak_bin, ("espeak-ng.exe", "espeak-ng", "espeak.exe", "espeak"))
        if espeak:
            candidates.append(
                Candidate(
                    engine="espeak-ng",
                    label="eSpeak NG | ru",
                    voice_id="ru",
                    voice_name="ru",
                    extra={"espeak_bin": espeak, "voice": "ru"},
                )
            )
        else:
            skipped.append("espeak-ng: executable не найден")

    if "rhvoice-test" in engines:
        rhvoice = find_executable(args.rhvoice_bin, ("RHVoice-test.exe", "RHVoice-test", "rhvoice-test"))
        if rhvoice:
            candidates.append(
                Candidate(
                    engine="rhvoice-test",
                    label="RHVoice-test | default",
                    extra={"rhvoice_bin": rhvoice},
                )
            )
        else:
            skipped.append("rhvoice-test: executable не найден")

    if "silero" in engines:
        speakers = [item.strip() for item in args.silero_speakers.split(",") if item.strip()]
        if args.quick:
            speakers = speakers[:1]
        for speaker in speakers:
            candidates.append(
                Candidate(
                    engine="silero",
                    label=f"Silero torch | {speaker}",
                    voice_id=speaker,
                    voice_name=speaker,
                    extra={"voice": speaker, "model_speaker": args.silero_model_speaker},
                )
            )

    return candidates, skipped


def output_for_candidate(candidate: Candidate, output_dir: Path, index: int) -> Path:
    suffix = "wav"
    name = safe_filename(f"{index:02d}_{candidate.engine}_{candidate.voice_name or candidate.voice_id or candidate.label}")
    return output_dir / f"{name}.{suffix}"


def run_candidate(candidate: Candidate, output_path: Path, args: argparse.Namespace) -> dict[str, Any]:
    child_args = [
        "--_child-run",
        "--_engine",
        candidate.engine,
        "--_label",
        candidate.label,
        "--_voice-id",
        candidate.voice_id,
        "--_voice-name",
        candidate.voice_name,
        "--_output",
        str(output_path),
        "--_extra-json",
        json.dumps(candidate.extra, ensure_ascii=False),
        "--text",
        args.text,
        "--timeout",
        str(args.timeout),
    ]
    if args.play:
        child_args.append("--play")
    return run_child_json(child_args, args.timeout + 20)


def print_table(results: list[dict[str, Any]]) -> None:
    print()
    print(
        f"{'#':>2} {'Движок/голос':<42} {'Статус':<18} "
        f"{'Импорт':>8} {'Иниц.':>8} {'Синтез':>8} {'Пик':>8} {'Время':>7}  Файл"
    )
    print("-" * 126)
    for index, item in enumerate(results, 1):
        start = float(item.get("rss_start_mb", 0.0))
        after_import = float(item.get("rss_after_import_mb", start))
        after_init = float(item.get("rss_after_init_mb", after_import))
        after_synth = float(item.get("rss_after_synth_mb", after_init))
        peak = max(float(item.get("peak_mb", after_synth)), float(item.get("external_peak_mb", 0.0)))
        import_delta = after_import - start
        init_delta = after_init - after_import
        synth_delta = after_synth - after_init
        status = item.get("status", "")
        output = item.get("output", "")
        if not item.get("output_exists"):
            output = ""
        print(
            f"{index:>2} "
            f"{shorten(item.get('label', item.get('engine', '')), 42):<42} "
            f"{shorten(status, 18):<18} "
            f"{import_delta:>8.1f} "
            f"{init_delta:>8.1f} "
            f"{synth_delta:>8.1f} "
            f"{peak:>8.1f} "
            f"{float(item.get('seconds', 0.0)):>7.2f}  "
            f"{shorten(output, 36)}"
        )


def print_details(results: list[dict[str, Any]]) -> None:
    failed = [item for item in results if not str(item.get("status", "")).startswith("ok")]
    if not failed:
        return
    print()
    print("Ошибки:")
    for item in failed:
        print(f"- {item.get('label', item.get('engine'))}: {item.get('status')}")
        tail = item.get("stderr_tail") or item.get("stdout_tail") or ""
        if tail:
            print(f"  {shorten(tail.replace(chr(10), ' '), 220)}")


def run_parent(args: argparse.Namespace) -> None:
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    candidates, skipped = build_candidates(args)
    print("=== Тест локальных озвучек JARVIS ===")
    print(f"Python: {sys.executable}")
    print(f"Папка результатов: {output_dir}")
    print(f"Текст: {args.text}")

    if skipped:
        print()
        print("Пропущено:")
        for item in skipped:
            print(f"- {item}")

    if args.list_only:
        print()
        print("Найденные кандидаты:")
        for index, candidate in enumerate(candidates, 1):
            print(f"{index:>2}. {candidate.label}")
        return

    if not candidates:
        print()
        print("Не найдено ни одного доступного локального движка.")
        return

    results: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates, 1):
        output_path = output_for_candidate(candidate, output_dir, index)
        print(f"[{index}/{len(candidates)}] {candidate.label}")
        result = run_candidate(candidate, output_path, args)
        result.setdefault("engine", candidate.engine)
        result.setdefault("label", candidate.label)
        result.setdefault("output", str(output_path))
        results.append(result)

    report_path = output_dir / "tts_local_report.json"
    report_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    print_table(results)
    print_details(results)
    print()
    print(f"JSON-отчёт: {report_path}")
    print("WAV-файлы можно открыть из папки результатов и сравнить качество на слух.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Тест локальных TTS-движков и голосов с замером памяти.")
    parser.add_argument("--text", default=DEFAULT_TEXT, help="Текст для озвучки.")
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR), help="Папка для WAV-файлов и отчёта.")
    parser.add_argument("--engines", default="all", help="all или список через запятую: " + ",".join(DEFAULT_ENGINES))
    parser.add_argument("--max-voices", type=int, default=30, help="Максимум голосов на один движок.")
    parser.add_argument("--quick", action="store_true", help="Проверить только по одному голосу на движок.")
    parser.add_argument("--list-only", action="store_true", help="Только показать найденные варианты.")
    parser.add_argument("--play", action="store_true", help="Проигрывать WAV после синтеза в дочернем процессе.")
    parser.add_argument("--timeout", type=int, default=90, help="Таймаут на один голос/движок.")
    parser.add_argument("--voice-dir", action="append", default=[], help="Папка с Piper .onnx голосами.")
    parser.add_argument("--piper-bin", default="", help="Путь к piper.exe.")
    parser.add_argument("--espeak-bin", default="", help="Путь к espeak-ng.exe.")
    parser.add_argument("--rhvoice-bin", default="", help="Путь к RHVoice-test.exe.")
    parser.add_argument("--powershell-bin", default="", help="Путь к powershell.exe или pwsh.exe.")
    parser.add_argument("--silero-speakers", default=",".join(DEFAULT_SILERO_SPEAKERS), help="Голоса Silero через запятую.")
    parser.add_argument("--silero-model-speaker", default="v4_ru", help="Silero speaker pack, обычно v4_ru.")

    parser.add_argument("--_child-run", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--_list-pyttsx3", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--_list-win32com", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--_engine", default="", help=argparse.SUPPRESS)
    parser.add_argument("--_label", default="", help=argparse.SUPPRESS)
    parser.add_argument("--_voice-id", default="", help=argparse.SUPPRESS)
    parser.add_argument("--_voice-name", default="", help=argparse.SUPPRESS)
    parser.add_argument("--_output", default="", help=argparse.SUPPRESS)
    parser.add_argument("--_extra-json", default="{}", help=argparse.SUPPRESS)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args._list_pyttsx3:
        list_pyttsx3_voices()
        return
    if args._list_win32com:
        list_win32com_voices()
        return
    if args._child_run:
        child_run(args)
        return
    run_parent(args)


if __name__ == "__main__":
    main()