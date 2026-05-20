import sys
from html import escape

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QTextCursor
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from assistant_worker import AssistantWorker
from commands import register_file
from secret_store import (
    REQUIRED_SECRETS,
    SecretStoreError,
    get_secret,
    has_all_required_secrets,
    save_required_secrets,
    validate_secret_format,
)

COMMAND_HELP = [
    ("Wake word", "джарвис / джервис / jarvis", "Активирует ассистента"),
    ("Ожидание", "отойди / спи / замолчи / хватит", "Возвращает ассистента в ожидание wake word"),
    ("Файлы", "добавить файл", "Открывает GUI для выбора файла и ключевых слов"),
    ("Файлы", "открой файл <ключ>", "Открывает привязанный файл"),
    ("ПК", "выключи компьютер без подтверждения", "Выключает компьютер"),
    ("ПК", "перезагрузи компьютер без подтверждения", "Перезагружает компьютер"),
    ("ПК", "спящий режим / сон ", "Переводит компьютер в сон"),
    ("Браузер", "открой браузер <запрос>", "Открывает Google или поиск"),
    ("Буфер", "скопируй / вставь", "Копирует или вставляет выделенное"),
    ("Буфер", "скопировать в буфер <текст>", "Сохраняет произнесенный текст в буфер"),
    ("Экран", "что на экране / прочитай экран", "Делает скриншот и описывает экран"),
    ("Время", "время", "Говорит текущее время"),
    ("Система", "система / статус / ресурсы", "Говорит общий отчет по системе"),
    ("Система", "процессор / память / диск / сеть", "Говорит отдельные метрики"),
    ("Громкость", "громче / тише / выключи звук", "Управляет громкостью"),
    ("Заметки", "запиши <текст> / заметка <текст>", "Добавляет запись в notes.txt"),
    ("Таймер", "установи таймер на 5 минут", "Ставит таймер"),
    ("Напоминание", "напомни через 5 минут <текст>", "Ставит напоминание"),
    ("Таймеры", "активные таймеры / активные таймера", "Говорит количество активных таймеров"),
]


class CommandsHelpDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Подсказка по командам")
        self.setMinimumSize(760, 520)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        title = QLabel("Актуальные голосовые команды")
        title.setObjectName("SectionTitle")
        layout.addWidget(title)

        help_text = QTextEdit()
        help_text.setReadOnly(True)
        help_text.setFont(QFont("Consolas", 10))
        help_text.setHtml(self._build_html())
        layout.addWidget(help_text, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _build_html(self) -> str:
        rows = "\n".join(
            f"<tr><td>{escape(category)}</td><td><code>{escape(phrase)}</code></td><td>{escape(description)}</td></tr>"
            for category, phrase, description in COMMAND_HELP
        )
        return f"""
        <style>
            table {{ border-collapse: collapse; width: 100%; }}
            th, td {{ border: 1px solid #334666; padding: 7px; vertical-align: top; }}
            th {{ background: #17233b; color: #eef4ff; }}
            td {{ color: #dce6f7; }}
            code {{ color: #ffffff; }}
        </style>
        <table>
            <tr><th>Категория</th><th>Фраза</th><th>Действие</th></tr>
            {rows}
        </table>
        """


class CredentialsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ключи доступа")
        self.setMinimumWidth(520)
        self.inputs = {}

        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        description = QLabel(
            "Введите ключи для двух нейросетей. Они сохранятся в системном хранилище "
            "учетных данных и не будут записаны в код проекта."
        )
        description.setWordWrap(True)
        description.setObjectName("Subtitle")
        layout.addWidget(description)

        form = QFormLayout()
        form.setSpacing(10)

        for spec in REQUIRED_SECRETS:
            field = QLineEdit()
            field.setEchoMode(QLineEdit.EchoMode.Password)
            field.setPlaceholderText(f"Начинается с {spec.expected_prefix}")
            try:
                has_saved_secret = bool(get_secret(spec))
            except SecretStoreError as exc:
                QMessageBox.critical(self, "Ошибка хранилища ключей", str(exc))
                has_saved_secret = False
            if has_saved_secret:
                field.setPlaceholderText("Ключ уже сохранен. Введите новый, чтобы заменить.")
            self.inputs[spec.id] = field
            form.addRow(spec.label, field)

        layout.addLayout(form)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self._save)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def _save(self):
        values = {}
        for spec in REQUIRED_SECRETS:
            raw_value = self.inputs[spec.id].text().strip()
            try:
                values[spec.id] = raw_value or (get_secret(spec) or "")
            except SecretStoreError as exc:
                QMessageBox.critical(self, "Ошибка хранилища ключей", str(exc))
                return
            error = validate_secret_format(spec, values[spec.id])
            if error:
                QMessageBox.warning(self, "Проверьте ключ", error)
                self.inputs[spec.id].setFocus()
                return

        try:
            save_required_secrets(values)
        except SecretStoreError as exc:
            QMessageBox.critical(self, "Не удалось сохранить", str(exc))
            return

        self.accept()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.worker = None

        self.setWindowTitle("JARVIS Assistant")
        self.setMinimumSize(980, 680)

        root = QWidget()
        self.setCentralWidget(root)

        outer = QVBoxLayout(root)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(18)

        # ===== Header =====
        header = QFrame()
        header.setObjectName("Card")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(20, 18, 20, 18)
        header_layout.setSpacing(16)

        title_block = QVBoxLayout()
        title = QLabel("JARVIS")
        title.setObjectName("Title")
        subtitle = QLabel("Голосовой ассистент с режимами слушания, речи и таймерами")
        subtitle.setObjectName("Subtitle")
        title_block.addWidget(title)
        title_block.addWidget(subtitle)

        self.status_pill = QLabel("Остановлен")
        self.status_pill.setObjectName("StatusPill")
        self.status_pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_pill.setMinimumWidth(140)

        header_layout.addLayout(title_block)
        header_layout.addStretch(1)
        header_layout.addWidget(self.status_pill)

        # ===== Log Card =====
        log_card = QFrame()
        log_card.setObjectName("Card")
        log_layout = QVBoxLayout(log_card)
        log_layout.setContentsMargins(18, 18, 18, 18)
        log_layout.setSpacing(12)

        log_label = QLabel("Лог")
        log_label.setObjectName("SectionTitle")

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setFont(QFont("Consolas", 11))
        self.log_box.setPlaceholderText("Здесь будут появляться распознанные команды и ответы ассистента...")

        log_layout.addWidget(log_label)
        log_layout.addWidget(self.log_box)

        # ===== Controls Card =====
        controls = QFrame()
        controls.setObjectName("Card")
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(18, 18, 18, 18)
        controls_layout.setSpacing(12)

        self.start_btn = QPushButton("▶ Старт")
        self.start_btn.clicked.connect(self.start_assistant)

        self.stop_btn = QPushButton("■ Стоп")
        self.stop_btn.clicked.connect(self.stop_assistant)
        self.stop_btn.setEnabled(False)

        self.clear_btn = QPushButton("✦ Очистить лог")
        self.clear_btn.clicked.connect(self.log_box.clear)

        self.credentials_btn = QPushButton("Ключи доступа")
        self.credentials_btn.clicked.connect(self.open_credentials_dialog)

        self.add_file_btn = QPushButton("Добавить файл")
        self.add_file_btn.clicked.connect(self.open_add_file_dialog)

        self.help_btn = QPushButton("Подсказка")
        self.help_btn.clicked.connect(self.open_commands_help)

        controls_layout.addWidget(self.start_btn)
        controls_layout.addWidget(self.stop_btn)
        controls_layout.addWidget(self.clear_btn)
        controls_layout.addWidget(self.credentials_btn)
        controls_layout.addWidget(self.add_file_btn)
        controls_layout.addWidget(self.help_btn)
        controls_layout.addStretch(1)

        footer = QLabel("PyQt6 UI • фоновой поток")
        footer.setObjectName("Footer")

        outer.addWidget(header)
        outer.addWidget(log_card, 1)
        outer.addWidget(controls)
        outer.addWidget(footer)

        self._apply_theme()
        self._update_credentials_status()
        QTimer.singleShot(300, self.start_assistant)

    def _apply_theme(self):
        self.setStyleSheet("""
            QMainWindow {
                background: #0b1020;
                color: #e7eefb;
            }

            QFrame#Card {
                background: #111a2f;
                border: 1px solid #223152;
                border-radius: 22px;
            }

            QLabel#Title {
                font-size: 30px;
                font-weight: 800;
                color: #f4f7ff;
            }

            QLabel#Subtitle {
                color: #96a7c3;
                font-size: 12px;
            }

            QLabel#SectionTitle {
                color: #d9e3f4;
                font-size: 13px;
                font-weight: 700;
            }

            QLabel#Footer {
                color: #6f7f98;
                font-size: 11px;
                padding-left: 4px;
            }

            QLabel#StatusPill {
                background: #2b364e;
                color: #ffffff;
                border-radius: 16px;
                padding: 10px 16px;
                font-size: 12px;
                font-weight: 700;
            }

            QTextEdit {
                background: #0a1222;
                color: #dce6f7;
                border: 1px solid #223152;
                border-radius: 18px;
                padding: 12px;
                selection-background-color: #3d5afe;
            }

            QPushButton {
                background: #17233b;
                color: #eef4ff;
                border: 1px solid #2f4368;
                border-radius: 14px;
                padding: 12px 18px;
                font-size: 13px;
                font-weight: 700;
            }

            QPushButton:hover {
                background: #1d2c49;
            }

            QPushButton:pressed {
                background: #152036;
            }

            QPushButton:disabled {
                background: #10192a;
                color: #6d7b92;
                border-color: #1d2a42;
            }
        """)

    def append_log(self, text: str):
        self.log_box.append(text)
        self.log_box.moveCursor(QTextCursor.MoveOperation.End)

    def set_status(self, text: str):
        self.status_pill.setText(text)

        status = text.lower()
        if "говор" in status:
            bg = "#3d5afe"
        elif "слуш" in status:
            bg = "#2e7d32"
        elif "обработ" in status:
            bg = "#b26a00"
        elif "загруз" in status:
            bg = "#546e7a"
        elif "ошиб" in status:
            bg = "#b71c1c"
        else:
            bg = "#2b364e"

        self.status_pill.setStyleSheet(f"""
            QLabel#StatusPill {{
                background: {bg};
                color: white;
                border-radius: 16px;
                padding: 10px 16px;
                font-size: 12px;
                font-weight: 700;
            }}
        """)

    def _update_credentials_status(self):
        try:
            if has_all_required_secrets():
                self.append_log("Ключи доступа сохранены.")
            else:
                self.append_log("Ключи доступа не заданы. Откройте «Ключи доступа» перед стартом.")
        except SecretStoreError as exc:
            self.append_log(str(exc))

    def open_credentials_dialog(self) -> bool:
        dialog = CredentialsDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.append_log("Ключи доступа сохранены.")
            return True
        return False

    def open_commands_help(self):
        CommandsHelpDialog(self).exec()

    def open_add_file_dialog(self, from_voice_command: bool = False):
        file_path, _ = QFileDialog.getOpenFileName(self, "Выберите файл для голосового открытия")
        if not file_path:
            if from_voice_command and self.worker:
                self.worker.provide_add_file_result(None)
            return

        keywords_text, ok = QInputDialog.getText(
            self,
            "Ключевые слова",
            "Введите ключевые слова через запятую, например: дискорд, дс, дис",
        )
        if not ok:
            if from_voice_command and self.worker:
                self.worker.provide_add_file_result(None)
            return

        keywords = [keyword.strip().lower() for keyword in keywords_text.split(",") if keyword.strip()]
        if not keywords:
            QMessageBox.warning(self, "Ключевые слова", "Введите хотя бы одно ключевое слово.")
            if from_voice_command and self.worker:
                self.worker.provide_add_file_result(None)
            return

        if from_voice_command and self.worker and self.worker.isRunning():
            self.worker.provide_add_file_result({
                "file_path": file_path,
                "keywords": keywords,
            })
            return

        added = register_file(file_path, keywords)
        self.append_log(f"Файл добавлен. Ключи: {', '.join(added)}")

    def open_add_file_dialog_from_voice(self):
        self.open_add_file_dialog(from_voice_command=True)

    def start_assistant(self):
        if self.worker and self.worker.isRunning():
            return

        try:
            secrets_ready = has_all_required_secrets()
        except SecretStoreError as exc:
            QMessageBox.critical(self, "Ошибка хранилища ключей", str(exc))
            self.append_log(str(exc))
            return

        if not secrets_ready:
            self.append_log("Для запуска нужны ключи io.net и OpenRouter.")
            if not self.open_credentials_dialog():
                self.append_log("Запуск отменен: ключи доступа не сохранены.")
                return

        self.worker = AssistantWorker()
        self.worker.log.connect(self.append_log)
        self.worker.status.connect(self.set_status)
        self.worker.finished_clean.connect(self.on_worker_finished)
        self.worker.ready.connect(self.on_worker_ready)
        self.worker.add_file_requested.connect(self.open_add_file_dialog_from_voice)

        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.set_status("Загрузка моделей")
        self.append_log("Запуск ассистента...")

        self.worker.start()

    def stop_assistant(self):
        if self.worker and self.worker.isRunning():
            self.append_log("Остановка ассистента...")
            self.worker.request_stop()
            self.stop_btn.setEnabled(False)

    def on_worker_ready(self):
        self.append_log("Ассистент запущен.")

    def on_worker_finished(self):
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.set_status("Остановлен")
        self.append_log("Ассистент остановлен.")

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.worker.request_stop()
            self.worker.wait(2500)
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
