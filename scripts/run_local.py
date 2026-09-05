"""Start all three local services; stop only processes started by this launcher."""
from pathlib import Path
import os
import signal
import socket
import subprocess
import time
import urllib.request
import webbrowser
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]

def wait_ready(url, child, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if child.poll() is not None:
            raise RuntimeError('A service exited. Check its log under data/logs/.')
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except (OSError, TimeoutError):
            pass
        time.sleep(.5)
    raise RuntimeError(f'Service did not become ready: {url}. Check data/logs/.')

def main():
    os.chdir(ROOT)
    load_dotenv(ROOT / '.env')
    web_port = int(os.environ.get('PACEBOARD_WEB_PORT', '3000'))
    api_port = int(os.environ.get('PACEBOARD_API_PORT', '8787'))
    garmin_port = int(os.environ.get('GARMIN_MCP_PORT', '8000'))
    for port in (web_port, api_port, garmin_port):
        with socket.socket() as sock:
            try:
                sock.bind(('127.0.0.1', port))
            except OSError:
                raise RuntimeError(f'Port {port} is already in use. Stop the other instance first; no running service was changed.')
    os.environ.update(PACEBOARD_HOST='127.0.0.1', GARMIN_MCP_HOST='127.0.0.1',
                      GARMIN_MCP_URL=f'http://127.0.0.1:{garmin_port}/mcp',
                      PACEBOARD_WEB_PORT=str(web_port), PACEBOARD_API_PORT=str(api_port))
    logs = ROOT / 'data/logs'
    logs.mkdir(parents=True, exist_ok=True)
    os.chmod(logs, 0o700)
    children, handles = [], []
    def stop(_signum, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    try:
        commands = [
            ('garmin', ['bash', 'scripts/garmin-mcp-readonly.sh'], f'http://127.0.0.1:{garmin_port}/healthz'),
            ('api', ['uv', 'run', '--locked', '--python', '3.12', '--extra', 'paceboard', 'paceboard-api', 'serve'], f'http://127.0.0.1:{api_port}/healthz'),
            ('dashboard', ['node', 'dashboard/scripts/serve.mjs'], f'http://127.0.0.1:{web_port}/'),
        ]
        for name, command, url in commands:
            print(f'Starting {name}…', flush=True)
            log = open(logs / f'{name}.log', 'a')
            os.chmod(log.name, 0o600)
            handles.append(log)
            child = subprocess.Popen(command, stdout=log, stderr=log, start_new_session=True)
            children.append(child)
            wait_ready(url, child)
        url = f'http://127.0.0.1:{web_port}/'
        print(f'\nPaceboard is ready: {url}\nOpen Connections to authorize Strava and backfill history.\nKeep this terminal open. Press Ctrl-C to stop.', flush=True)
        webbrowser.open(url)
        while all(child.poll() is None for child in children):
            time.sleep(1)
        raise RuntimeError('A service stopped. Check data/logs/ and restart.')
    finally:
        for child in reversed(children):
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
        for child in children:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
        for handle in handles:
            handle.close()

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nPaceboard stopped. Your data is saved.')
    except (RuntimeError, ValueError) as exc:
        raise SystemExit(str(exc))
