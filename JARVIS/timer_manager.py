# timer_manager.py
import json
import os
import threading
import time
from datetime import datetime, timedelta
import schedule

TIMERS_FILE = "timers.json"

class TimerManager:
    def __init__(self, speak_callback):
        self.speak = speak_callback
        self.timers = []
        self._running = False
        self._thread = None
        self._load_timers()

    def _load_timers(self):
        if os.path.exists(TIMERS_FILE):
            try:
                with open(TIMERS_FILE, "r", encoding="utf-8") as f:
                    self.timers = json.load(f)
            except:
                self.timers = []
        else:
            self.timers = []

    def _save_timers(self):
        with open(TIMERS_FILE, "w", encoding="utf-8") as f:
            json.dump(self.timers, f, ensure_ascii=False, indent=2)

    def add_timer(self, duration_seconds: int, message: str = "Таймер сработал"):
        trigger_time = datetime.now() + timedelta(seconds=duration_seconds)
        timer = {
            "trigger_time": trigger_time.isoformat(),
            "message": message,
            "type": "timer"
        }
        self.timers.append(timer)
        self._save_timers()
        return True

    def add_reminder(self, minutes_from_now: int, message: str):
        return self.add_timer(minutes_from_now * 60, f"Напоминание: {message}")

    def get_active_count(self):
        now = datetime.now()
        active = [t for t in self.timers if datetime.fromisoformat(t["trigger_time"]) > now]
        return len(active)

    def _check_timers(self):
        now = datetime.now()
        triggered = []
        for timer in self.timers:
            trigger_time = datetime.fromisoformat(timer["trigger_time"])
            if now >= trigger_time:
                try:
                    self.speak(timer["message"])
                except:
                    pass
                triggered.append(timer)
        if triggered:
            for t in triggered:
                self.timers.remove(t)
            self._save_timers()

    def _run(self):
        schedule.every(1).seconds.do(self._check_timers)
        while self._running:
            schedule.run_pending()
            time.sleep(0.5)

    def start(self):
        if not self._running:
            self._running = True
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
