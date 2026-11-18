"""힉스필드 모델 카탈로그: 이미지·영상 모델 목록을 12시간마다 자동으로 갱신한다.

- GET /models?include_schema=true 로 전체 모델과 모델별 입력값(JSON 스키마)을 받는다.
- 스키마를 보고 이 앱에서 쓸 수 있는 모델만 고른다.
  - 이미지: 프롬프트 + 참고 이미지(image_urls 또는 image_url)를 받는 모델
  - 영상: 이미지 한 장으로 시작하는 image-to-video 모델
- 모델마다 요청 본문(비율·해상도·길이·소리 끔)을 스키마에서 자동으로 맞추므로 새 모델도 바로 쓸 수 있다.
- 가격은 견적 API(/estimate)로 모델마다 확인해 둔다.
- 결과는 data/cache/higgsfield_models.json에 저장해 두고, 서버를 다시 켜도 그대로 쓴다.
"""
import json
import math
import re
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import config

from . import higgsfield

REFRESH_SEC = 12 * 3600
CACHE = config.DATA_DIR / "cache" / "higgsfield_models.json"
# 참고 이미지가 너무 많으면 생성이 실패한다 (Grok Image 2.0 실측: 5장까지 성공, 6장부터 'Generation failed').
REF_IMAGE_LIMIT = 5
_SAMPLE_IMG = "https://example.com/sample.jpg"  # 견적 요청용 (실제로 내려받지 않음)
_SAMPLE_PROMPT = "A product photo of a bottle on a wooden table in soft daylight."  # 너무 짧으면 견적을 거부하는 모델이 있다

_lock = threading.Lock()
_refreshing = threading.Event()
_catalog: dict | None = None


# ── 스키마 → 모델 규격 ─────────────────────────────────────────────

def _enum(props: dict, key: str) -> list:
    return list(props.get(key, {}).get("enum") or [])


def _pick(options: list, *prefer):
    return next((p for p in prefer if p in options), None)


# ── 화질: 모든 이미지·영상은 1080p 이상 ─────────────────────────────────────────────
# 해상도 표기 → 대략의 세로(짧은 쪽) 픽셀. 이미지의 1k는 긴 쪽 약 1024px라 9:16에서 1080p에 못 미친다.
_RES_PX = {"360p": 360, "480p": 480, "540p": 540, "720p": 720, "768p": 768, "1k": 1024, "1080p": 1080,
           "1440p": 1440, "2k": 2048, "4k": 2160}
MIN_PX = 1080


def _res_px(label: str | None) -> int:
    return _RES_PX.get((label or "").strip().lower(), 0)


def _hd_choice(options: list) -> str | None:
    """1080p 이상 중 가장 낮은 것 (불필요하게 비싼 4K는 피한다)."""
    ok = [o for o in options if _res_px(o) >= MIN_PX]
    return min(ok, key=_res_px) if ok else None


def _real_name(item: dict) -> str:
    """'Marketing Studio Image'처럼 묶음 이름만 있는 모델은 설명에 적힌 실제 모델 이름을 쓴다 (예: GPT Image 2.5 Flare)."""
    m = re.search(r" with ((?:GPT|Gemini|Imagen|Nano)[\w .-]*?)\.?$", item.get("description") or "", re.I)
    return m.group(1).strip() if m else ""


def _image_spec(item: dict) -> dict | None:
    sc = item.get("input_schema") or {}
    props = sc.get("properties") or {}
    if item.get("output_type") != "image" or item.get("is_workflow") or "prompt" not in props:
        return None
    if "image_urls" in props:
        field, max_images = "image_urls", min(props["image_urls"].get("maxItems") or REF_IMAGE_LIMIT, REF_IMAGE_LIMIT)
    elif "image_url" in props:
        field, max_images = "image_url", 1
    else:
        return None  # 참고 이미지를 못 받는 모델은 제품 외형을 재현할 수 없어 뺀다
    if set(sc.get("required") or []) - {"prompt", field}:
        return None
    return {
        "id": item["slug"], "kind": "image", "title": _real_name(item) or item.get("title") or item["slug"],
        "image_field": field, "max_images": max_images,
        "aspects": _enum(props, "aspect_ratio"),
        "resolution": _hd_choice(_enum(props, "resolution")),  # 화질을 고를 수 없거나 1080p 미만뿐이면 None → 목록에서 뺀다
        "quality": _pick(_enum(props, "quality"), "medium"),
        "usd": None,
    }


def _video_spec(item: dict) -> dict | None:
    sc = item.get("input_schema") or {}
    props = sc.get("properties") or {}
    if item.get("output_type") != "video" or item.get("is_workflow") or not item["slug"].endswith("image-to-video") or "image_url" not in props:
        return None
    if set(sc.get("required") or []) - {"prompt", "image_url"}:
        return None
    dur = props.get("duration") or {}
    extra: dict = {}
    if "off" in _enum(props, "sound"):
        extra["sound"] = "off"  # 음성은 TTS로 따로 만든다
    if "generate_audio" in props:
        extra["generate_audio"] = False
    options = _enum(props, "resolution")
    res = _hd_choice(options)
    if res:
        extra["resolution"] = res
    elif options:
        return None  # 1080p를 낼 수 없는 모델 (예: 720p 전용)
    return {
        "id": item["slug"], "kind": "video", "title": item.get("title") or item["slug"],
        "dur_enum": sorted(int(x) for x in dur.get("enum") or []),
        "dur_min": int(dur.get("minimum") or 1), "dur_max": int(dur.get("maximum") or 15),
        "aspects": _enum(props, "aspect_ratio"),
        "resolution": res, "extra": extra, "usd_per_sec": None,
    }


def _labels(specs: list[dict]) -> None:
    """같은 이름(title)이 여러 개면 경로의 구분 단어를 붙인다 (예: Kling 3.0 · pro)."""
    count: dict[str, int] = {}
    for s in specs:
        count[s["title"]] = count.get(s["title"], 0) + 1
    for s in specs:
        parts = [p for p in s["id"].split("/") if p not in ("image-to-video",)]
        s["label"] = s["title"] if count[s["title"]] == 1 else f"{s['title']} · {parts[-1]}"


# ── 요청 본문 ─────────────────────────────────────────────

def aspect_for(spec: dict, aspect: str) -> str | None:
    """프로젝트 비율에 가장 맞는 모델 비율. 정확히 없으면 auto/adaptive 또는 가까운 비율 (이미지는 나중에 잘라 맞춘다)."""
    options = spec.get("aspects") or []
    if not options:
        return None
    if aspect in options:
        return aspect
    fallback = {"4:5": ["3:4", "2:3"], "9:16": ["2:3", "3:4"], "16:9": ["3:2", "4:3"], "1:1": []}.get(aspect, [])
    return _pick(options, *fallback, "auto", "adaptive")


def clip_seconds(spec: dict, scene_len: float) -> int:
    """장면 길이를 모델이 허용하는 정수 초로 맞춘다 (짧으면 최소 길이로, 편집 때 잘라 쓰면 됨)."""
    need = max(1, math.ceil(scene_len - 0.05))
    if spec["dur_enum"]:
        return next((d for d in spec["dur_enum"] if d >= need), spec["dur_enum"][-1])
    return max(spec["dur_min"], min(spec["dur_max"], need))


def image_body(spec: dict, prompt: str, urls: list[str], aspect: str) -> dict:
    body: dict = {"prompt": prompt}
    if urls:
        body[spec["image_field"]] = urls[: spec["max_images"]] if spec["image_field"] == "image_urls" else urls[0]
    if a := aspect_for(spec, aspect):
        body["aspect_ratio"] = a
    if spec.get("resolution"):
        body["resolution"] = spec["resolution"]
    if spec.get("quality"):
        body["quality"] = spec["quality"]
    return body


def video_body(spec: dict, image_url: str, prompt: str, seconds: int, aspect: str) -> dict:
    body = {"image_url": image_url, "prompt": prompt, "duration": seconds, **spec["extra"]}
    if a := aspect_for(spec, aspect):
        body["aspect_ratio"] = a
    return body


# ── 가격 ─────────────────────────────────────────────

def _price(spec: dict) -> None:
    for attempt in range(3):  # 동시에 많이 물으면 일시적으로 거절될 수 있어 다시 시도
        if _price_once(spec):
            return
        time.sleep(1.5 * (attempt + 1))


def _price_once(spec: dict) -> bool:
    try:
        if spec["kind"] == "image":
            res = higgsfield._request("POST", f"{higgsfield.BASE}/estimate/{spec['id']}", image_body(spec, _SAMPLE_PROMPT, [_SAMPLE_IMG], "9:16"), timeout=30)
            spec["usd"] = float(res["usd"]) if res.get("usd") is not None else None
            if spec["usd"] is None and "token" in res.get("pricing_description", "").lower():
                spec["price_note"] = "사용량(토큰) 기준 과금"
        else:
            sec = clip_seconds(spec, 5)
            res = higgsfield._request("POST", f"{higgsfield.BASE}/estimate/{spec['id']}", video_body(spec, _SAMPLE_IMG, _SAMPLE_PROMPT, sec, "9:16"), timeout=30)
            if res.get("usd") is not None:
                spec["usd_per_sec"] = round(float(res["usd"]) / sec, 4)
            else:
                text = res.get("pricing_description", "")
                num = r"\$(\d+(?:\.\d+)?)"  # "$0.0714." 처럼 문장 끝 마침표는 빼고 읽는다
                if not spec.get("resolution"):
                    # 화질 설정이 없는 모델은 가격표에 적힌 화질이 곧 출력 화질 (예: "720p: $0.0714")
                    native = re.search(r"(\d{3,4}p|\dK)\s*:", text, re.I)
                    spec["native_res"] = native.group(1) if native else None
                label = spec.get("resolution") or spec.get("native_res") or "720p"
                m = re.search(rf"{re.escape(label)}:\s*{num}", text, re.I) or re.search(num, text)
                spec["usd_per_sec"] = float(m.group(1)) if m else None
        return True
    except higgsfield.HiggsfieldError as e:
        return "HTTP 4" in str(e) and "429" not in str(e)  # 요청 형식 문제면 다시 묻지 않는다 (견적 없이 목록에는 둔다)
    except Exception:  # noqa: BLE001
        return False


# ── 갱신 ─────────────────────────────────────────────

def refresh() -> dict:
    """힉스필드에서 모델 목록을 새로 받아 저장한다."""
    if not higgsfield.is_configured():
        raise RuntimeError("힉스필드 키가 없습니다.")
    _refreshing.set()
    try:
        items = higgsfield._request("GET", f"{higgsfield.BASE}/models?include_schema=true", timeout=60).get("items", [])
        images = [s for s in map(_image_spec, items) if s]
        videos = [s for s in map(_video_spec, items) if s]
        _labels(images)
        _labels(videos)
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(_price, images + videos))
        images = [s for s in images if s["resolution"]]
        videos = [s for s in videos if _res_px(s["resolution"] or s.get("native_res")) >= MIN_PX]
        for s in videos:
            s["resolution"] = s["resolution"] or s.get("native_res")
        images.sort(key=lambda s: s["label"].lower())
        videos.sort(key=lambda s: s["label"].lower())
        cat = {"updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "fetched": time.time(),
               "image": {s["id"]: s for s in images}, "video": {s["id"]: s for s in videos}}
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(cat, ensure_ascii=False, indent=1), encoding="utf-8")
        global _catalog
        with _lock:
            _catalog = cat
        print(f"[catalog] 힉스필드 모델 갱신: 이미지 {len(images)}개 · 영상 {len(videos)}개")
        return cat
    finally:
        _refreshing.clear()


def _refresh_in_background() -> None:
    if _refreshing.is_set():
        return

    def run():
        try:
            refresh()
        except Exception:  # noqa: BLE001
            traceback.print_exc()

    threading.Thread(target=run, daemon=True).start()


def get() -> dict:
    """현재 카탈로그. 12시간이 지났으면 뒤에서 갱신하고, 처음이면 받아 올 때까지 기다린다."""
    global _catalog
    with _lock:
        cat = _catalog
    if cat is None and CACHE.exists():
        try:
            cat = json.loads(CACHE.read_text(encoding="utf-8"))
            with _lock:
                _catalog = cat
        except (OSError, ValueError):
            cat = None
    if cat is None:
        try:
            return refresh()
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            return {"updated_at": None, "fetched": 0, "image": {}, "video": {}}
    if time.time() - cat.get("fetched", 0) > REFRESH_SEC:
        _refresh_in_background()
    return cat


def start_scheduler() -> None:
    """서버가 켜져 있는 동안 12시간마다 갱신한다."""
    if not higgsfield.is_configured():
        return

    def loop():
        while True:
            try:
                cat = get()
                wait = max(60, REFRESH_SEC - (time.time() - cat.get("fetched", 0)))
            except Exception:  # noqa: BLE001
                wait = 600
            time.sleep(wait)
            try:
                refresh()
            except Exception:  # noqa: BLE001
                traceback.print_exc()

    threading.Thread(target=loop, daemon=True, name="higgsfield-catalog").start()


def spec(kind: str, model_id: str) -> dict | None:
    return get()[kind].get(model_id)


def resolve(kind: str, chosen: str) -> str:
    """고른 모델이 목록에 없으면(종료된 모델 등) 기본 모델 → 목록 첫 모델 순으로 대신 쓴다."""
    models = get()[kind]
    default = config.HIGGSFIELD_IMAGE_MODEL if kind == "image" else config.HIGGSFIELD_VIDEO_MODEL
    for m in (chosen, default):
        if m and m in models:
            return m
    return next(iter(models), default)
