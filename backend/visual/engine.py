"""②-A 비주얼 엔진. 실제 이미지 생성/이미지-투-비디오 AI를 붙일 때 이 인터페이스를 구현한다.

실제 엔진은 ctx.prompt(장면 브리프)로 이미지를 만들고, ctx.reference_frame(레퍼런스 장면)과
ctx.product_images(자사 제품 연출컷·누끼컷 전체)를 참고 이미지로 쓴다.

- HiggsfieldEngine: 이미지(Grok Image 2.0, 참고 이미지 최대 10장) → 영상(VIDEO_MODELS 중 선택)
- MockVisualEngine: 키가 없을 때. 레퍼런스 프레임 + ffmpeg 줌/팬 효과 (전체 흐름 테스트용)
"""
import math
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import config
import media
from schemas import Scene

from . import higgsfield

# 이미지→영상 모델. min/max = 허용 길이(초, 정수). extra = 모델별 고정 옵션 (생성 음성은 끔: 음성은 TTS로 따로 만든다)
VIDEO_MODELS: dict[str, dict] = {
    "wan/v2.7/image-to-video": {"label": "Wan 2.7 · 720p", "min": 2, "max": 15, "extra": {"resolution": "720p"}, "usd_per_sec": 0.075},
    "kling-video/v3.0/std/image-to-video": {"label": "Kling 3.0 Standard · 720p", "min": 3, "max": 15, "extra": {"sound": "off"}, "usd_per_sec": 0.0714},
    "alibaba/happy-horse/v1.1/image-to-video": {"label": "Happy Horse 1.1 · 720p", "min": 2, "max": 15, "extra": {"resolution": "720p"}, "usd_per_sec": 0.14},
    "bytedance/seedance-2.0/image-to-video": {"label": "Seedance 2.0 · 720p", "min": 4, "max": 15, "extra": {"resolution": "720p", "generate_audio": False}, "usd_per_sec": 0.1735},
}
IMAGE_USD = 0.09  # Grok Image 2.0 · 1k 한 장 (2026-11-18 견적 기준)

# Grok Image 2.0이 지원하는 비율. 4:5는 없어서 3:4로 만든 뒤 4:5로 잘라 쓴다
_GROK_ASPECT = {"9:16": "9:16", "16:9": "16:9", "1:1": "1:1", "4:5": "3:4"}


def clip_seconds(scene: Scene, model: str) -> int:
    """장면 길이를 모델이 허용하는 정수 초로 맞춘다 (짧으면 최소 길이로, 편집 때 잘라 쓰면 됨)."""
    spec = VIDEO_MODELS[model]
    return max(spec["min"], min(spec["max"], math.ceil(scene.end - scene.start - 0.05)))


@dataclass
class SceneContext:
    scene: Scene
    aspect: str
    ref_frame: Path | None  # 대응 레퍼런스 구간 프레임
    product_images: list[Path]  # 자사 제품 연출컷·누끼컷 전체 (장면에 배정하지 않는 참고 자료)
    prompt: str  # 장면 브리프 (영어 이미지 프롬프트)
    motion: str  # 이미지→영상 카메라 움직임
    video_model: str = config.HIGGSFIELD_VIDEO_MODEL


class VisualEngine(Protocol):
    name: str
    label: str

    def generate_image(self, ctx: SceneContext, out: Path) -> None: ...
    def animate(self, image: Path, ctx: SceneContext, out: Path) -> None: ...


class MockVisualEngine:
    name = "mock"
    label = "mock · 레퍼런스 프레임으로 대체"

    def generate_image(self, ctx: SceneContext, out: Path) -> None:
        w, h = media.RESOLUTIONS[ctx.aspect]
        cover = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"
        out.parent.mkdir(parents=True, exist_ok=True)
        if ctx.ref_frame:
            args = ["-y", "-i", str(ctx.ref_frame), "-vf", cover, "-frames:v", "1", "-q:v", "3", str(out)]
        else:
            args = ["-y", "-f", "lavfi", "-i", f"color=c=0x2f8f4e:s={w}x{h}", "-frames:v", "1", str(out)]
        media.check(args, "장면 이미지 생성")

    def animate(self, image: Path, ctx: SceneContext, out: Path) -> None:
        w, h = media.RESOLUTIONS[ctx.aspect]
        frames = max(1, round((ctx.scene.end - ctx.scene.start) * media.FPS))
        step = 0.12 / frames
        motion = ctx.motion.lower()
        if "out" in motion:
            zoom = f"if(eq(on,0),1.12,max(zoom-{step:.5f},1.0))"
        else:
            zoom = f"min(zoom+{step:.5f},1.12)"
        if "left" in motion or "right" in motion:
            # 좌우 패닝
            x = "(iw-iw/zoom)*on/{f}".format(f=frames) if "right" in motion else "(iw-iw/zoom)*(1-on/{f})".format(f=frames)
            zoom = "1.12"
        else:
            x = "iw/2-(iw/zoom/2)"
        vf = (
            f"scale={w * 2}:{h * 2},"
            f"zoompan=z='{zoom}':x='{x}':y='ih/2-(ih/zoom/2)':d={frames}:s={w}x{h}:fps={media.FPS}"
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        media.check(
            ["-y", "-i", str(image), "-vf", vf, "-frames:v", str(frames),
             "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-r", str(media.FPS), str(out)],
            "장면 영상화",
        )


class HiggsfieldEngine:
    name = "higgsfield"

    @property
    def label(self) -> str:
        return "힉스필드 · Grok Image 2.0 → 영상"

    def generate_image(self, ctx: SceneContext, out: Path) -> None:
        refs = ([ctx.ref_frame] if ctx.ref_frame else []) + ctx.product_images
        urls = [higgsfield.upload(p) for p in refs[:10]]
        notes = []
        if ctx.ref_frame:
            notes.append("Image 1 is the reference scene: match its composition, camera angle, framing, lighting and mood.")
        if ctx.product_images:
            first = 2 if ctx.ref_frame else 1
            notes.append(f"Images {first}-{len(urls)} show our product: reproduce its packaging exactly (shape, colors, label design) wherever the product appears.")
        notes.append("Photorealistic. No added text, captions, subtitles or watermarks.")
        body = {
            "prompt": "\n\n".join([ctx.prompt, " ".join(notes)]),
            "image_urls": urls,
            "aspect_ratio": _GROK_ASPECT.get(ctx.aspect, "9:16"),
            "resolution": "1k",
            "quality": "medium",
        }
        res = higgsfield.generate(config.HIGGSFIELD_IMAGE_MODEL, body)
        with tempfile.TemporaryDirectory() as tmp:
            raw = higgsfield.download(res["images"][0]["url"], Path(tmp) / "raw")
            _crop_to_aspect(raw, ctx.aspect, out)

    def animate(self, image: Path, ctx: SceneContext, out: Path) -> None:
        spec = VIDEO_MODELS[ctx.video_model]
        body = {
            "image_url": higgsfield.upload(image),
            "prompt": f"Camera: {ctx.motion or 'slow push-in'}. Subtle natural movement, keep the subject and product consistent with the image. No text.",
            "duration": clip_seconds(ctx.scene, ctx.video_model),
            **spec["extra"],
        }
        res = higgsfield.generate(ctx.video_model, body)
        higgsfield.download(res["video"]["url"], out)


def _crop_to_aspect(src: Path, aspect: str, out: Path) -> None:
    """원본 해상도를 유지한 채 목표 비율로 가운데를 잘라 jpg로 저장한다."""
    w, h = (int(x) for x in aspect.split(":"))
    crop = f"crop='min(iw,ih*{w}/{h})':'min(ih,iw*{h}/{w})'"
    out.parent.mkdir(parents=True, exist_ok=True)
    media.check(["-y", "-i", str(src), "-vf", crop, "-frames:v", "1", "-q:v", "2", str(out)], "이미지 비율 맞추기")


def get_engine() -> VisualEngine:
    if config.VISUAL_ENGINE == "higgsfield" and higgsfield.is_configured():
        return HiggsfieldEngine()
    return MockVisualEngine()
