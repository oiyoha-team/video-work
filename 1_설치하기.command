#!/usr/bin/env bash
# 오이요하 퍼포먼스 영상 자동화 — Mac 스타터팩
# 필요한 프로그램이 없으면 Homebrew로 설치한 뒤 프로젝트를 준비한다.
# 더블클릭이 안 되면 터미널에서: bash 1_설치하기.command
cd "$(dirname "$0")" || exit 1
ROOT="$(pwd)"
TOTAL=7
AUTO="${1:-}"   # --auto: 질문 없이 기본값으로 진행

# ── 0. 실행 환경 판별: Windows(Git Bash 등)에서 실행됐다면 Windows용 설치로 넘긴다 ──
case "$(uname -s)" in
  Darwin) OS=mac ;;
  Linux)  OS=linux ;;
  MINGW*|MSYS*|CYGWIN*)
    echo "Windows 환경이 감지되었습니다 → 1_설치하기.bat 로 진행합니다."
    exec powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$(cygpath -w "$ROOT/scripts/install.ps1")" $([ "$AUTO" = "--auto" ] && echo -Auto) ;;
  *) echo "지원하지 않는 OS입니다: $(uname -s)"; exit 1 ;;
esac

step() { printf "\n\033[36m[%s/%s] %s\033[0m\n" "$1" "$TOTAL" "$2"; }
ok()   { printf "  \033[32m[OK]\033[0m %s\n" "$1"; }
info() { printf "   -  %s\n" "$1"; }
warn() { printf "  \033[33m[!]\033[0m %s\n" "$1"; }
fail() {
  printf "\n  \033[31m[실패] %s\033[0m\n" "$1"
  printf "  문제가 해결되지 않으면 이 창의 내용을 캡처해서 담당자에게 보내주세요.\n"
  read -r -p "엔터를 누르면 종료합니다" _
  exit 1
}
ask() {
  [ "$AUTO" = "--auto" ] && return 0
  read -r -p "$1 [Y/n] " a
  [ -z "$a" ] || [[ "$a" =~ ^[Yy] ]]
}
# version_ge 3.12 3.10 → 참 (major.minor 비교)
version_ge() { awk -v a="$1" -v b="$2" 'BEGIN { split(a, x, "."); split(b, y, "."); exit !((x[1]+0 > y[1]+0) || (x[1]+0 == y[1]+0 && x[2]+0 >= y[2]+0)) }'; }

load_brew() {
  for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do
    [ -x "$b" ] && eval "$("$b" shellenv)" && return 0
  done
  return 1
}
ensure_brew() {
  if [ "$OS" = "linux" ]; then
    fail "Linux에서는 자동 설치를 지원하지 않습니다. 먼저 설치하세요: sudo apt install python3 python3-venv nodejs npm"
  fi
  command -v brew >/dev/null 2>&1 || load_brew && return 0
  warn "Homebrew(맥 프로그램 설치 도구)가 없어 먼저 설치합니다. Mac 로그인 비밀번호를 물으면 입력하세요."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" || fail "Homebrew 설치에 실패했습니다."
  load_brew || fail "Homebrew 설치 후에도 찾을 수 없습니다. 터미널을 새로 열고 다시 실행하세요."
}

find_python() {
  for c in python3.12 python3.13 python3 "$(brew --prefix 2>/dev/null)/bin/python3.12"; do
    command -v "$c" >/dev/null 2>&1 || continue
    v=$("$c" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null) || continue
    if version_ge "$v" "3.10"; then PY="$(command -v "$c")"; PYV="$v"; return 0; fi
  done
  return 1
}

echo "========================================================"
echo "   오이요하 퍼포먼스 영상 자동화 - 스타터팩 설치"
echo "========================================================"
echo "  필요한 프로그램을 확인하고, 없으면 자동으로 설치합니다."
echo "  처음 설치는 인터넷 속도에 따라 10~20분 정도 걸릴 수 있습니다."
echo
if [ "$OS" = "mac" ]; then
  MACV=$(sw_vers -productVersion 2>/dev/null)
  case "$(uname -m)" in arm64) CHIP="Apple Silicon (M 시리즈)" ;; *) CHIP="Intel" ;; esac
  printf "  \033[36m감지된 환경: macOS %s · %s → Mac 방식(Homebrew, .command)으로 진행합니다.\033[0m\n" "$MACV" "$CHIP"
  if [ "$(sysctl -n sysctl.proc_translated 2>/dev/null)" = "1" ]; then
    warn "터미널이 Rosetta(Intel 호환 모드)로 실행 중입니다. 터미널 앱의 '정보 가져오기'에서 Rosetta 옵션을 끄면 더 빠릅니다."
  fi
  version_ge "$MACV" "12.0" || warn "macOS $MACV 는 오래된 버전이라 일부 프로그램 설치가 실패할 수 있습니다."
  # 인터넷에서 받은 파일에 붙는 격리 표시 제거 + 실행 권한 (더블클릭 실행용)
  xattr -dr com.apple.quarantine "$ROOT" 2>/dev/null || true
  chmod +x "$ROOT/1_설치하기.command" "$ROOT/2_실행하기.command" 2>/dev/null || true
else
  printf "  \033[36m감지된 환경: Linux → 이미 설치된 Python/Node.js를 사용합니다.\033[0m\n"
fi

# ── 1. 필수 프로그램 ──
step 1 "필수 프로그램 확인"
load_brew >/dev/null 2>&1
if ! find_python; then
  warn "Python 3.10 이상이 없습니다."
  ensure_brew
  info "Python 3.12 설치 중..."
  brew install python@3.12 || fail "Python 설치에 실패했습니다."
  find_python || fail "Python 설치 후에도 찾을 수 없습니다."
fi
ok "Python $PYV ($PY)"

NODEV=$(node --version 2>/dev/null | sed 's/^v//')
if [ -z "$NODEV" ] || ! version_ge "$NODEV" "18.0"; then
  if [ -n "$NODEV" ]; then warn "Node.js $NODEV 는 너무 오래된 버전입니다 (18 이상 필요)."; else warn "Node.js가 없습니다."; fi
  ensure_brew
  info "Node.js 설치 중..."
  brew install node || fail "Node.js 설치에 실패했습니다."
  NODEV=$(node --version 2>/dev/null | sed 's/^v//')
  [ -n "$NODEV" ] || fail "Node.js 설치 후에도 찾을 수 없습니다."
fi
ok "Node.js $NODEV"
ok "ffmpeg는 다음 단계에서 Python 패키지로 함께 설치됩니다"

# ── 2. 가상환경 ──
step 2 "Python 가상환경 준비"
VPY="$ROOT/.venv/bin/python"
if [ -x "$VPY" ] && ! "$VPY" -c 'import sys' >/dev/null 2>&1; then
  warn "기존 가상환경이 이 Mac에서 동작하지 않아 새로 만듭니다."
  rm -rf "$ROOT/.venv"
fi
[ -x "$VPY" ] || "$PY" -m venv "$ROOT/.venv" || fail "가상환경을 만들지 못했습니다."
ok "가상환경 (.venv)"

# ── 3. Python 패키지 ──
step 3 "Python 패키지 설치 (FastAPI, Whisper, Claude SDK, ffmpeg 등)"
"$VPY" -m pip install --upgrade pip --disable-pip-version-check -q
"$VPY" -m pip install -r "$ROOT/backend/requirements.txt" --disable-pip-version-check \
  || fail "Python 패키지 설치에 실패했습니다. 인터넷 연결을 확인한 뒤 다시 실행하세요."
ok "Python 패키지"

# ── 4. 프론트엔드 ──
step 4 "화면(프론트엔드) 빌드"
(cd "$ROOT/frontend" && npm install --no-audit --no-fund && npm run build) || fail "화면 빌드에 실패했습니다."
ok "화면 빌드 (frontend/dist)"

# ── 5. 설정 파일 ──
step 5 "설정 파일 (.env)"
[ -f "$ROOT/.env" ] || cp "$ROOT/.env.example" "$ROOT/.env"
if grep -qE '^ANTHROPIC_API_KEY=[[:space:]]*$' "$ROOT/.env"; then
  if [ "$AUTO" != "--auto" ]; then
    echo "  Claude API 키를 붙여넣고 Enter를 누르세요."
    echo "  (아직 없으면 그냥 Enter. 나중에 .env 파일에 직접 넣어도 됩니다)"
    read -r -p "  API 키: " KEY
    if [ -n "$KEY" ]; then
      KEY="$KEY" "$VPY" - "$ROOT/.env" <<'PYEOF'
import os, re, sys
path = sys.argv[1]
text = open(path, encoding="utf-8").read()
text = re.sub(r"(?m)^ANTHROPIC_API_KEY=.*$", "ANTHROPIC_API_KEY=" + os.environ["KEY"].strip(), text)
open(path, "w", encoding="utf-8").write(text)
PYEOF
      ok "API 키 저장됨"
    else
      warn "API 키 없이 진행합니다 (mock 모드). 나중에 .env 파일에 넣고 프로그램을 다시 실행하세요."
    fi
  else
    warn "API 키가 비어 있습니다 (mock 모드)."
  fi
else
  ok "API 키가 이미 설정되어 있습니다"
fi

# ── 6. 음성 인식 모델 ──
step 6 "음성 인식 모델 준비"
MODEL=$(grep -E '^WHISPER_MODEL=' "$ROOT/.env" | cut -d= -f2 | tr -d '[:space:]')
MODEL=${MODEL:-small}
if ask "  음성 인식 모델($MODEL, 약 500MB)을 지금 받아둘까요? 받지 않으면 첫 분석 때 자동으로 받습니다."; then
  info "다운로드 중... (이미 받았다면 바로 넘어갑니다)"
  if "$VPY" -c "from faster_whisper import WhisperModel; WhisperModel('$MODEL', device='cpu', compute_type='int8')"; then
    ok "음성 인식 모델 ($MODEL)"
  else
    warn "모델을 받지 못했습니다. 첫 분석 때 다시 시도합니다."
  fi
else
  info "건너뜀"
fi

# ── 7. 최종 점검 ──
step 7 "최종 점검"
"$VPY" - <<'PYEOF' || fail "점검 중 오류가 났습니다. 위 메시지를 확인하세요."
import subprocess, imageio_ffmpeg
import fastapi, uvicorn, anthropic, faster_whisper, ctranslate2
subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-version"], check=True, capture_output=True)
PYEOF
[ -f "$ROOT/frontend/dist/index.html" ] || fail "화면 빌드 결과가 없습니다."
chmod +x "$ROOT/2_실행하기.command" 2>/dev/null
ok "백엔드 · 음성 인식 · ffmpeg · 화면 모두 정상"

echo
echo "========================================================"
echo "   설치 완료!  앞으로는 '2_실행하기.command' 만 실행하면 됩니다."
echo "========================================================"
if [ "$AUTO" != "--auto" ] && ask "  지금 바로 실행할까요?"; then
  exec bash "$ROOT/2_실행하기.command"
fi
