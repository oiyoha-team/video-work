"""타입캐스트 TTS API 클라이언트 (https://typecast.ai/docs).

- 인증: X-API-KEY 헤더
- POST /v1/text-to-speech → 오디오 바이트(wav)를 바로 돌려준다 (한 번에 최대 2,000자)
- GET /v3/voices → 목소리 목록 (성별·연령 필터, 목소리별 지원 모델·감정·미리듣기 주소)
"""
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import config

BASE = "https://api.typecast.ai"
VOICES_CACHE_SEC = 3600


class TypecastError(RuntimeError):
    pass


_ERRORS = {
    401: "타입캐스트 API 키가 올바르지 않습니다.",
    402: "타입캐스트 크레딧이 부족합니다.",
    404: "선택한 목소리를 이 모델에서 쓸 수 없습니다.",
    422: "합성할 수 없는 문자가 들어 있습니다.",
    429: "타입캐스트 요청이 너무 많습니다.",
}


def is_configured() -> bool:
    return bool(config.TYPECAST_API_KEY)


def _request(method: str, path: str, body: dict | None = None, timeout: int = 60) -> bytes:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"X-API-KEY": config.TYPECAST_API_KEY}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{BASE}{path}", data=data, method=method, headers=headers)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:300]
            if e.code in (429, 500, 502, 503) and attempt < 2:
                time.sleep(3 * (attempt + 1))
                continue
            raise TypecastError(f"{_ERRORS.get(e.code, '타입캐스트 오류')} (HTTP {e.code}) {detail}") from e
        except urllib.error.URLError as e:
            if attempt < 2:
                time.sleep(2)
                continue
            raise TypecastError(f"타입캐스트에 연결할 수 없습니다: {e.reason}") from e
    raise TypecastError("타입캐스트 요청이 반복해서 실패했습니다.")


_voices: tuple[float, list[dict]] | None = None
_voices_lock = threading.Lock()


def list_voices() -> list[dict]:
    """현재 모델(ssfm-v31)을 지원하는 목소리 전체. 1시간 캐시."""
    global _voices
    with _voices_lock:
        if _voices and time.time() - _voices[0] < VOICES_CACHE_SEC:
            return _voices[1]
    query = urllib.parse.urlencode({"model": config.TYPECAST_MODEL})
    voices = json.loads(_request("GET", f"/v3/voices?{query}"))
    with _voices_lock:
        _voices = (time.time(), voices)
    return voices


def synthesize(
    voice_id: str,
    text: str,
    out: Path,
    *,
    previous_text: str = "",
    next_text: str = "",
    tempo: float = 1.0,
    emotion: str = "smart",
    emotion_intensity: float = 1.0,
    pitch: int = 0,
) -> None:
    """문장 하나 → wav.

    emotion="smart"면 앞뒤 문장을 함께 넘겨 문맥에 맞는 억양으로 읽고,
    그 밖의 값(normal, happy, whisper, cute …)이면 그 감정 프리셋을 강도와 함께 적용한다.
    """
    if emotion == "smart":
        prompt = {"emotion_type": "smart", "previous_text": previous_text[:2000], "next_text": next_text[:2000]}
    else:
        prompt = {"emotion_type": "preset", "emotion_preset": emotion, "emotion_intensity": max(0.0, min(2.0, emotion_intensity))}
    body = {
        "voice_id": voice_id,
        "text": text,
        "model": config.TYPECAST_MODEL,
        "language": "kor",
        "prompt": prompt,
        "output": {"audio_format": "wav", "audio_tempo": max(0.5, min(2.0, tempo)), "audio_pitch": max(-12, min(12, int(pitch))), "volume": 100},
    }
    audio = _request("POST", "/v1/text-to-speech", body, timeout=120)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(audio)
