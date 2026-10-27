import os
import platform
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

DATA_DIR = ROOT_DIR / "data"
PROJECTS_DIR = DATA_DIR / "projects"
PRODUCTS_DIR = DATA_DIR / "products"
FRONTEND_DIST = ROOT_DIR / "frontend" / "dist"

for _d in (PROJECTS_DIR, PRODUCTS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# 실행 환경 — OS별로 다른 처리(실행 파일 이름, 시스템 TTS 등)는 이 값으로 분기한다
_system = platform.system()
PLATFORM = {"Darwin": "mac", "Windows": "windows"}.get(_system, "linux")
LAUNCHER = "2_실행하기.bat" if PLATFORM == "windows" else "2_실행하기.command"

# Claude — 키가 비어 있으면 mock 모드로 동작
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-5-5").strip()
# 워크스페이스에 묶이지 않은 키(sk-ant-usr-…)는 요청마다 워크스페이스 ID가 필요하다
ANTHROPIC_WORKSPACE_ID = os.getenv("ANTHROPIC_WORKSPACE_ID", "").strip()

# STT — local | openai | gemini (openai/gemini는 추후 구현)
STT_ENGINE = os.getenv("STT_ENGINE", "local").strip().lower()
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small").strip()

# 영상 자동화 엔진 — 실제 엔진이 붙기 전까지 mock / system 으로 동작
VISUAL_ENGINE = os.getenv("VISUAL_ENGINE", "mock").strip().lower()
SOUND_ENGINE = os.getenv("SOUND_ENGINE", "system").strip().lower()  # system(OS 기본 음성) | silent

# Flow 메신저 승인 알림 (추후 연동) — 비어 있으면 앱 화면 알림만 사용
FLOW_API_URL = os.getenv("FLOW_API_URL", "").strip()
FLOW_API_TOKEN = os.getenv("FLOW_API_TOKEN", "").strip()
FLOW_ROOM_ID = os.getenv("FLOW_ROOM_ID", "").strip()
FLOW_WEBHOOK_SECRET = os.getenv("FLOW_WEBHOOK_SECRET", "").strip()
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").strip().rstrip("/")

# 레퍼런스 분석 규칙
MAX_VIDEO_SEC = 180
SEGMENT_SEC = 2.0
ASPECT_RATIOS = ["1:1", "4:5", "16:9", "9:16"]
