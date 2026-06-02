#assistant_worker
import gc
import threading
import time

from PyQt6.QtCore import QThread, pyqtSignal

import commands as commands_module
from config import (
    STT_IDLE_RESTART_SECONDS,
    STT_LISTEN_POLL_SECONDS,
    STT_RESTART_AFTER_RESPONSES,
)
from commands import process_command, register_file
from keyboard_layout import switch_to_english_layout
from stt import SpeechListener, initialize_stt
from tts import initialize_tts, speak as tts_speak
from timer_manager import TimerManager


WAKE_WORDS = ("джарвис", "джервис", "jarvis")
SLEEP_COMMANDS = ("отойди", "спи", "усни", "хватит")


def strip_wake_word(text: str) -> tuple[bool, str]:
    cmd = text.lower().strip()
    for wake_word in WAKE_WORDS:
        if wake_word in cmd:
            return True, cmd.replace(wake_word, "", 1).strip(" ,.!?")
    return False, cmd


class AssistantWorker(QThread):
    log = pyqtSignal(str)
    status = pyqtSignal(str)
    ready = pyqtSignal()
    finished_clean = pyqtSignal()
    add_file_requested = pyqtSignal()
    awake_changed = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stop_event = threading.Event()
        self._stt_model = None
        self._tts_engine = None
        self._timer_manager = None
        self._awake = threading.Event()
        self._add_file_event = threading.Event()
        self._add_file_result = None
        self._reply_count_since_stt_restart = 0
        self._stt_restart_requested = False
        self._stt_restart_reason = ""
        self._last_stt_activity = time.monotonic()

    def request_stop(self):
        self._stop_event.set()

    def wake_assistant(self):
        self._awake.set()
        self.awake_changed.emit(True)
        self.log.emit("Ассистент переведен в режим команды.")
        if self._tts_engine is not None:
            self._speak_proxy(self._tts_engine, None, "Слушаю.")
        self.status.emit("Слушаю команду")

    def sleep_assistant(self):
        self._awake.clear()
        self.awake_changed.emit(False)
        self.log.emit("Ассистент переведен в ожидание.")
        if self._tts_engine is not None:
            self._speak_proxy(self._tts_engine, None, "Хорошо, я замолкаю. Скажите Джарвис, когда будет нужно.")
        self.status.emit("Ожидаю Джарвис")

    def _speak_proxy(self, engine, _silence, text: str):
        self.log.emit(f"Ассистент: {text}")
        self.status.emit("Говорю")
        self._count_assistant_reply()
        tts_speak(engine, None, text)

    def _timer_speak_proxy(self, text: str):
        self._speak_proxy(self._tts_engine, None, text)

    def _count_assistant_reply(self):
        if STT_RESTART_AFTER_RESPONSES <= 0:
            return
        self._reply_count_since_stt_restart += 1
        if self._reply_count_since_stt_restart >= STT_RESTART_AFTER_RESPONSES:
            self._request_stt_restart(f"{STT_RESTART_AFTER_RESPONSES} ответа")

    def _request_stt_restart(self, reason: str):
        if self._stt_restart_requested:
            return
        self._stt_restart_requested = True
        self._stt_restart_reason = reason
        self.log.emit(f"STT будет перезапущен: {reason}.")

    def _reset_stt_restart_window(self):
        self._reply_count_since_stt_restart = 0
        self._stt_restart_requested = False
        self._stt_restart_reason = ""
        self._last_stt_activity = time.monotonic()

    def _idle_stt_restart_due(self) -> bool:
        if STT_IDLE_RESTART_SECONDS <= 0:
            return False
        return time.monotonic() - self._last_stt_activity >= STT_IDLE_RESTART_SECONDS

    def provide_add_file_result(self, result: dict | None):
        self._add_file_result = result
        self._add_file_event.set()

    def _handle_add_file(self) -> bool:
        self._add_file_result = None
        self._add_file_event.clear()
        self.status.emit("Ожидаю файл")
        self.log.emit("Ассистент: выберите файл и задайте ключевые слова в открывшемся окне.")
        self.add_file_requested.emit()

        while not self._stop_event.is_set():
            if self._add_file_event.wait(timeout=0.1):
                break

        if self._stop_event.is_set():
            return True

        result = self._add_file_result
        if not result:
            self._speak_proxy(self._tts_engine, None, "Добавление файла отменено.")
            return True

        added = register_file(result["file_path"], result["keywords"])
        if not added:
            self._speak_proxy(self._tts_engine, None, "Ключевые слова не указаны. Файл не добавлен.")
            return True

        self._speak_proxy(self._tts_engine, None, f"Файл добавлен. Ключи: {', '.join(added)}")
        return True

    def run(self):
        try:
            switch_to_english_layout()
            self.status.emit("Загрузка моделей")
            self.log.emit("Инициализация STT и TTS...")

            self._stt_model = initialize_stt()
            self._tts_engine = initialize_tts()

            # Подменяем speak внутри commands.py, чтобы все ответы шли через GUI-лог
            commands_module.speak = self._speak_proxy

            self._timer_manager = TimerManager(self._timer_speak_proxy)
            self._timer_manager.start()

            self.ready.emit()

            self._speak_proxy(self._tts_engine, None, "Ассистент готов. Скажите Джарвис, чтобы обратиться ко мне.")
            self.status.emit("Ожидаю Джарвис")
            self.awake_changed.emit(False)
            self._reset_stt_restart_window()

            keep_worker_running = True
            while keep_worker_running and not self._stop_event.is_set():
                restart_reason = ""
                self._reset_stt_restart_window()

                with SpeechListener(self._stt_model, stop_event=self._stop_event) as listener:
                    while not self._stop_event.is_set():
                        if self._stt_restart_requested:
                            restart_reason = self._stt_restart_reason or "плановый перезапуск"
                            break

                        text = listener.listen_once(timeout_seconds=STT_LISTEN_POLL_SECONDS)

                        if self._stop_event.is_set():
                            break

                        if not text:
                            if self._idle_stt_restart_due():
                                self._request_stt_restart(f"тишина {int(STT_IDLE_RESTART_SECONDS)} сек")
                                restart_reason = self._stt_restart_reason
                                break
                            continue

                        self._last_stt_activity = time.monotonic()
                        has_wake_word, command_text = strip_wake_word(text)

                        if not has_wake_word and not self._awake.is_set():
                            self.status.emit("Ожидаю Джарвис")
                            continue

                        self.log.emit(f"Вы: {text if has_wake_word else command_text}")

                        if has_wake_word:
                            self._awake.set()
                            self.awake_changed.emit(True)
                            if not command_text:
                                self._speak_proxy(self._tts_engine, None, "Слушаю.")
                                self.status.emit("Слушаю команду")
                                if self._stt_restart_requested:
                                    restart_reason = self._stt_restart_reason
                                    break
                                continue

                        if any(k in command_text for k in SLEEP_COMMANDS):
                            self._awake.clear()
                            self.awake_changed.emit(False)

                        self.status.emit("Обрабатываю")

                        if "добавить файл" in command_text:
                            self._handle_add_file()
                            if self._stt_restart_requested:
                                restart_reason = self._stt_restart_reason
                                break
                            if not self._stop_event.is_set():
                                self.status.emit("Слушаю команду" if self._awake.is_set() else "Ожидаю Джарвис")
                            continue

                        keep_running = process_command(
                            command_text,
                            self._tts_engine,
                            None,
                            self._timer_manager
                        )

                        if keep_running is False:
                            keep_worker_running = False
                            break

                        if self._stt_restart_requested:
                            restart_reason = self._stt_restart_reason
                            break

                        if not self._stop_event.is_set():
                            self.status.emit("Слушаю команду" if self._awake.is_set() else "Ожидаю Джарвис")

                del listener
                gc.collect()

                if restart_reason and keep_worker_running and not self._stop_event.is_set():
                    self.log.emit(f"STT перезапущен: {restart_reason}.")
                    self.status.emit("Слушаю команду" if self._awake.is_set() else "Ожидаю Джарвис")
                    continue

                break

        except Exception as e:
            self.log.emit(f"Ошибка: {e}")
            self.status.emit("Ошибка")
        finally:
            try:
                if self._timer_manager:
                    self._timer_manager.stop()
            except Exception:
                pass
            try:
                if self._tts_engine:
                    self._tts_engine.close()
            except Exception:
                pass

            self.status.emit("Остановлен")
            self.finished_clean.emit()
