"""ffmpeg 기반 영상 처리: 메타데이터 확인, 2초 구간 프레임 추출, 오디오 분리."""
import math
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from config import ASPECT_RATIOS, SEGMENT_SEC
from media import run as _run


@dataclass
class VideoInfo:
    duration: float
    width: int
    height: int
    has_audio: bool


def probe(path: Path) -> VideoInfo:
    result = _run(["-i", str(path)])  # 출력 파일이 없어 항상 실패하지만 stderr에 메타데이터가 나온다
    err = result.stderr

    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", err)
    if not m:
        raise ValueError("영상 파일을 읽을 수 없습니다.")
    duration = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))

    v = re.search(r"Stream #.*Video:.*?(\d{2,5})x(\d{2,5})", err)
    if not v:
        raise ValueError("영상 스트림을 찾을 수 없습니다.")
    width, height = int(v.group(1)), int(v.group(2))
    # 휴대폰 세로 영상은 회전 메타데이터로 저장되는 경우가 있음
    rot = re.search(r"rotation of (-?\d+(?:\.\d+)?) degrees", err) or re.search(r"rotate\s*:\s*(-?\d+)", err)
    if rot and abs(round(float(rot.group(1)))) % 180 == 90:
        width, height = height, width

    return VideoInfo(duration=duration, width=width, height=height, has_audio="Audio:" in err)


def closest_aspect_ratio(width: int, height: int) -> str:
    target = width / height
    def ratio(s: str) -> float:
        a, b = s.split(":")
        return int(a) / int(b)
    return min(ASPECT_RATIOS, key=lambda s: abs(math.log(ratio(s) / target)))


def segment_bounds(duration: float) -> list[tuple[float, float]]:
    """2초 단위 구간. 마지막 자투리가 0.5초 미만이면 앞 구간에 붙인다."""
    bounds = []
    t = 0.0
    while t < duration - 1e-6:
        bounds.append((round(t, 2), round(min(t + SEGMENT_SEC, duration), 2)))
        t += SEGMENT_SEC
    if len(bounds) > 1 and bounds[-1][1] - bounds[-1][0] < 0.5:
        last = bounds.pop()
        bounds[-1] = (bounds[-1][0], last[1])
    return bounds


def extract_frame(src: Path, t: float, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    result = _run([
        "-y", "-ss", f"{t:.3f}", "-i", str(src), "-frames:v", "1",
        "-vf", "scale=w='if(gt(iw,ih),min(960,iw),-2)':h='if(gt(iw,ih),-2,min(960,ih))'",
        "-q:v", "3", str(out),
    ])
    if result.returncode != 0 or not out.exists():
        raise RuntimeError(f"프레임 추출 실패 ({t:.1f}s): {result.stderr[-300:]}")


def extract_frames(src: Path, frames_dir: Path, bounds: list[tuple[float, float]]) -> list[Path]:
    """각 구간의 중앙 시점 프레임을 뽑는다."""
    jobs = []
    for i, (start, end) in enumerate(bounds):
        t = start + min(1.0, (end - start) / 2)
        jobs.append((t, frames_dir / f"{i:04d}.jpg"))
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda j: extract_frame(src, j[0], j[1]), jobs))
    return [out for _, out in jobs]


def extract_audio(src: Path, out: Path) -> None:
    result = _run(["-y", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000", str(out)])
    if result.returncode != 0:
        raise RuntimeError(f"오디오 추출 실패: {result.stderr[-300:]}")
