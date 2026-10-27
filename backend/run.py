"""서버 실행 + 브라우저 자동 열기. 2_실행하기.bat / 2_실행하기.command 가 이 파일을 실행한다.

- 서버가 실제로 응답하기 시작하면 기본 브라우저로 화면을 연다 (Windows·Mac 공통).
- 이미 실행 중이면 서버를 또 띄우지 않고 브라우저만 연다.
"""
import socket
import sys
import threading
import time
import webbrowser

import uvicorn

HOST, PORT = "127.0.0.1", 8000
URL = f"http://localhost:{PORT}"


def server_is_up() -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex((HOST, PORT)) == 0


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

    if server_is_up():
        print(f"이미 실행 중입니다. 브라우저만 엽니다: {URL}")
        webbrowser.open(URL)
        return

    print("=" * 56)
    print("  오이요하 퍼포먼스 영상 자동화")
    print(f"  주소: {URL}")
    print("  이 창을 닫으면 프로그램이 종료됩니다.")
    print("=" * 56, flush=True)
    threading.Thread(target=open_browser_when_ready, daemon=True).start()
    uvicorn.run("main:app", host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
