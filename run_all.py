"""
VPS Orchestrator for gvtsch2.

Runs every scraper as a subprocess on its own schedule (concurrently),
then runs sch.py to merge everything into sch.json.

Designed to run under PM2 (see ecosystem.config.js) as a long-lived process.
Usage:
    python run_all.py                  # run one full cycle and exit
    python run_all.py --daemon         # run forever with scheduling (PM2)
"""
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)

# ------------------------------------------------------------------
# SCRAPERS: (name, script, interval_seconds, enabled)
# ------------------------------------------------------------------
SCRAPERS = [
    ("soco",            "soco.py",            180,  True),   # 3 min
    ("90phut",          "90phut.py",          180,  True),   # 3 min
    ("colatv",          "colatv.py",          180,  True),   # 3 min
    ("bolaloca",        "bolaloca.py",        180,  True),   # 3 min
    ("flashscore",      "flashscore.py",      600,  False),  # off: butuh Chrome (tak ada di VPS)
    ("flashscore_home", "flashscore_home.py", 180,  False),  # optional
    ("sportsonline",    "sportsonline.py",    180,  True),   # 3 min
    ("timstreams",      "timstreams.py",      180,  True),   # 3 min
    ("sofascore",       "sofascore.py",       180,  True),   # 3 min
    ("kralsport",       "kralsport.py",       180,  True),   # 3 min
    ("xoilac",          "xoilac.py",          180,  True),   # 3 min
]

MERGE_SCRIPT = "sch.py"
MERGE_INTERVAL = 120  # 2 min

LOCK = threading.Lock()
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(os.path.join(LOG_DIR, "orchestrator.log"), "a", encoding="utf-8") as f:
        f.write(line + "\n")


def run_script(label, script):
    """Run one scraper as a subprocess; log pass/fail."""
    start = time.time()
    try:
        proc = subprocess.run(
            [sys.executable, os.path.join(BASE_DIR, script)],
            cwd=BASE_DIR,
            timeout=600,
            capture_output=True,
            text=True,
            encoding="utf-8",   # scrapers emit Vietnamese/emoji output; cp1252 would crash
            errors="replace",
        )
        elapsed = time.time() - start
        if proc.returncode == 0:
            log(f"[OK]   {label:16s} done in {elapsed:.1f}s")
        else:
            tail = (proc.stderr or proc.stdout or "")[-800:]
            log(f"[FAIL] {label:16s} rc={proc.returncode} ({elapsed:.1f}s)\n{tail}")
    except subprocess.TimeoutExpired:
        log(f"[FAIL] {label:16s} TIMEOUT after 600s")
    except Exception as e:
        log(f"[FAIL] {label:16s} exception: {e}")


def scraper_loop(label, script, interval):
    """Daemon loop: run scraper, then sleep for the interval."""
    while True:
        if shutil.which("chmod"):
            pass
        run_script(label, script)
        time.sleep(interval)


def run_all_once():
    """Run all scrapers sequentially (single cycle). Used by non-daemon mode."""
    threads = []
    for label, script, _, enabled in SCRAPERS:
        if not enabled:
            continue
        t = threading.Thread(target=run_script, args=(label, script), daemon=True)
        t.start()
        threads.append(t)
    for t in threads:
        t.join()
    log("All scrapers finished. Running merge...")
    run_script("merge", MERGE_SCRIPT)


def run_daemon():
    """Run every scraper on its own interval (thread pool) + periodic merge."""
    log("Starting gvtsch2 VPS orchestrator (daemon mode).")
    threads = []
    for label, script, interval, enabled in SCRAPERS:
        if not enabled:
            continue
        t = threading.Thread(target=scraper_loop, args=(label, script, interval), daemon=True)
        t.start()
        threads.append(t)

    # Periodic merge thread
    merge_thread = threading.Thread(target=scraper_loop, args=("merge", MERGE_SCRIPT, MERGE_INTERVAL), daemon=True)
    merge_thread.start()
    threads.append(merge_thread)

    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        log("Stopped by user.")


def main():
    if "--daemon" in sys.argv:
        run_daemon()
    else:
        run_all_once()


if __name__ == "__main__":
    main()