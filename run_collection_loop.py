"""Watchdog v2: keep collect_to_target.py running until the 50k target is hit.

Handles BOTH failure modes observed overnight:
  1. hard crashes   -> subprocess exits, we relaunch
  2. silent hangs   -> collect_target.log untouched for STALE_SEC seconds,
                       we taskkill the whole tree and relaunch
Every relaunch resumes from checkpoints (max 250 memes lost).
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime

TARGET = 50000
STALE_SEC = 600          # no log activity for 10 min => hung
POLL_SEC = 60
LOG_FILE = "collect_target.log"


def count():
    try:
        return len(json.load(open("curated_metadata.json", encoding="utf-8")))
    except Exception:
        return -1


def log(msg):
    line = f"[{datetime.now().strftime('%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open("collect_watchdog.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def log_age_sec():
    try:
        return time.time() - os.path.getmtime(LOG_FILE)
    except OSError:
        return 0


def main():
    run = 0
    while True:
        n = count()
        if n >= TARGET:
            log(f"DONE: {n} >= {TARGET}")
            break
        run += 1
        log(f"run #{run} start (curated={n}/{TARGET})")
        proc = subprocess.Popen([sys.executable, "collect_to_target.py",
                                 "--target", str(TARGET)])
        killed = False
        while proc.poll() is None:
            time.sleep(POLL_SEC)
            if log_age_sec() > STALE_SEC:
                log(f"run #{run}: no log activity for {STALE_SEC}s "
                    f"-> killing hung process tree")
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                               capture_output=True)
                killed = True
                break
        proc.wait()
        n = count()
        log(f"run #{run} ended ({'KILLED-stale' if killed else 'exited'}) "
            f"curated={n}")
        if n < TARGET:
            time.sleep(15)


if __name__ == "__main__":
    main()
