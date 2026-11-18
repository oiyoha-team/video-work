"""힉스필드 API 클라이언트 (https://docs.higgsfield.ai).

흐름: 입력 이미지 업로드 → 생성 요청(비동기 큐) → 상태 확인(폴링) → 결과 파일 다운로드.
- 인증: Authorization: Key <키ID>:<시크릿>
- 입력 이미지는 공개 URL만 받으므로 /files/generate-upload-url 로 올린 뒤 public_url 을 넘긴다.
- 실패·nsfw·취소된 요청은 과금되지 않는다.
"""
import json
import mimetypes
import re
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import config
import media

BASE ="https://api.higgsfield.ai"
TERMINAL = {"completed", "failed", "nsfw", "canceled"}
POLL_TIMEOUT_SEC = 15 * 60


class HiggsfieldError(RuntimeError):
    pass


def is_configured() -> bool:
    return ":" in config.HIGGSFIELD_API_KEY


def _request(method: str, url: str, body: dict | None = None, headers: dict | None = None, timeout: int = 60) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    hdrs = {"Authorization": f"Key {config.HIGGSFIELD_API_KEY}", **(headers or {})}
    if data is not None:
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:400]
            # 큐가 가득 찼거나 일시 장애면 잠시 후 재시도
            if e.code in (429, 500, 502, 503) and attempt < 3:
                time.sleep(int(e.headers.get("Retry-After") or 5 * (attempt + 1)))
                continue
            msg = {401: "힉스필드 API 키가 올바르지 않습니다.", 403: "힉스필드 크레딧이 부족하거나 키가 비활성 상태입니다."}.get(e.code, "")
            raise HiggsfieldError(f"{msg} (HTTP {e.code}) {detail}".strip()) from e
        except urllib.error.URLError as e:
            if attempt < 3:
                time.sleep(3)
                continue
            raise HiggsfieldError(f"힉스필드에 연결할 수 없습니다: {e.reason}") from e
    raise HiggsfieldError("힉스필드 요청이 반복해서 실패했습니다.")


# ── 업로드 ─────────────────────────────────────────────

_upload_cache: dict[tuple[str, float], tuple[str, float]] = {}
_upload_lock = threading.Lock()
UPLOAD_REUSE_SEC = 12 * 3600  # 같은 파일은 12시간 동안 다시 올리지 않는다
SHRINK_OVER_BYTES = 3_000_000  # 이보다 큰 참고 이미지는 긴 쪽 2048px JPG로 줄여 올린다


def _shrink(path: Path) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "ref.jpg"
        media.check(["-y", "-i", str(path), "-vf", "scale='min(2048,iw)':'min(2048,ih)':force_original_aspect_ratio=decrease",
                     "-frames:v", "1", "-q:v", "2", str(out)], "참고 이미지 축소")
        return out.read_bytes()


def upload(path: Path) -> str:
    """로컬 파일을 올리고 생성 요청에 넣을 공개 URL을 돌려준다."""
    key = (str(path), path.stat().st_mtime)
    with _upload_lock:
        hit = _upload_cache.get(key)
        if hit and time.time() - hit[1] < UPLOAD_REUSE_SEC:
            return hit[0]
    content_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    data = path.read_bytes()
    if content_type.startswith("image/") and len(data) > SHRINK_OVER_BYTES:
        data, content_type = _shrink(path), "image/jpeg"
    slot = _request("POST", f"{BASE}/files/generate-upload-url", {"content_type": content_type})
    put = urllib.request.Request(slot["upload_url"], data=data, method="PUT", headers=slot.get("upload_headers") or {"Content-Type": content_type})
    with urllib.request.urlopen(put, timeout=120):
        pass
    with _upload_lock:
        _upload_cache[key] = (slot["public_url"], time.time())
    return slot["public_url"]


# ── 생성 ─────────────────────────────────────────────

def generate(endpoint: str, body: dict) -> dict:
    """생성 요청 → 완료까지 대기 → 완료 응답(dict)을 돌려준다."""
    sub = _request("POST", f"{BASE}/{endpoint}", body, headers={"Idempotency-Key": str(uuid.uuid4())})
    status_url = sub.get("status_url") or f"{BASE}/requests/{sub['request_id']}/status"
    delay, waited = 2.0, 0.0
    while waited < POLL_TIMEOUT_SEC:
        time.sleep(delay)
        waited += delay
        res = _request("GET", status_url, timeout=30)
        status = res.get("status")
        if status == "completed":
            return res
        if status in TERMINAL:
            reason = {"nsfw": "부적절한 콘텐츠로 판정되어 생성이 거부되었습니다", "canceled": "생성이 취소되었습니다"}.get(status, res.get("error") or "생성에 실패했습니다")
            raise HiggsfieldError(f"{reason} (과금되지 않음)")
        delay = min(delay * 1.5, 10.0)
    raise HiggsfieldError("생성이 15분 안에 끝나지 않았습니다. 잠시 후 다시 시도하세요.")


def download(url: str, out: Path) -> Path:
    """결과 URL은 보관 기간(기본 7일)이 지나면 사라지므로 바로 내려받아 둔다."""
    out.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=300) as r:
        out.write_bytes(r.read())
    return out


# ── 견적 ─────────────────────────────────────────────

def estimate_usd(endpoint: str, body: dict, seconds: float | None = None, resolution: str = "720p") -> float | None:
    """예상 비용(USD). 금액을 바로 주는 모델과 '초당 단가' 설명을 주는 모델이 있어 둘 다 처리한다."""
    res = _request("POST", f"{BASE}/estimate/{endpoint}", body, timeout=30)
    if res.get("usd") is not None:
        return float(res["usd"])
    text = res.get("pricing_description", "")
    m = re.search(rf"{re.escape(resolution)}:\s*\$([0-9.]+)", text, re.I)
    if m and seconds:
        return float(m.group(1)) * seconds
    return None
