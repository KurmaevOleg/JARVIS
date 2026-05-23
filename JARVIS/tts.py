import atexit
import json
import os
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

from config import (
    TTS_MAX_CHARS,
    TTS_POWERSHELL,
    TTS_REQUEST_TIMEOUT,
    TTS_STARTUP_TIMEOUT,
    TTS_VOICE_NAME,
)
from number_utils import replace_numbers_for_speech


is_speaking = threading.Event()
_speak_lock = threading.Lock()


_HELPER_SCRIPT = r"""
param([string]$VoiceName)
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName System
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.SpeechSynthesis.SpeechSynthesizer, Windows.Media.SpeechSynthesis, ContentType=WindowsRuntime]

function Write-Response($Object) {
    [Console]::Out.WriteLine(($Object | ConvertTo-Json -Compress -Depth 6))
    [Console]::Out.Flush()
}

try {
    $voice = [Windows.Media.SpeechSynthesis.SpeechSynthesizer]::AllVoices |
        Where-Object { $_.DisplayName -eq $VoiceName -or $_.Id -like "*Pavel*" } |
        Select-Object -First 1
    if (-not $voice) {
        throw "Voice '$VoiceName' was not found in Windows OneCore TTS."
    }

    $synth = [Windows.Media.SpeechSynthesis.SpeechSynthesizer]::new()
    $synth.Voice = $voice
    $asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() |
        Where-Object {
            $_.Name -eq 'AsTask' -and
            $_.GetParameters().Count -eq 1 -and
            $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
        } |
        Select-Object -First 1
    if (-not $asTask) {
        throw 'System.WindowsRuntimeSystemExtensions.AsTask was not found.'
    }
    $speechStreamType = [Windows.Media.SpeechSynthesis.SpeechSynthesisStream]

    Write-Response @{
        status = 'ready'
        voice = $voice.DisplayName
        language = $voice.Language
        id = $voice.Id
    }
}
catch {
    Write-Response @{ status = 'error'; message = $_.Exception.Message }
    exit 1
}

function Save-Speech([string]$Text, [string]$OutputPath) {
    $parent = [System.IO.Path]::GetDirectoryName($OutputPath)
    if ($parent -and -not [System.IO.Directory]::Exists($parent)) {
        [System.IO.Directory]::CreateDirectory($parent) | Out-Null
    }

    $op = $synth.SynthesizeTextToStreamAsync($Text)
    $task = $asTask.MakeGenericMethod($speechStreamType).Invoke($null, @($op))
    $stream = $task.GetAwaiter().GetResult()
    $netStream = [System.IO.WindowsRuntimeStreamExtensions]::AsStreamForRead($stream)
    $file = [System.IO.File]::Create($OutputPath)
    try {
        $netStream.CopyTo($file)
    }
    finally {
        if ($file) { $file.Dispose() }
        if ($netStream) { $netStream.Dispose() }
        if ($stream) { $stream.Dispose() }
    }
}

while (($line = [Console]::In.ReadLine()) -ne $null) {
    if ([string]::IsNullOrWhiteSpace($line)) {
        continue
    }

    try {
        $request = $line | ConvertFrom-Json
        $action = [string]$request.action

        if ($action -eq 'shutdown') {
            Write-Response @{ status = 'ok' }
            break
        }

        $text = [string]$request.text
        if ([string]::IsNullOrWhiteSpace($text)) {
            Write-Response @{ status = 'ok'; skipped = $true }
            continue
        }

        $outputPath = [string]$request.output_path
        $removeAfterPlay = $false
        if ([string]::IsNullOrWhiteSpace($outputPath)) {
            $outputPath = [System.IO.Path]::Combine([System.IO.Path]::GetTempPath(), [System.Guid]::NewGuid().ToString() + '.wav')
            $removeAfterPlay = $true
        }

        Save-Speech $text $outputPath

        if ($action -eq 'speak') {
            $player = [System.Media.SoundPlayer]::new($outputPath)
            try {
                $player.Load()
                $player.PlaySync()
            }
            finally {
                if ($player) { $player.Dispose() }
                if ($removeAfterPlay) {
                    Remove-Item -LiteralPath $outputPath -Force -ErrorAction SilentlyContinue
                }
            }
        }

        Write-Response @{ status = 'ok'; output_path = $outputPath }
    }
    catch {
        Write-Response @{ status = 'error'; message = $_.Exception.Message }
    }
}

if ($synth) {
    $synth.Dispose()
}
"""


class OneCoreTTS:
    def __init__(self, voice_name: str = TTS_VOICE_NAME, powershell: str = TTS_POWERSHELL):
        if os.name != "nt":
            raise RuntimeError("Microsoft Pavel доступен только через Windows OneCore TTS.")

        self.voice_name = voice_name
        self.powershell = self._resolve_powershell(powershell)
        self._lock = threading.RLock()
        self._responses: queue.Queue[str] = queue.Queue()
        self._stderr_tail: deque[str] = deque(maxlen=30)
        self._helper_path: str | None = None
        self._process: subprocess.Popen[str] | None = None
        self._closed = False
        self.voice_info = self._start_helper()
        atexit.register(self.close)

    @staticmethod
    def _resolve_powershell(powershell: str) -> str:
        path = Path(powershell)
        if path.is_file():
            return str(path)

        found = shutil.which(powershell)
        if found:
            return found

        for name in ("powershell.exe", "powershell", "pwsh.exe", "pwsh"):
            found = shutil.which(name)
            if found:
                return found

        raise RuntimeError("PowerShell не найден. Он нужен для Windows OneCore TTS.")

    def _write_helper_script(self) -> str:
        with tempfile.NamedTemporaryFile("w", suffix=".ps1", delete=False, encoding="utf-8-sig") as tmp:
            tmp.write(_HELPER_SCRIPT)
            return tmp.name

    def _start_helper(self) -> dict[str, Any]:
        self._cleanup_helper_script()
        self._helper_path = self._write_helper_script()
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self._responses = queue.Queue()
        self._stderr_tail.clear()
        self._process = subprocess.Popen(
            [
                self.powershell,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                self._helper_path,
                "-VoiceName",
                self.voice_name,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creationflags,
        )
        threading.Thread(target=self._stdout_reader, daemon=True).start()
        threading.Thread(target=self._stderr_reader, daemon=True).start()

        ready = self._read_response(TTS_STARTUP_TIMEOUT)
        if ready.get("status") != "ready":
            self.close()
            raise RuntimeError(ready.get("message") or "TTS helper не готов.")
        return ready

    def _stdout_reader(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        for line in process.stdout:
            line = line.strip()
            if line:
                self._responses.put(line)

    def _stderr_reader(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        for line in process.stderr:
            line = line.strip()
            if line:
                self._stderr_tail.append(line)

    def _stderr_text(self) -> str:
        return " ".join(self._stderr_tail)

    def _read_response(self, timeout: float) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                process = self._process
                if process is not None and process.poll() is not None:
                    raise RuntimeError(f"TTS helper завершился с кодом {process.returncode}. {self._stderr_text()}")
                raise TimeoutError(f"TTS helper не ответил за {timeout:.1f} сек. {self._stderr_text()}")

            try:
                line = self._responses.get(timeout=min(remaining, 0.2))
            except queue.Empty:
                continue

            try:
                return json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"TTS helper вернул некорректный JSON: {line}") from exc

    def _ensure_running(self) -> None:
        if self._closed:
            raise RuntimeError("TTS helper уже остановлен.")
        if self._process is None or self._process.poll() is not None:
            self.voice_info = self._start_helper()

    def _send_request(self, payload: dict[str, Any], timeout: float = TTS_REQUEST_TIMEOUT) -> dict[str, Any]:
        with self._lock:
            self._ensure_running()
            process = self._process
            if process is None or process.stdin is None:
                raise RuntimeError("TTS helper stdin недоступен.")

            process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            process.stdin.flush()
            response = self._read_response(timeout)
            if response.get("status") != "ok":
                raise RuntimeError(response.get("message") or "Ошибка TTS helper.")
            return response

    def _cleanup_helper_script(self) -> None:
        if not self._helper_path:
            return
        try:
            os.unlink(self._helper_path)
        except OSError:
            pass
        self._helper_path = None

    def synthesize_to_file(self, text: str, output_path: str | os.PathLike[str]) -> None:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        self._send_request({"action": "synthesize", "text": text, "output_path": str(output)})

    def speak_text(self, text: str) -> None:
        self._send_request({"action": "speak", "text": text})

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            process = self._process
            if process is not None and process.poll() is None:
                try:
                    if process.stdin is not None:
                        process.stdin.write(json.dumps({"action": "shutdown"}) + "\n")
                        process.stdin.flush()
                        self._read_response(2.0)
                except Exception:
                    pass
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=2.0)
                    except subprocess.TimeoutExpired:
                        process.kill()
            self._cleanup_helper_script()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


def initialize_tts() -> OneCoreTTS:
    return OneCoreTTS()


def _normalize_for_tts(text: str) -> str:
    text = text.replace("\n", " ")
    text = text.replace("\r", " ")
    text = re.sub(r"\s+", " ", text)
    text = replace_numbers_for_speech(text)
    text = re.sub(r"[^\wа-яА-Яa-zA-Z0-9 .,!?—-]", "", text)
    return text[:TTS_MAX_CHARS].strip()


def synthesize_tts(engine: OneCoreTTS, text: str, output_path: str | os.PathLike[str] | None = None) -> Path:
    safe = _normalize_for_tts(text)
    if not safe:
        raise ValueError("Нет текста для озвучки.")

    if output_path is None:
        handle = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        output = Path(handle.name)
        handle.close()
    else:
        output = Path(output_path)

    engine.synthesize_to_file(safe, output)
    return output


def speak(engine: OneCoreTTS, _silence, text: str) -> None:
    print(f"Ассистент: {text}")
    safe = _normalize_for_tts(text)
    if not safe:
        return

    with _speak_lock:
        is_speaking.set()
        try:
            engine.speak_text(safe)
        finally:
            is_speaking.clear()
