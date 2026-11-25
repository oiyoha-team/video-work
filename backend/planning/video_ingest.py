"""ffmpeg 기반 영상 처리: 메타데이터 확인, 1초 구간 프레임 추출, 화면 전환(컷) 감지, 오디오 분리."""
import math
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from config import ASPECT_RATIOS, CUT_SCENE_THRESHOLD, MAX_CUT_SEC, SEGMENT_SEC
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
    """SEGMENT_SEC(1초) 단위 구간. 마지막 자투리가 0.5초 미만이면 앞 구간에 붙인다."""
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


# ── 컷(화면 전환) ─────────────────────────────────────────────

MIN_CUT_SEC = 0.4  # 이보다 짧은 컷은 앞뒤 컷에 붙인다 (전환 효과·깜빡임)


def detect_cuts(src: Path, threshold: float = CUT_SCENE_THRESHOLD) -> list[float]:
    """화면이 확 바뀌는 시점(초) 목록. ffmpeg의 장면 변화 점수가 threshold를 넘는 프레임."""
    result = _run(["-i", str(src), "-vf", f"select='gt(scene,{threshold})',showinfo", "-an", "-f", "null", "-"])
    times = sorted({round(float(m.group(1)), 2) for m in re.finditer(r"pts_time:(\d+(?:\.\d+)?)", result.stderr)})
    return [t for t in times if t > 0]


def plan_cuts(start: float, end: float, cut_times: list[float], max_len: float = MAX_CUT_SEC) -> list[tuple[float, float, bool]]:
    """구간 [start, end]를 컷으로 나눈다 → [(시작, 끝, 길이 때문에 나눔)].

    1. 화면 전환 시점에서 나눈다 (너무 짧은 컷은 붙인다).
    2. max_len이 있으면(0이 아니면) 그보다 긴 컷을 같은 길이로 다시 나눈다. 기본은 나누지 않는다
       (화면이 바뀌지 않으면 3초든 5초든 한 컷 → 같은 장면을 중복으로 만들지 않는다).
    """
    edges = [start] + [t for t in cut_times if start + MIN_CUT_SEC <= t <= end - MIN_CUT_SEC] + [end]
    shots: list[tuple[float, float]] = []
    for a, b in zip(edges, edges[1:]):
        if shots and b - a < MIN_CUT_SEC:
            shots[-1] = (shots[-1][0], b)
        else:
            shots.append((a, b))
    out: list[tuple[float, float, bool]] = []
    for a, b in shots:
        n = max(1, math.ceil((b - a) / max_len - 1e-6)) if max_len else 1
        step = (b - a) / n
        for k in range(n):
            out.append((round(a + k * step, 2), round(a + (k + 1) * step if k < n - 1 else b, 2), k > 0))
    return out


def has_cut_at(t: float, cut_times: list[float], tol: float = 0.15) -> bool:
    """t 시점에 화면이 바뀌는지 (구간 경계에서 같은 샷이 이어지는지 판단)."""
    return any(abs(c - t) <= tol for c in cut_times)


def extract_cut_frames(src: Path, frames_dir: Path, cuts: list[tuple[int, int, float]]) -> None:
    """[(구간 번호, 컷 번호, 시점)] 마다 프레임 한 장 (frames/cut_구간_컷.jpg)."""
    jobs = [(t, frames_dir / f"cut_{seg:04d}_{k}.jpg") for seg, k, t in cuts]
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda j: extract_frame(src, j[0], j[1]), jobs))
