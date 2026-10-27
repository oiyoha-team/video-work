@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" goto noinstall
if not exist "frontend\dist\index.html" goto nobuild

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

:nobuild
echo 화면 빌드가 없습니다. 1_설치하기.bat 을 다시 실행하세요.
pause
exit /b 1
