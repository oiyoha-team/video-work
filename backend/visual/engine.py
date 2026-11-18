"""②-A 비주얼 엔진. 실제 이미지 생성/이미지-투-비디오 AI를 붙일 때 이 인터페이스를 구현한다.

실제 엔진은 ctx.prompt(장면 브리프)로 이미지를 만들고, 참고 이미지로 ctx.ref_frame(레퍼런스 장면 — 구도만),
ctx.cast_image(새 인물 — 얼굴·헤어·의상), ctx.products(제품 사진 — 손에 든 크기 비교·패키지)를 역할과 함께 넘긴다.

- HiggsfieldEngine: 이미지 → 영상. 모델은 5단계에서 고르며 목록은 catalog.py가 12시간마다 갱신한다
- MockVisualEngine: 키가 없을 때. 레퍼런스 프레임 + ffmpeg 줌/팬 효과 (전체 흐름 테스트용)
"""
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import config
import media
from schemas import Scene

from . import catalog, higgsfield


@dataclass
class SceneContext:
    scene: Scene
    aspect: str
    ref_frame: Path | None  # 대응 레퍼런스 구간 프레임
    products: list[tuple[Path, str]]  # (제품 사진, 역할 in_hand|packaging|other) — 장면에 배정하지 않는 참고 자료
    prompt: str  # 장면 브리프 (영어 이미지 프롬프트)
    motion: str  # 이미지→영상 카메라 움직임
    has_person: bool = True
    cast_image: Path | None = None  # 새 인물 기준 이미지
    product_scale: str = ""  # 제품 실제 크기 (영어)
    image_model: str = config.HIGGSFIELD_IMAGE_MODEL
    video_model: str = config.HIGGSFIELD_VIDEO_MODEL


class VisualEngine(Protocol):
    name: str
    label: str

    def generate_image(self, ctx: SceneContext, out: Path) -> None: ...
    def generate_portrait(self, prompt: str, aspect: str, model: str, out: Path) -> None: ...
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

    def generate_portrait(self, prompt: str, aspect: str, model: str, out: Path) -> None:
        w, h = media.RESOLUTIONS[aspect]
        out.parent.mkdir(parents=True, exist_ok=True)
        media.check(["-y", "-f", "lavfi", "-i", f"color=c=0x8a8f88:s={w}x{h}", "-frames:v", "1", str(out)], "인물 기준 이미지")

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

    label = "힉스필드"

    def generate_image(self, ctx: SceneContext, out: Path) -> None:
        spec = catalog.spec("image", ctx.image_model)
        if spec is None:
            raise RuntimeError(f"이미지 모델 {ctx.image_model}을(를) 쓸 수 없습니다. 다른 모델을 고르세요.")
        refs = _pick_refs(ctx, spec["max_images"])
        urls = [higgsfield.upload(p) for p, _ in refs]
        body = catalog.image_body(spec, scene_prompt(ctx, [note for _, note in refs]), urls, ctx.aspect)
        res = higgsfield.generate(ctx.image_model, body)
        with tempfile.TemporaryDirectory() as tmp:
            raw = higgsfield.download(res["images"][0]["url"], Path(tmp) / "raw")
            _crop_to_aspect(raw, ctx.aspect, out)

    def generate_portrait(self, prompt: str, aspect: str, model: str, out: Path) -> None:
        """새 인물 기준 이미지. 레퍼런스 인물을 닮지 않게 참고 이미지 없이 글로만 만든다."""
        spec = catalog.spec("image", model)
        if spec is None:
            raise RuntimeError(f"이미지 모델 {model}을(를) 쓸 수 없습니다. 다른 모델을 고르세요.")
        res = higgsfield.generate(model, catalog.image_body(spec, prompt, [], aspect))
        with tempfile.TemporaryDirectory() as tmp:
            raw = higgsfield.download(res["images"][0]["url"], Path(tmp) / "raw")
            _crop_to_aspect(raw, aspect, out)

    def animate(self, image: Path, ctx: SceneContext, out: Path) -> None:
        spec = catalog.spec("video", ctx.video_model)
        if spec is None:
            raise RuntimeError(f"영상 모델 {ctx.video_model}을(를) 쓸 수 없습니다. 다른 모델을 고르세요.")
        prompt = f"Camera: {ctx.motion or 'slow push-in'}. Subtle natural movement, keep the subject and product consistent with the image. No text."
        seconds = catalog.clip_seconds(spec, ctx.scene.end - ctx.scene.start)
        res = higgsfield.generate(ctx.video_model, catalog.video_body(spec, higgsfield.upload(image), prompt, seconds, ctx.aspect))
        higgsfield.download(res["video"]["url"], out)


_REF_NOTE = ("the REFERENCE SHOT. Copy ONLY its composition, camera angle and distance, pose and gesture, background layout, "
             "lighting direction and color grade. Do NOT copy the person in it: not the face, hairstyle, clothing, accessories or any logos.")
_CAST_NOTE = "the PERSON to show. Use exactly this person's face, hairstyle, skin tone and outfit."
_HAND_NOTE = "our product held in a real adult hand. It shows the product's TRUE SIZE relative to a hand: keep exactly this scale."
_PACK_NOTE = "our product packaging. Reproduce its shape, colors and label design exactly."
_OTHER_NOTE = "another photo of our product, for its look and material."

INTEGRATION = (
    "The product must look physically photographed in this scene, not composited or pasted on: same light direction, "
    "color temperature and exposure as the scene, matching soft shadows and contact shadows, realistic packaging material "
    "(matte or foil sheen, slight creases), fingers naturally wrapping and overlapping its edges, the same perspective, "
    "depth of field, sharpness and image grain as the rest of the photo."
)
STYLE = ("Photorealistic smartphone UGC photo with natural skin texture. No added text, captions, subtitles, watermarks "
         "or brand logos other than our product's own label.")


def _pick_refs(ctx: SceneContext, limit: int) -> list[tuple[Path, str]]:
    """참고 이미지와 역할 설명. 우선순위: 레퍼런스 장면 → 새 인물 → 손에 든 크기 비교 1장 → 패키지 → 나머지.

    참고 이미지가 너무 많으면 생성 자체가 실패하므로 모델 한도(최대 catalog.REF_IMAGE_LIMIT=5장)를 넘기지 않는다.
    """
    hand = [p for p, r in ctx.products if r == "in_hand"]
    pack = [p for p, r in ctx.products if r == "packaging"]
    other = [p for p, r in ctx.products if r not in ("in_hand", "packaging")]
    refs: list[tuple[Path, str]] = []
    if ctx.ref_frame:
        refs.append((ctx.ref_frame, _REF_NOTE))
    if ctx.has_person and ctx.cast_image and ctx.cast_image.exists():
        refs.append((ctx.cast_image, _CAST_NOTE))
    refs += [(p, _HAND_NOTE) for p in hand[:1]] + [(p, _PACK_NOTE) for p in pack] + [(p, _OTHER_NOTE) for p in other] + [(p, _HAND_NOTE) for p in hand[1:]]
    return refs[:limit]


def scene_prompt(ctx: SceneContext, notes: list[str]) -> str:
    """장면 브리프 + 참고 이미지별 역할 + 크기·합성·화질 지시."""
    parts = [ctx.prompt]
    if notes:
        parts.append("Reference images: " + " ".join(f"Image {i} is {n}" for i, n in enumerate(notes, 1)))
    if ctx.products:
        parts.append(" ".join(x for x in (ctx.product_scale, "If the product appears, it must keep this real-world size relative to hands and body." if ctx.product_scale else "", INTEGRATION) if x))
    parts.append(STYLE)
    return "\n\n".join(parts)


def portrait_prompt(character: str) -> str:
    return (f"Waist-up portrait photo of this person looking at the camera: {character} "
            "Plain softly lit indoor background, natural daylight, neutral expression. " + STYLE)


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
