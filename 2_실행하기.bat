@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" goto noinstall
rem 화면 빌드가 없거나 오래됐으면 run.py가 실행 전에 다시 만든다 (새 버전 ZIP을 덮어쓴 경우)
cd backend
"..\.venv\Scripts\python.exe" run.py
echo.
echo 프로그램이 종료되었습니다.
pause
exit /b 0

:noinstall
echo 아직 설치가 되어 있지 않습니다. 먼저 1_설치하기.bat 을 실행하세요.
pause
exit /b 1
