"""ffmpeg 공용 도구 (기획·비주얼·사운드·합성 모듈이 함께 사용)."""
import subprocess
import wave
from pathlib import Path

import imageio_ffmpeg

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

# 비율별 작업 해상도
RESOLUTIONS = {
    "9:16": (720, 1280),
    "16:9": (1280, 720),
    "1:1": (720, 720),
    "4:5": (720, 900),
}

FPS = 30
AUDIO_RATE = 44100


def run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [FFMPEG, "-hide_banner", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=cwd,
    )


def check(args: list[str], what: str, cwd: Path | None = None) -> None:
    result = run(args, cwd)
    if result.returncode != 0:
        raise RuntimeError(f"{what} 실패: {result.stderr.strip()[-400:]}")


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as wf:
        return wf.getnframes() / float(wf.getframerate())


def silence(out: Path, seconds: float) -> None:
    check(
        ["-y", "-f", "lavfi", "-i", f"anullsrc=r={AUDIO_RATE}:cl=mono", "-t", f"{seconds:.3f}", "-c:a", "pcm_s16le", str(out)],
        "무음 생성",
    )
