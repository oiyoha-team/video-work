"""②-A 비주얼 엔진. 실제 이미지 생성/이미지-투-비디오 AI를 붙일 때 이 인터페이스를 구현한다.

실제 엔진은 ctx.prompt(장면 브리프)로 이미지를 만들고, ctx.reference_frame(레퍼런스 장면)과
ctx.product_images(자사 제품 연출컷·누끼컷 전체)를 참고 이미지로 쓴다.

현재는 MockVisualEngine: 레퍼런스 프레임으로 장면 이미지를 대신하고,
ffmpeg 줌/팬 효과로 장면 길이만큼의 클립을 만든다 (전체 흐름 테스트용).
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import config
import media
from schemas import Scene


@dataclass
class SceneContext:
    scene: Scene
    aspect: str
    ref_frame: Path | None  # 대응 레퍼런스 구간 프레임
    product_images: list[Path]  # 자사 제품 연출컷·누끼컷 전체 (장면에 배정하지 않는 참고 자료)
    prompt: str  # 장면 브리프 (영어 이미지 프롬프트)
    motion: str  # 이미지→영상 카메라 움직임


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


def get_engine() -> VisualEngine:
    # 실제 엔진 추가 시: if config.VISUAL_ENGINE == "xxx": return XxxEngine()
    _ = config.VISUAL_ENGINE
    return MockVisualEngine()
