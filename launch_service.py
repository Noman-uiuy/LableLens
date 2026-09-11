import subprocess
import time
import re
import os
import sys
from pathlib import Path

BASE_DIR = Path(r"C:\Users\Ansar\.gemini\antigravity\scratch\tolmaap-backend")
PYTHON_EXE = str(BASE_DIR / "venv" / "Scripts" / "python.exe")
CLOUDFLARED_EXE = r"C:\Users\Ansar\cloudflared_clean.exe"
URL_FILE = BASE_DIR / "tunnel_url.txt"
LOG_FILE = BASE_DIR / "service.log"

URL_RE = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")

def run():
    with open(LOG_FILE, "w", encoding="utf-8") as log:
        log.write(f"[{time.ctime()}] Starting Tolmaap Backend...\n")
        log.flush()

        # Start FastAPI uvicorn
        backend_proc = subprocess.Popen(
            [PYTHON_EXE, "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"],
            cwd=str(BASE_DIR),
            stdout=log,
            stderr=subprocess.STDOUT
        )

        # Wait for backend
        time.sleep(3)
        log.write(f"[{time.ctime()}] Uvicorn started (PID: {backend_proc.pid}). Starting Cloudflare Tunnel...\n")
        log.flush()

        # Start Cloudflare Tunnel
        tunnel_proc = subprocess.Popen(
            [CLOUDFLARED_EXE, "tunnel", "--url", "http://127.0.0.1:8000", "--no-autoupdate"],
            cwd=str(BASE_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )

        tunnel_url = None
        for line in tunnel_proc.stdout:
            log.write(line)
            log.flush()
            m = URL_RE.search(line)
            if m:
                tunnel_url = m.group(0)
                with open(URL_FILE, "w", encoding="utf-8") as uf:
                    uf.write(tunnel_url.strip())
                log.write(f"\n[{time.ctime()}] ACTIVE TUNNEL URL: {tunnel_url}\n")
                log.flush()
                break

        # Keep both alive
        while True:
            if backend_proc.poll() is not None:
                log.write(f"[{time.ctime()}] Uvicorn exited unexpectedly!\n")
                break
            if tunnel_proc.poll() is not None:
                log.write(f"[{time.ctime()}] Tunnel exited unexpectedly!\n")
                break
            time.sleep(2)

if __name__ == "__main__":
    run()
