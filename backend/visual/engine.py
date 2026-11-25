"""②-A 비주얼 엔진. 실제 이미지 생성/이미지-투-비디오 AI를 붙일 때 이 인터페이스를 구현한다.

실제 엔진은 그림체(style_guide)·세계관(world)·장면 브리프(prompt)로 이미지를 만든다. 참고 이미지:
- 기준 장면(첫 장면): 레퍼런스 영상의 그림체 견본(style_frames — 인물·배경·구도는 쓰지 않음) + 제품 사진
- 나머지 장면: 기준 장면 이미지(anchor_image — 그림체·세계관·인물) + 인물 기준 이미지 + 제품 사진
레퍼런스 장면을 그대로 넘기지 않으므로 레퍼런스와 같은 장면·인물·배경이 나오지 않는다.

- HiggsfieldEngine: 이미지 → 영상. 모델은 5단계에서 고르며 목록은 catalog.py가 12시간마다 갱신한다
- MockVisualEngine: 키가 없을 때. 레퍼런스 프레임 + ffmpeg 줌/팬 효과 (전체 흐름 테스트용)
"""
import tempfile
from dataclasses import dataclass, field
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
    ref_frame: Path | None  # 대응 레퍼런스 구간 프레임 (임시 엔진 전용 — 실제 생성에는 넘기지 않는다)
    products: list[tuple[Path, str]]  # (제품 사진, 역할 in_hand|packaging|other) — 장면에 배정하지 않는 참고 자료
    prompt: str  # 장면 브리프 (영어 이미지 프롬프트)
    motion: str  # 이미지→영상 카메라 움직임
    has_person: bool = True
    cast_image: Path | None = None  # 인물 기준 이미지
    cast_is_anchor: bool = False  # 인물 기준 = 기준 장면 (따로 넣을 필요 없음)
    product_scale: str = ""  # 제품 실제 크기 (영어)
    image_model: str = config.HIGGSFIELD_IMAGE_MODEL
    video_model: str = config.HIGGSFIELD_VIDEO_MODEL
    style_guide: str = ""  # 레퍼런스에서 빌려 온 그림체 (영어)
    world: str = ""  # 새 배경·공간 (영어)
    style_frames: list[Path] = field(default_factory=list)  # 기준 장면을 만들 때만: 레퍼런스 그림체 견본
    anchor_image: Path | None = None  # 기준 장면 이미지 (기준 장면 자신을 만들 때는 None)
    video_prompt: str = ""  # 영상 수정 지시를 반영한 영상 프롬프트
    ref_follow: str = "medium"  # low면 레퍼런스 컷을 넘기지 않음, medium/high면 구도 참고로 넘김
    duration: float = 0  # 이 컷의 길이 (초). 0이면 장면 길이

    @property
    def clip_len(self) -> float:
        return self.duration if self.duration > 0 else max(self.scene.end - self.scene.start, 0.1)


class VisualEngine(Protocol):
    name: str
    label: str

    def generate_image(self, ctx: SceneContext, out: Path) -> None: ...
    def generate_portrait(self, prompt: str, aspect: str, model: str, out: Path, refs: list[tuple[Path, str]] | None = None) -> None: ...
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

    def generate_portrait(self, prompt: str, aspect: str, model: str, out: Path, refs: list[tuple[Path, str]] | None = None) -> None:
        w, h = media.RESOLUTIONS[aspect]
        out.parent.mkdir(parents=True, exist_ok=True)
        media.check(["-y", "-f", "lavfi", "-i", f"color=c=0x8a8f88:s={w}x{h}", "-frames:v", "1", str(out)], "인물 기준 이미지")

    def animate(self, image: Path, ctx: SceneContext, out: Path) -> None:
        w, h = media.RESOLUTIONS[ctx.aspect]
        frames = max(1, round(ctx.clip_len * media.FPS))
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

    def generate_portrait(self, prompt: str, aspect: str, model: str, out: Path, refs: list[tuple[Path, str]] | None = None) -> None:
        """인물 기준 이미지. 참고 이미지는 그림체 기준(기준 장면)만 넣는다 — 레퍼런스 인물은 넣지 않는다."""
        spec = catalog.spec("image", model)
        if spec is None:
            raise RuntimeError(f"이미지 모델 {model}을(를) 쓸 수 없습니다. 다른 모델을 고르세요.")
        refs = (refs or [])[: spec["max_images"]]
        urls = [higgsfield.upload(p) for p, _ in refs]
        if refs:
            prompt += "\n\nReference images: " + " ".join(f"Image {i} is {n}" for i, (_, n) in enumerate(refs, 1))
        res = higgsfield.generate(model, catalog.image_body(spec, prompt, urls, aspect))
        with tempfile.TemporaryDirectory() as tmp:
            raw = higgsfield.download(res["images"][0]["url"], Path(tmp) / "raw")
            _crop_to_aspect(raw, aspect, out)

    def animate(self, image: Path, ctx: SceneContext, out: Path) -> None:
        spec = catalog.spec("video", ctx.video_model)
        if spec is None:
            raise RuntimeError(f"영상 모델 {ctx.video_model}을(를) 쓸 수 없습니다. 다른 모델을 고르세요.")
        seconds = catalog.clip_seconds(spec, ctx.clip_len)
        res = higgsfield.generate(ctx.video_model, catalog.video_body(spec, higgsfield.upload(image), video_prompt(ctx), seconds, ctx.aspect))
        higgsfield.download(res["video"]["url"], out)


# ── 참고 이미지 역할 ─────────────────────────────────────────────
_STYLE_NOTE = ("a STYLE SAMPLE from another video. Borrow ONLY its art style / medium, rendering, texture, color palette, "
               "lighting mood and image quality. Do NOT reproduce anything in it: not its people, faces, hairstyles, clothing, "
               "background, room, props, layout or composition. Create a completely new scene.")
_ANCHOR_NOTE = ("the KEY FRAME of this same ad (scene 1). Keep exactly its art style, rendering, color palette, lighting mood "
                "and the same character identity (face, hair, outfit) if a person appears. Do NOT reuse its camera angle, "
                "framing, shot size or composition — this is a different shot, composed as described.")
_LAYOUT_NOTES = {
    "medium": ("a SHOT LAYOUT reference from another video. Match ONLY its shot size, camera angle and height, framing, "
               "where the subject sits in the frame, and the pose / gesture. Do NOT copy its people (face, hair, clothing), "
               "background, props, colors or art style — those come from the text and the key frame."),
    "high": ("a SHOT LAYOUT reference from another video. Match its shot size, camera angle and height, framing, subject "
             "placement, pose / gesture and the general kind and arrangement of the setting, but redraw everything in this "
             "ad's art style with this ad's character, outfit and colors. Do NOT copy faces, hairstyles, clothing, logos or text."),
}
_CAST_NOTE = "the CHARACTER of this ad. Keep exactly this character's face, hairstyle, skin tone and outfit."
_HAND_NOTE = "our product held in a real adult hand. It shows the product's TRUE SIZE relative to a hand: keep exactly this scale."
_PACK_NOTE = "our product packaging. Keep its shape, colors and label design recognizable, rendered in this image's art style."
_OTHER_NOTE = "another photo of our product, for its look and material."

INTEGRATION = (
    "The product must look like it naturally belongs in this image, not composited or pasted on: rendered in the same art style, "
    "same light direction, color temperature and exposure as the scene, matching soft shadows and contact shadows, realistic "
    "packaging material, fingers naturally wrapping and overlapping its edges, the same perspective, depth of field and grain."
)
NO_TEXT = "No added text, captions, subtitles, watermarks or brand logos other than our product's own label."
DEFAULT_STYLE = "Photorealistic smartphone UGC photo with natural skin texture."


def _pick_refs(ctx: SceneContext, limit: int) -> list[tuple[Path, str]]:
    """참고 이미지와 역할 설명.

    - 기준 장면(첫 장면): 레퍼런스 영상의 그림체 견본(구도·인물은 쓰지 않음) + 제품 사진
    - 나머지 장면: 기준 장면(그림체·세계관·인물) + (기준 장면에 인물이 없을 때) 인물 기준 이미지 + 제품 사진
    참고 이미지가 너무 많으면 생성 자체가 실패하므로 모델 한도(최대 catalog.REF_IMAGE_LIMIT=5장)를 넘기지 않는다.
    """
    hand = [p for p, r in ctx.products if r == "in_hand"]
    pack = [p for p, r in ctx.products if r == "packaging"]
    other = [p for p, r in ctx.products if r not in ("in_hand", "packaging")]
    refs: list[tuple[Path, str]] = []
    if ctx.anchor_image and ctx.anchor_image.exists():
        refs.append((ctx.anchor_image, _ANCHOR_NOTE))
        if ctx.has_person and ctx.cast_image and ctx.cast_image.exists() and not ctx.cast_is_anchor:
            refs.append((ctx.cast_image, _CAST_NOTE))
    else:
        refs += [(p, _STYLE_NOTE) for p in ctx.style_frames[:1]]
    # 컷 다양성: 같은 위치 레퍼런스 장면의 구도(샷 크기·앵글·배치·동작)만 참고
    layout = _LAYOUT_NOTES.get(ctx.ref_follow)
    if layout and ctx.ref_frame and ctx.ref_frame.exists():
        refs.append((ctx.ref_frame, layout))
    refs += [(p, _HAND_NOTE) for p in hand[:1]] + [(p, _PACK_NOTE) for p in pack] + [(p, _OTHER_NOTE) for p in other] + [(p, _HAND_NOTE) for p in hand[1:]]
    return refs[:limit]


def scene_prompt(ctx: SceneContext, notes: list[str]) -> str:
    """그림체 → 세계관 → 장면 브리프 → 참고 이미지별 역할 → 크기·합성 지시."""
    parts = [f"Art style: {ctx.style_guide or DEFAULT_STYLE}"]
    if ctx.world:
        parts.append(f"Setting of this ad: {ctx.world}")
    parts.append(ctx.prompt)
    if notes:
        parts.append("Reference images: " + " ".join(f"Image {i} is {n}" for i, n in enumerate(notes, 1)))
    if ctx.products:
        parts.append(" ".join(x for x in (ctx.product_scale, "If the product appears, it must keep this real-world size relative to hands and body." if ctx.product_scale else "", INTEGRATION) if x))
    parts.append(NO_TEXT)
    return "\n\n".join(parts)


def video_prompt(ctx: SceneContext) -> str:
    move = ctx.video_prompt or f"Camera: {ctx.motion or 'slow push-in'}. Subtle natural movement."
    return f"{move} Keep the art style, the character and the product exactly consistent with the image. No text."


def portrait_prompt(character: str, style_guide: str = "") -> str:
    return (f"Art style: {style_guide or DEFAULT_STYLE}\n\nWaist-up character portrait looking at the camera: {character} "
            f"Simple softly lit background, neutral expression. {NO_TEXT}")


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
