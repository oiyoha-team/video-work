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

# 영상 자동화 엔진 — 키가 있으면 실제 서비스, 없으면 mock / OS 음성으로 동작
HIGGSFIELD_API_KEY = os.getenv("HIGGSFIELD_API_KEY", "").strip()  # "키ID:시크릿"
from version import APP_VERSION  # noqa: E402,F401 — 화면 상단에 표시 (버전은 version.py에서 올린다)

HIGGSFIELD_IMAGE_MODEL = os.getenv("HIGGSFIELD_IMAGE_MODEL", "marketing-studio/image/flare").strip()
HIGGSFIELD_VIDEO_MODEL = os.getenv("HIGGSFIELD_VIDEO_MODEL", "kling-video/v2.5-turbo/pro/image-to-video").strip()  # 기획안별로 화면에서 변경 가능
# 5단계 모델 목록에서 '추천' 표시를 붙일 모델 (힉스필드 모델 ID)
RECOMMENDED_MODELS = {"marketing-studio/image/flare", "kling-video/v2.5-turbo/pro/image-to-video"}
TYPECAST_API_KEY = os.getenv("TYPECAST_API_KEY", "").strip()
TYPECAST_MODEL = os.getenv("TYPECAST_MODEL", "ssfm-v31").strip()

# 키가 있으면 항상 실제 엔진을 쓴다. 예전 .env(2026-10 배포본)에 VISUAL_ENGINE=mock / SOUND_ENGINE=system 이
# 적혀 있어, 키를 넣어도 임시 엔진(레퍼런스 화면 + 줌)으로 돌며 모델 선택 칸도 안 보이던 문제가 있었다.
# 테스트로 일부러 임시 엔진을 쓰려면 FORCE_MOCK_ENGINES=1.
_FORCE_MOCK = os.getenv("FORCE_MOCK_ENGINES", "").strip() in ("1", "true", "yes")
_sound = os.getenv("SOUND_ENGINE", "").strip().lower()
if HIGGSFIELD_API_KEY and not _FORCE_MOCK:
    VISUAL_ENGINE = "higgsfield"
else:
    VISUAL_ENGINE = "mock"
if TYPECAST_API_KEY and not _FORCE_MOCK:
    SOUND_ENGINE = "typecast"
else:
    SOUND_ENGINE = _sound if _sound in ("system", "silent") else "system"  # typecast | system | silent

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
