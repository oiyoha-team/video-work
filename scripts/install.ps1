# 오이요하 퍼포먼스 영상 자동화 — Windows 스타터팩
# 1_설치하기.bat 에서 실행된다. 필요한 프로그램이 없으면 winget으로 설치한 뒤 프로젝트를 준비한다.
param(
    [switch]$Auto  # 질문 없이 기본값으로 진행 (자동 테스트용)
)

$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Total = 7

# ── 0. 실행 환경 판별 ─────────────────────────────────────────────
# PowerShell 7은 Mac/Linux에서도 돌아가므로, Windows가 아니면 Mac용 스크립트로 넘긴다
if ($PSVersionTable.PSEdition -eq 'Core' -and -not $IsWindows) {
    Write-Host "Mac/Linux 환경이 감지되었습니다 → 1_설치하기.command 로 진행합니다." -ForegroundColor Cyan
    & bash (Join-Path $Root '1_설치하기.command') $(if ($Auto) { '--auto' })
    exit $LASTEXITCODE
}

function Step($n, $msg) { Write-Host ""; Write-Host "[$n/$Total] $msg" -ForegroundColor Cyan }
function Ok($msg) { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Info($msg) { Write-Host "   -  $msg" }
function Warn($msg) { Write-Host "  [!] $msg" -ForegroundColor Yellow }
function Fail($msg) {
    Write-Host ""
    Write-Host "  [실패] $msg" -ForegroundColor Red
    Write-Host "  문제가 해결되지 않으면 이 창의 내용을 캡처해서 담당자에게 보내주세요." -ForegroundColor Red
    exit 1
}

function Ask($question) {
    if ($Auto) { return $true }
    $answer = Read-Host "$question [Y/n]"
    return ($answer -eq '' -or $answer -match '^[Yy]')
}

function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
}

function Install-Winget($id, $name, [string[]]$extra = @()) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Fail "$name 을(를) 자동 설치하려면 'winget(앱 설치 관리자)'이 필요합니다. Microsoft Store에서 '앱 설치 관리자'를 설치한 뒤 다시 실행하거나, $name 을(를) 직접 설치하세요."
    }
    Info "$name 설치 중... (설치 창이나 관리자 권한 요청이 뜨면 '예'를 눌러주세요)"
    & winget install -e --id $id --accept-package-agreements --accept-source-agreements --silent @extra
    Refresh-Path
}

# ── 프로그램 찾기 ─────────────────────────────────────────────

function Find-Python {
    $candidates = @(
        'py -3.12', 'py -3.13', 'py -3', 'python', 'python3',
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe"
    )
    foreach ($c in $candidates) {
        $parts = $c -split ' (?=-)'
        $exe = $parts[0]
        $pre = @($parts | Select-Object -Skip 1)
        if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
        # Microsoft Store의 가짜 python.exe는 실행에 실패하므로 자연스럽게 걸러진다
        $out = & $exe @pre -c "import sys; print(sys.executable); print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $out) { continue }
        $lines = @($out)
        $ver = [version]$lines[1]
        if ($ver -ge [version]'3.10') { return @{ Exe = $lines[0]; Version = $ver } }
    }
    return $null
}

function Find-Node {
    if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
        if (Test-Path "$env:ProgramFiles\nodejs\node.exe") { $env:Path += ";$env:ProgramFiles\nodejs" } else { return $null }
    }
    $v = & node --version 2>$null
    if ($LASTEXITCODE -eq 0 -and "$v" -match 'v(\d+)\.(\d+)') { return [version]"$($Matches[1]).$($Matches[2])" }
    return $null
}

function Test-VCRedist {
    foreach ($k in 'HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64',
                   'HKLM:\SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\x64') {
        $p = Get-ItemProperty $k -ErrorAction SilentlyContinue
        if ($p -and $p.Installed -eq 1) { return $true }
    }
    return $false
}

Write-Host "========================================================" -ForegroundColor Green
Write-Host "   오이요하 퍼포먼스 영상 자동화 - 스타터팩 설치" -ForegroundColor Green
Write-Host "========================================================" -ForegroundColor Green
Write-Host "  필요한 프로그램을 확인하고, 없으면 자동으로 설치합니다."
Write-Host "  처음 설치는 인터넷 속도에 따라 10~20분 정도 걸릴 수 있습니다."

$osName = (Get-CimInstance Win32_OperatingSystem -ErrorAction SilentlyContinue).Caption
$arch = $env:PROCESSOR_ARCHITECTURE
Write-Host ""
Write-Host "  감지된 환경: $osName ($arch) → Windows 방식(winget, .bat)으로 진행합니다." -ForegroundColor Cyan
if ($arch -eq 'ARM64') {
    Warn "ARM 기반 Windows입니다. 음성 인식 패키지가 설치되지 않을 수 있습니다. 문제가 생기면 x64 Python을 설치해 주세요."
}

# ── 1. 필수 프로그램 ─────────────────────────────────────────────
Step 1 "필수 프로그램 확인"

$py = Find-Python
if (-not $py) {
    Warn "Python 3.10 이상이 없습니다."
    Install-Winget 'Python.Python.3.12' 'Python 3.12' @('--scope', 'user')
    $py = Find-Python
    if (-not $py) { Fail "Python 설치 후에도 찾을 수 없습니다. 이 창을 닫고 1_설치하기.bat 을 다시 실행해 보세요. 그래도 안 되면 https://www.python.org/downloads/ 에서 직접 설치하세요." }
}
Ok "Python $($py.Version)  ($($py.Exe))"

$node = Find-Node
if (-not $node -or $node -lt [version]'18.0') {
    if ($node) { Warn "Node.js $node 는 너무 오래된 버전입니다 (18 이상 필요)." } else { Warn "Node.js가 없습니다." }
    Install-Winget 'OpenJS.NodeJS.LTS' 'Node.js LTS'
    $node = Find-Node
    if (-not $node -or $node -lt [version]'18.0') { Fail "Node.js 설치 후에도 찾을 수 없습니다. 이 창을 닫고 다시 실행하거나, https://nodejs.org 에서 LTS 버전을 직접 설치하세요." }
}
Ok "Node.js $node"

if (-not (Test-VCRedist)) {
    Warn "Visual C++ 런타임이 없습니다 (음성 인식에 필요)."
    Install-Winget 'Microsoft.VCRedist.2015+.x64' 'Visual C++ 런타임'
    if (-not (Test-VCRedist)) { Warn "Visual C++ 런타임 설치를 확인하지 못했습니다. 마지막 점검에서 음성 인식 오류가 나면 https://aka.ms/vs/17/release/vc_redist.x64.exe 를 직접 설치하세요." }
    else { Ok "Visual C++ 런타임 설치됨" }
} else {
    Ok "Visual C++ 런타임"
}
Ok "ffmpeg는 다음 단계에서 Python 패키지로 함께 설치됩니다"

# ── 2. 가상환경 ─────────────────────────────────────────────
Step 2 "Python 가상환경 준비"
$VenvPy = Join-Path $Root '.venv\Scripts\python.exe'
if (Test-Path $VenvPy) {
    # 다른 PC에서 복사해 온 .venv는 동작하지 않으므로 확인 후 다시 만든다
    $v = & $VenvPy -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
    if ($LASTEXITCODE -ne 0 -or [version]"$v" -lt [version]'3.10') {
        Warn "기존 가상환경이 이 PC에서 동작하지 않아 새로 만듭니다."
        Remove-Item (Join-Path $Root '.venv') -Recurse -Force
    }
}
if (-not (Test-Path $VenvPy)) {
    & $py.Exe -m venv (Join-Path $Root '.venv')
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $VenvPy)) { Fail "가상환경을 만들지 못했습니다." }
}
Ok "가상환경 (.venv)"

# ── 3. Python 패키지 ─────────────────────────────────────────────
Step 3 "Python 패키지 설치 (FastAPI, Whisper, Claude SDK, ffmpeg 등)"
& $VenvPy -m pip install --upgrade pip --disable-pip-version-check -q
& $VenvPy -m pip install -r (Join-Path $Root 'backend\requirements.txt') --disable-pip-version-check
if ($LASTEXITCODE -ne 0) { Fail "Python 패키지 설치에 실패했습니다. 인터넷 연결을 확인한 뒤 다시 실행하세요." }
Ok "Python 패키지"

# ── 4. 프론트엔드 ─────────────────────────────────────────────
Step 4 "화면(프론트엔드) 빌드"
Push-Location (Join-Path $Root 'frontend')
& npm.cmd install --no-audit --no-fund
if ($LASTEXITCODE -ne 0) { Pop-Location; Fail "npm 패키지 설치에 실패했습니다. 인터넷 연결을 확인한 뒤 다시 실행하세요." }
& npm.cmd run build
if ($LASTEXITCODE -ne 0) { Pop-Location; Fail "화면 빌드에 실패했습니다." }
Pop-Location
Ok "화면 빌드 (frontend\dist)"

# ── 5. 설정 파일 ─────────────────────────────────────────────
Step 5 "설정 파일 (.env)"
$EnvFile = Join-Path $Root '.env'
if (-not (Test-Path $EnvFile)) { Copy-Item (Join-Path $Root '.env.example') $EnvFile }
$envText = [IO.File]::ReadAllText($EnvFile)
if ($envText -match '(?m)^ANTHROPIC_API_KEY=\s*$') {
    if (-not $Auto) {
        Write-Host "  Claude API 키를 붙여넣고 Enter를 누르세요."
        Write-Host "  (아직 없으면 그냥 Enter. 나중에 .env 파일에 직접 넣어도 됩니다)"
        $key = (Read-Host "  API 키").Trim()
        if ($key) {
            $envText = $envText -replace '(?m)^ANTHROPIC_API_KEY=.*$', "ANTHROPIC_API_KEY=$key"
            [IO.File]::WriteAllText($EnvFile, $envText, (New-Object Text.UTF8Encoding $false))
            Ok "API 키 저장됨"
        } else {
            Warn "API 키 없이 진행합니다 (mock 모드). 나중에 .env 파일에 넣고 프로그램을 다시 실행하세요."
        }
    } else {
        Warn "API 키가 비어 있습니다 (mock 모드)."
    }
} else {
    Ok "API 키가 이미 설정되어 있습니다"
}

# 워크스페이스에 묶이지 않은 키(sk-ant-usr-…)는 워크스페이스 ID도 있어야 동작한다
if ($envText -match '(?m)^ANTHROPIC_API_KEY=sk-ant-usr-' -and $envText -notmatch '(?m)^ANTHROPIC_WORKSPACE_ID=wrkspc_') {
    if (-not $Auto) {
        Write-Host "  이 API 키는 워크스페이스 ID(wrkspc_ 로 시작)가 함께 있어야 합니다."
        $ws = (Read-Host "  워크스페이스 ID").Trim()
        if ($ws) {
            if ($envText -match '(?m)^ANTHROPIC_WORKSPACE_ID=') {
                $envText = $envText -replace '(?m)^ANTHROPIC_WORKSPACE_ID=.*$', "ANTHROPIC_WORKSPACE_ID=$ws"
            } else {
                $envText = $envText.TrimEnd() + "`nANTHROPIC_WORKSPACE_ID=$ws`n"
            }
            [IO.File]::WriteAllText($EnvFile, $envText, (New-Object Text.UTF8Encoding $false))
            Ok "워크스페이스 ID 저장됨"
        } else {
            Warn "워크스페이스 ID가 없으면 Claude 기능이 동작하지 않습니다. 나중에 .env의 ANTHROPIC_WORKSPACE_ID에 넣어 주세요."
        }
    } else {
        Warn "워크스페이스 ID가 비어 있습니다."
    }
}

# ── 6. 음성 인식 모델 ─────────────────────────────────────────────
Step 6 "음성 인식 모델 준비"
$model = 'small'
if ($envText -match '(?m)^WHISPER_MODEL=(\S+)') { $model = $Matches[1] }
if (Ask "  음성 인식 모델($model, 약 500MB)을 지금 받아둘까요? 받지 않으면 첫 분석 때 자동으로 받습니다.") {
    Info "다운로드 중... (이미 받았다면 바로 넘어갑니다)"
    & $VenvPy -c "from faster_whisper import WhisperModel; WhisperModel('$model', device='cpu', compute_type='int8')"
    if ($LASTEXITCODE -eq 0) { Ok "음성 인식 모델 ($model)" } else { Warn "모델을 받지 못했습니다. 첫 분석 때 다시 시도합니다." }
} else {
    Info "건너뜀"
}

# ── 7. 최종 점검 ─────────────────────────────────────────────
Step 7 "최종 점검"
# 주의: Windows PowerShell 5.1은 외부 프로그램 인자의 큰따옴표를 지우므로 Python 코드에는 작은따옴표만 쓴다
$check = @'
import subprocess, imageio_ffmpeg
import fastapi, uvicorn, anthropic, faster_whisper, ctranslate2
subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-version'], check=True, capture_output=True)
'@
& $VenvPy -c $check
if ($LASTEXITCODE -ne 0) { Fail "점검 중 오류가 났습니다. 위 메시지를 확인하세요. (DLL 오류라면 Visual C++ 런타임을 설치하세요: https://aka.ms/vs/17/release/vc_redist.x64.exe)" }
if (-not (Test-Path (Join-Path $Root 'frontend\dist\index.html'))) { Fail "화면 빌드 결과가 없습니다." }
Ok "백엔드 · 음성 인식 · ffmpeg · 화면 모두 정상"

Write-Host ""
Write-Host "========================================================" -ForegroundColor Green
Write-Host "   설치 완료!  앞으로는 '2_실행하기.bat' 만 실행하면 됩니다." -ForegroundColor Green
Write-Host "========================================================" -ForegroundColor Green

if (-not $Auto -and (Ask "  지금 바로 실행할까요?")) {
    Start-Process -FilePath (Join-Path $Root '2_실행하기.bat') -WorkingDirectory $Root
}
exit 0
