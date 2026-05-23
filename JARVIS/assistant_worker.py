#assistant_worker
import threading

from PyQt6.QtCore import QThread, pyqtSignal

import commands as commands_module
from commands import process_command, register_file
from keyboard_layout import switch_to_english_layout
from stt import SpeechListener, initialize_stt
from tts import initialize_tts, warmup_tts, speak as tts_speak
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
        self._tts_model = None
        self._silence = None
        self._timer_manager = None
        self._awake = threading.Event()
        self._add_file_event = threading.Event()
        self._add_file_result = None

    def request_stop(self):
        self._stop_event.set()

    def wake_assistant(self):
        self._awake.set()
        self.awake_changed.emit(True)
        self.log.emit("Ассистент переведен в режим команды.")
        if self._tts_model is not None and self._silence is not None:
            self._speak_proxy(self._tts_model, self._silence, "Слушаю.")
        self.status.emit("Слушаю команду")

    def sleep_assistant(self):
        self._awake.clear()
        self.awake_changed.emit(False)
        self.log.emit("Ассистент переведен в ожидание.")
        if self._tts_model is not None and self._silence is not None:
            self._speak_proxy(self._tts_model, self._silence, "Хорошо, я замолкаю. Скажите Джарвис, когда будет нужно.")
        self.status.emit("Ожидаю Джарвис")

    def _speak_proxy(self, model, silence, text: str):
        self.log.emit(f"Ассистент: {text}")
        self.status.emit("Говорю")
        tts_speak(self._tts_model, self._silence, text)

    def _timer_speak_proxy(self, text: str):
        self._speak_proxy(self._tts_model, self._silence, text)

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
            self._speak_proxy(self._tts_model, self._silence, "Добавление файла отменено.")
            return True

        added = register_file(result["file_path"], result["keywords"])
        if not added:
            self._speak_proxy(self._tts_model, self._silence, "Ключевые слова не указаны. Файл не добавлен.")
            return True

        self._speak_proxy(self._tts_model, self._silence, f"Файл добавлен. Ключи: {', '.join(added)}")
        return True

    def run(self):
        try:
            switch_to_english_layout()
            self.status.emit("Загрузка моделей")
            self.log.emit("Инициализация STT и TTS...")

            self._stt_model = initialize_stt()
            self._tts_model, self._silence = initialize_tts()
            warmup_tts(self._tts_model, self._silence)

            # Подменяем speak внутри commands.py, чтобы все ответы шли через GUI-лог
            commands_module.speak = self._speak_proxy

            self._timer_manager = TimerManager(self._timer_speak_proxy)
            self._timer_manager.start()

            self.ready.emit()

            self._speak_proxy(self._tts_model, self._silence, "Ассистент готов. Скажите Джарвис, чтобы обратиться ко мне.")
            self.status.emit("Ожидаю Джарвис")
            self.awake_changed.emit(False)

            with SpeechListener(self._stt_model, stop_event=self._stop_event) as listener:
                while not self._stop_event.is_set():
                    text = listener.listen_once()

                    if self._stop_event.is_set():
                        break

                    if not text:
                        continue

                    has_wake_word, command_text = strip_wake_word(text)

                    if not has_wake_word and not self._awake.is_set():
                        self.status.emit("Ожидаю Джарвис")
                        continue

                    self.log.emit(f"Вы: {text if has_wake_word else command_text}")

                    if has_wake_word:
                        self._awake.set()
                        self.awake_changed.emit(True)
                        if not command_text:
                            self._speak_proxy(self._tts_model, self._silence, "Слушаю.")
                            self.status.emit("Слушаю команду")
                            continue

                    if any(k in command_text for k in SLEEP_COMMANDS):
                        self._awake.clear()
                        self.awake_changed.emit(False)

                    self.status.emit("Обрабатываю")

                    if "добавить файл" in command_text:
                        self._handle_add_file()
                        if not self._stop_event.is_set():
                            self.status.emit("Слушаю команду" if self._awake.is_set() else "Ожидаю Джарвис")
                        continue

                    keep_running = process_command(
                        command_text,
                        self._tts_model,
                        self._silence,
                        self._timer_manager
                    )

                    if keep_running is False:
                        break

                    if not self._stop_event.is_set():
                        self.status.emit("Слушаю команду" if self._awake.is_set() else "Ожидаю Джарвис")

        except Exception as e:
            self.log.emit(f"Ошибка: {e}")
            self.status.emit("Ошибка")
        finally:
            try:
                if self._timer_manager:
                    self._timer_manager.stop()
            except Exception:
                pass

            self.status.emit("Остановлен")
            self.finished_clean.emit()
