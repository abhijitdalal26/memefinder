#!/usr/bin/env python3
"""
Launcher + watchdog + live dashboard for collect_to_target.py
Run: python run_collection.py
"""
import os
import sys
import time
import json
import subprocess
import threading
from pathlib import Path
from datetime import datetime, timedelta

os.system("")

BASE_DIR = Path(__file__).resolve().parent
CURATED_DIR = BASE_DIR / "data" / "curated"
METADATA_FILE = BASE_DIR / "curated_metadata.json"
LOCK_FILE = BASE_DIR / "collect_target.lock"
LOG_FILE = BASE_DIR / "collect_target.log"
TARGET = 50000  # balanced 50k target for text→meme retrieval
COLLECT_SCRIPT = BASE_DIR / "collect_to_target.py"

REFRESH_SEC = 10
RATE_WINDOW_SEC = 300

CLEAR = "\x1b[2J\x1b[H"
BOLD = "\x1b[1m"
DIM = "\x1b[2m"
RED = "\x1b[31m"
GREEN = "\x1b[32m"
YELLOW = "\x1b[33m"
CYAN = "\x1b[36m"
RESET = "\x1b[0m"
BAR_FULL = "#"
BAR_EMPTY = "-"

class Dashboard:
    def __init__(self):
        self.history = []
        self.start_time = time.time()
        self.restarts = 0
        self.last_checkpoint = 0

    def get_counts(self):
        file_count = 0
        try:
            for _ in CURATED_DIR.rglob("*"):
                if _.is_file():
                    file_count += 1
        except Exception:
            pass

        meta_count = 0
        sub_counts = {}
        try:
            if METADATA_FILE.exists():
                with open(METADATA_FILE, "r", encoding="utf-8") as f:
                    records = json.load(f)
                meta_count = len(records)
                for r in records:
                    sub = (r.get("source_sub") or "").replace("r/", "")
                    if sub:
                        sub_counts[sub] = sub_counts.get(sub, 0) + 1
        except Exception:
            pass

        return file_count, meta_count, sub_counts

    def get_collector_status(self):
        if not LOCK_FILE.exists():
            return "STOPPED", None, None
        try:
            pid = int(LOCK_FILE.read_text().strip())
            import ctypes
            if pid > 0 and ctypes.windll.kernel32.OpenProcess(0x1000, False, pid):
                return "RUNNING", pid, None
            else:
                return "STALE LOCK", pid, "dead"
        except Exception:
            return "UNKNOWN", None, None

    def render(self, file_count, meta_count, sub_counts, collector_state, pid, restart_reason):
        now = time.time()
        self.history.append((now, file_count))
        cutoff = now - RATE_WINDOW_SEC
        self.history = [(t, c) for t, c in self.history if t >= cutoff]

        rate = 0.0
        if len(self.history) >= 2:
            dt = self.history[-1][0] - self.history[0][0]
            dc = self.history[-1][1] - self.history[0][1]
            if dt > 0:
                rate = max(0.0, (dc / dt) * 60)

        progress = min(file_count / TARGET, 1.0)
        bar_width = 40
        filled = int(progress * bar_width)
        bar = BAR_FULL * filled + BAR_EMPTY * (bar_width - filled)

        remaining = max(TARGET - file_count, 0)
        eta_str = "N/A"
        if rate > 0:
            eta_min = remaining / rate
            eta_str = str(timedelta(minutes=eta_min)).split(".")[0]

        uptime_str = str(timedelta(seconds=int(now - self.start_time))).split(".")[0]

        state_color = GREEN if collector_state == "RUNNING" else (YELLOW if "STALE" in collector_state else RED)

        top_subs = sorted(sub_counts.items(), key=lambda x: -x[1])[:10]
        sub_lines = [f"  {CYAN}{sub:<25}{RESET} {count:>6}" for sub, count in top_subs]

        pid_str = f"(pid {pid})" if pid else ""

        out = []
        out.append(f"{CLEAR}{BOLD}+ MakeMeMeme Collector -------------------------------+{RESET}")
        out.append(f"{BOLD}|{RESET} Status: {state_color}{collector_state:12}{RESET} {pid_str:<12} Uptime: {uptime_str}")
        out.append(f"{BOLD}|{RESET} Progress: [{bar}] {file_count:,} / {TARGET:,}")
        out.append(f"{BOLD}|{RESET} {progress*100:>5.1f}%   Rate: {rate:>6.1f} memes/min   ETA: {eta_str}")
        out.append(f"{BOLD}|{RESET} Restarts: {self.restarts}   Last checkpoint: {self.last_checkpoint:,}")
        if restart_reason:
            out.append(f"{BOLD}|{RESET} {YELLOW}Last restart: {restart_reason}{RESET}")
        out.append(f"{BOLD}+ Top subreddits -----------------------------------+{RESET}")
        for line in sub_lines:
            out.append(f"{BOLD}|{RESET}{line}")
        out.append(f"{BOLD}+---------------------------------------------------+{RESET}")
        sys.stdout.write("\n".join(out) + "\n")
        sys.stdout.flush()

class Watchdog:
    def __init__(self, dashboard):
        self.dashboard = dashboard
        self.proc = None
        self.running = True
        self.last_restart_reason = None

    def start_collector(self):
        if self.proc and self.proc.poll() is None:
            return
        # guard against stale lock race: don't spawn if another collector already holds lock
        state, pid, _ = self.dashboard.get_collector_status()
        if state == "RUNNING":
            self.last_restart_reason = f"skip start: already RUNNING pid {pid}"
            return
        self.proc = subprocess.Popen(
            [sys.executable, str(COLLECT_SCRIPT), "--target", str(TARGET)],
            cwd=BASE_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
        )
        self.last_restart_reason = f"started at {datetime.now().strftime('%H:%M:%S')}"

    def stop_collector(self):
        if self.proc and self.proc.poll() is None:
            try:
                if os.name == "nt":
                    self.proc.send_signal(subprocess.signal.CTRL_BREAK_EVENT)
                else:
                    self.proc.terminate()
                self.proc.wait(timeout=5)
            except Exception:
                self.proc.kill()

    def check_and_restart(self):
        state, pid, reason = self.dashboard.get_collector_status()
        if state != "RUNNING" and self.running:
            self.dashboard.restarts += 1
            self.last_restart_reason = f"{state} {reason or ''} at {datetime.now().strftime('%H:%M:%S')}"
            self.start_collector()

    def loop(self):
        self.start_collector()
        while self.running:
            self.check_and_restart()
            time.sleep(REFRESH_SEC)

def main():
    dashboard = Dashboard()
    watchdog = Watchdog(dashboard)
    watchdog_thread = threading.Thread(target=watchdog.loop, daemon=True)
    watchdog_thread.start()

    try:
        while True:
            file_count, meta_count, sub_counts = dashboard.get_counts()
            dashboard.last_checkpoint = meta_count
            state, pid, reason = dashboard.get_collector_status()
            dashboard.render(file_count, meta_count, sub_counts, state, pid, watchdog.last_restart_reason)
            time.sleep(REFRESH_SEC)
    except KeyboardInterrupt:
        print(f"\n{CYAN}Shutting down...{RESET}")
        watchdog.running = False
        watchdog.stop_collector()
        watchdog_thread.join(timeout=3)
        print(f"{GREEN}Done.{RESET}")

if __name__ == "__main__":
    main()
