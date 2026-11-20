"""서버 실행 + 브라우저 자동 열기. 2_실행하기.bat / 2_실행하기.command 가 이 파일을 실행한다.

- 서버가 실제로 응답하기 시작하면 기본 브라우저로 화면을 연다 (Windows·Mac 공통).
- 이미 실행 중이면 서버를 또 띄우지 않고 브라우저만 연다.
  단, 8000번 포트의 서버가 다른 폴더나 다른 버전(예전 프로그램)이면 그 서버를 끄고 새로 띄운다.
  (예전 창을 켜 둔 채 업데이트하면 새 버전을 설치해도 브라우저가 계속 예전 프로그램에 연결되던 문제)
- 서버를 띄우기 전에 업데이트를 반영한다 (updater.py: 새 설정 칸·빈 API 키·패키지·화면 다시 만들기).
"""
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

import uvicorn

HOST, PORT = "127.0.0.1", 8000
URL = f"http://localhost:{PORT}"


def server_is_up() -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex((HOST, PORT)) == 0


ROOT = Path(__file__).resolve().parent.parent


def running_server() -> dict | None:
    """지금 8000번 포트에서 도는 서버의 상태. 이 프로그램이 아니면(또는 응답이 없으면) None."""
    try:
        with urllib.request.urlopen(f"http://{HOST}:{PORT}/api/status", timeout=3) as r:
            data = json.loads(r.read())
        return data if isinstance(data, dict) and "claude_configured" in data else None
    except Exception:  # noqa: BLE001
        return None


def _port_pids() -> list[int]:
    """8000번 포트를 듣고 있는 프로세스 번호."""
    if os.name == "nt":
        out = subprocess.run(["netstat", "-ano", "-p", "tcp"], capture_output=True, text=True, errors="replace").stdout
        pids = {int(m.group(1)) for m in re.finditer(rf"[:.]{PORT}\s+\S+\s+LISTENING\s+(\d+)", out)}
    else:
        out = subprocess.run(["lsof", "-ti", f"tcp:{PORT}", "-sTCP:LISTEN"], capture_output=True, text=True).stdout
        pids = {int(x) for x in out.split()}
    return sorted(p for p in pids if p and p != os.getpid())


def stop_old_server() -> bool:
    for pid in _port_pids():
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
        else:
            subprocess.run(["kill", str(pid)], capture_output=True)
    for _ in range(20):
        if not server_is_up():
            return True
        time.sleep(0.5)
    return False


def open_browser_when_ready() -> None:
    for _ in range(120):  # 최대 60초 대기 (첫 실행은 모듈 로딩이 느릴 수 있음)
        if server_is_up():
            print(f"브라우저를 엽니다: {URL}", flush=True)
            if not webbrowser.open(URL):
                print(f"브라우저를 자동으로 열지 못했습니다. 주소창에 직접 입력하세요: {URL}", flush=True)
            return
        time.sleep(0.5)
    print(f"서버 준비가 늦어지고 있습니다. 잠시 후 주소창에 직접 입력하세요: {URL}", flush=True)


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

    from version import APP_VERSION  # config는 .env를 읽으므로 업데이트(새 키 입력) 뒤에 불러온다

    if server_is_up():
        other = running_server()
        same = (other and other.get("app_version") == APP_VERSION
                and os.path.normcase(str(Path(other.get("root_dir") or "."))) == os.path.normcase(str(ROOT)))
        if same:
            print(f"이미 실행 중입니다. 브라우저만 엽니다: {URL}")
            webbrowser.open(URL)
            return
        if other is None:
            print(f"! {PORT}번 포트를 다른 프로그램이 쓰고 있어 실행할 수 없습니다. 그 프로그램을 끄고 다시 실행하세요.")
            return
        where = other.get("root_dir") or "다른 폴더"
        print(f"예전 프로그램이 아직 켜져 있습니다 (버전 {other.get('app_version') or '이전'}, 위치: {where}).")
        print("예전 프로그램을 끄고 새 버전으로 실행합니다…", flush=True)
        if not stop_old_server():
            print("! 예전 프로그램을 끄지 못했습니다. 예전 실행 창(검은 창)을 직접 닫고 다시 실행하세요.")
            return

    print("업데이트 확인 중…", flush=True)
    try:
        import updater
        updater.run_all()
    except Exception as e:  # noqa: BLE001 — 업데이트 확인이 실패해도 프로그램은 띄운다
        print(f"  ! 업데이트 확인 중 오류: {e}", flush=True)

    import config
    print("=" * 56)
    print(f"  퍼포먼스 영상 자동화  v{config.APP_VERSION}")
    print(f"  주소: {URL}")
    print("  이 창을 닫으면 프로그램이 종료됩니다.")
    print("=" * 56, flush=True)
    threading.Thread(target=open_browser_when_ready, daemon=True).start()
    uvicorn.run("main:app", host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
