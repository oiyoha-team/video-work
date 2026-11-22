"""작업별 소요 시간 기록 → 화면의 '남은 시간' 계산.

실제로 걸린 시간을 작업 종류·모델별로 최근 20번까지 기록해 두고(data/cache/timings.json),
남은 시간을 '최소~최대' 범위로 계산한다. 기록이 없으면 기본 범위를 쓴다.
"""
import json
import math
import threading
import time

import config

PATH = config.DATA_DIR / "cache" / "timings.json"
KEEP = 20
_lock = threading.Lock()

# 기록이 없을 때 쓰는 한 건당 소요 시간 범위 (초)
DEFAULTS = {
    "briefs": (30, 120),  # Claude 장면 설계 (전체)
    "revise": (5, 20),  # Claude 수정 지시 반영 (장면 하나)
    "image": (30, 120),
    "portrait": (30, 120),
    "video": (60, 300),
    "line": (2, 8),  # TTS 문장 하나
}


def _load() -> dict:
    try:
        return json.loads(PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _key(kind: str, model: str = "") -> str:
    return f"{kind}:{model}" if model else kind


def _real_engine(kind: str) -> bool:
    """임시 엔진(키 없음·테스트)의 짧은 시간이 실제 예상 시간을 망치지 않게 실제 엔진일 때만 기록한다."""
    if kind in ("image", "video", "portrait"):
        return config.VISUAL_ENGINE == "higgsfield"
    if kind == "line":
        return config.SOUND_ENGINE == "typecast"
    return True


def record(kind: str, seconds: float, model: str = "") -> None:
    if not _real_engine(kind):
        return
    with _lock:
        data = _load()
        for k in {_key(kind, model), kind}:
            data[k] = (data.get(k, []) + [round(seconds, 1)])[-KEEP:]
        PATH.parent.mkdir(parents=True, exist_ok=True)
        PATH.write_text(json.dumps(data), encoding="utf-8")


def typical(kind: str, model: str = "") -> tuple[float, float]:
    """한 건당 (짧게, 길게) 걸리는 시간. 최근 기록의 하위 20%~상위 20% 범위."""
    data = _load()
    samples = sorted(data.get(_key(kind, model)) or data.get(kind) or [])
    if len(samples) < 2:
        lo, hi = DEFAULTS.get(kind, (10, 60))
        if samples:  # 한 번만 기록됐으면 그 값을 중심으로
            lo, hi = samples[0] * 0.7, samples[0] * 1.5
        return lo, hi
    lo = samples[int(len(samples) * 0.2)]
    hi = samples[min(len(samples) - 1, math.ceil(len(samples) * 0.8))]
    return lo * 0.9, max(hi * 1.15, lo * 1.3)


def remaining(kind: str, count: int, parallel: int = 1, model: str = "") -> tuple[float, float]:
    """count건을 parallel개씩 동시에 돌릴 때 남은 시간 범위."""
    if count <= 0:
        return 0.0, 0.0
    lo, hi = typical(kind, model)
    rounds = math.ceil(count / max(1, parallel))
    return lo * rounds, hi * rounds


class Timer:
    def __init__(self) -> None:
        self.t0 = time.time()

    @property
    def seconds(self) -> float:
        return time.time() - self.t0
