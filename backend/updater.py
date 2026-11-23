"""실행 전 자동 업데이트 반영 (2_실행하기 → run.py가 서버를 띄우기 전에 부른다).

새 버전 ZIP을 받아 기존 폴더에 덮어쓰고 [2_실행하기]만 눌러도 최신 상태로 돌도록:
1. .env에 새로 생긴 설정 칸을 .env.example에서 채운다 (기존 값은 건드리지 않음)
2. 비어 있는 필수 API 키(힉스필드·타입캐스트 등)를 물어본다 (Enter로 건너뛰기)
3. requirements.txt가 바뀌었으면 Python 패키지를 설치한다
4. 화면 소스가 바뀌었으면 npm install / npm run build 로 화면을 다시 만든다

바뀌었는지는 파일 내용 해시를 기록해 두고(.venv/.requirements.sha, frontend/dist/.build.sha) 비교한다.
직접 실행: python updater.py --mark   (설치 직후 '지금 상태가 최신'이라고 기록)
          python updater.py --keys   (비어 있는 API 키만 물어봄)
"""
import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV, ENV_EXAMPLE = ROOT / ".env", ROOT / ".env.example"
REQUIREMENTS = ROOT / "backend" / "requirements.txt"
FRONTEND = ROOT / "frontend"
DIST = FRONTEND / "dist"
REQ_STAMP = ROOT / ".venv" / ".requirements.sha"
DEPS_STAMP = FRONTEND / "node_modules" / ".deps.sha"
BUILD_STAMP = DIST / ".build.sha"

# 기본값이 바뀐 설정: .env에 예전 기본값이 그대로 있으면 .env.example의 새 기본값으로 바꾼다
OLD_DEFAULTS = {"HIGGSFIELD_VIDEO_MODEL": "wan/v2.7/image-to-video"}

# 비어 있으면 실행할 때 물어볼 키: (이름, 설명)
KEYS = [
    ("HIGGSFIELD_API_KEY", "힉스필드 API 키 (이미지·영상 생성, '키ID:시크릿' 형식)"),
    ("TYPECAST_API_KEY", "타입캐스트 API 키 (TTS 음성)"),
]


def _say(msg: str) -> None:
    print(f"  · {msg}", flush=True)


def _sha(paths: list[Path]) -> str:
    h = hashlib.sha256()
    for p in sorted(paths):
        if p.is_file():
            h.update(str(p.relative_to(ROOT)).replace("\\", "/").encode())
            h.update(p.read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()


def _frontend_sources() -> list[Path]:
    files = [p for p in (FRONTEND / "src").rglob("*") if p.is_file()]
    for name in ("index.html", "package.json", "package-lock.json", "vite.config.ts", "tsconfig.json"):
        files.append(FRONTEND / name)
    return files


def _deps_files() -> list[Path]:
    return [FRONTEND / "package.json", FRONTEND / "package-lock.json"]


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


# ── 1. .env 새 설정 칸 채우기 ─────────────────────────────────────────────

def sync_env() -> list[str]:
    """.env.example에는 있는데 .env에 없는 설정을 (설명 주석과 함께) 뒤에 붙인다."""
    if not ENV_EXAMPLE.exists():
        return []
    if not ENV.exists():
        shutil.copy(ENV_EXAMPLE, ENV)
        return []
    env = _read(ENV)
    have = set(re.findall(r"(?m)^([A-Z][A-Z0-9_]*)=", env))
    added, block, comments = [], [], []
    for line in _read(ENV_EXAMPLE).splitlines():
        m = re.match(r"^([A-Z][A-Z0-9_]*)=", line)
        if m and m.group(1) not in have:
            block += comments + [line]
            added.append(m.group(1))
        comments = comments + [line] if line.startswith("#") else []
    # 예전 배포본(2026-10)의 임시 엔진 고정 설정을 비운다 → 키 유무로 자동 선택
    cleaned = re.sub(r"(?m)^(VISUAL_ENGINE)=\s*mock\s*$", r"\1=", env)
    cleaned = re.sub(r"(?m)^(SOUND_ENGINE)=\s*system\s*$", r"\1=", cleaned)
    # 예전 기본 영상 모델(Wan 2.7)이 그대로 적혀 있으면 새 기본값으로 (사용자가 직접 바꾼 값은 건드리지 않음)
    for key, old_default in OLD_DEFAULTS.items():
        new_default = _env_value(_read(ENV_EXAMPLE), key)
        if new_default:
            cleaned = re.sub(rf"(?m)^{key}=\s*{re.escape(old_default)}\s*$", f"{key}={new_default}", cleaned)
    if cleaned != env:
        env = cleaned
        _write(ENV, env)
        _say("예전 설정을 새 버전에 맞게 정리했습니다 (임시 엔진 고정 해제 · 바뀐 기본 모델 반영)")
    if added:
        _write(ENV, env.rstrip("\n") + "\n\n# ── 업데이트로 추가된 설정 ──\n" + "\n".join(block) + "\n")
    return added


# ── 2. 비어 있는 API 키 묻기 ─────────────────────────────────────────────

def _env_value(text: str, key: str) -> str:
    m = re.search(rf"(?m)^{key}=(.*)$", text)
    return m.group(1).strip() if m else ""


def ask_missing_keys() -> None:
    if not sys.stdin or not sys.stdin.isatty():
        return
    text = _read(ENV)
    missing = [(k, d) for k, d in KEYS if not _env_value(text, k)]
    if not missing:
        return
    print("\n  [API 키 설정] 아래 키가 비어 있어 해당 기능이 임시 엔진으로 동작합니다.")
    print("  키를 붙여넣고 Enter (지금 없으면 그냥 Enter로 건너뛰기)", flush=True)
    for key, desc in missing:
        try:
            value = input(f"  - {desc}: ").strip()
        except EOFError:
            return
        if not value:
            continue
        if re.search(rf"(?m)^{key}=", text):
            text = re.sub(rf"(?m)^{key}=.*$", lambda _m: f"{key}={value}", text)
        else:
            text = text.rstrip("\n") + f"\n{key}={value}\n"
        _write(ENV, text)
        _say(f"{key} 저장됨")
    print(flush=True)


# ── 3·4. 패키지 · 화면 ─────────────────────────────────────────────

def _run(cmd: list[str], cwd: Path, what: str) -> bool:
    _say(f"{what} 중… (몇 분 걸릴 수 있습니다)")
    try:
        ok = subprocess.run(cmd, cwd=cwd).returncode == 0
    except OSError as e:
        print(f"  ! {what} 실패: {e}", flush=True)
        return False
    if not ok:
        print(f"  ! {what}에 실패했습니다. 1_설치하기를 다시 실행해 주세요.", flush=True)
    return ok


def _npm() -> str | None:
    return shutil.which("npm.cmd" if os.name == "nt" else "npm")


def update_python() -> None:
    want = _sha([REQUIREMENTS])
    if _read(REQ_STAMP).strip() == want:
        return
    if _run([sys.executable, "-m", "pip", "install", "-r", str(REQUIREMENTS), "--disable-pip-version-check", "-q"], ROOT, "새 Python 패키지 설치"):
        _write(REQ_STAMP, want)


def update_frontend() -> None:
    want = _sha(_frontend_sources())
    if (DIST / "index.html").exists() and _read(BUILD_STAMP).strip() == want:
        return
    npm = _npm()
    if not npm:
        print("  ! 화면을 새로 만들려면 Node.js가 필요합니다. 1_설치하기를 다시 실행해 주세요.", flush=True)
        return
    deps = _sha(_deps_files())
    if not (FRONTEND / "node_modules").exists() or _read(DEPS_STAMP).strip() != deps:
        if not _run([npm, "install", "--no-audit", "--no-fund"], FRONTEND, "화면 패키지 설치"):
            return
        _write(DEPS_STAMP, deps)
    if _run([npm, "run", "build"], FRONTEND, "새 버전 화면 만들기"):
        _write(BUILD_STAMP, want)


def mark_current() -> None:
    """설치 스크립트가 방금 설치·빌드했을 때: 지금 상태를 최신으로 기록 (다음 실행 때 다시 빌드하지 않게)."""
    if REQ_STAMP.parent.exists():
        _write(REQ_STAMP, _sha([REQUIREMENTS]))
    if (FRONTEND / "node_modules").exists():
        _write(DEPS_STAMP, _sha(_deps_files()))
    if (DIST / "index.html").exists():
        _write(BUILD_STAMP, _sha(_frontend_sources()))


def run_all() -> None:
    added = sync_env()
    if added:
        _say(f"새 설정 {len(added)}개를 .env에 추가했습니다: {', '.join(added)}")
    ask_missing_keys()
    update_python()
    update_frontend()


if __name__ == "__main__":
    if "--mark" in sys.argv:
        mark_current()
    elif "--keys" in sys.argv:
        sync_env()
        ask_missing_keys()
    else:
        run_all()
