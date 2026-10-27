#!/usr/bin/env bash
# 더블클릭이 안 되면 터미널에서: bash 2_실행하기.command
cd "$(dirname "$0")" || exit 1

# Windows(Git Bash 등)에서 실행됐다면 Windows용 실행 파일로 넘긴다
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) echo "Windows 환경이 감지되었습니다 → 2_실행하기.bat 로 실행합니다."; exec cmd.exe //c "$(cygpath -w "$(pwd)/2_실행하기.bat")" ;;
esac

if [ ! -x .venv/bin/python ]; then
  echo "아직 설치가 되어 있지 않습니다. 먼저 1_설치하기.command 를 실행하세요."
  read -r -p "엔터를 누르면 종료합니다" _; exit 1
fi
if [ ! -f frontend/dist/index.html ]; then
  echo "화면 빌드가 없습니다. 1_설치하기.command 를 다시 실행하세요."
  read -r -p "엔터를 누르면 종료합니다" _; exit 1
fi

# 서버 실행 + 준비되면 브라우저 자동 열기 (이미 실행 중이면 브라우저만 엶)
cd backend && exec ../.venv/bin/python run.py
