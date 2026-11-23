"""프리미어 프로에서 가져오면 영상·음성이 제자리에 깔린 시퀀스가 열리는 타임라인 파일.

형식: Final Cut Pro 7 XML (xmeml v4) — 프리미어 [파일 > 가져오기]로 읽는다.
- V1: 장면 순서대로 영상 클립. 음성이 클립보다 길어 장면이 늘어난 부분은 클립 마지막 화면(정지 화면)으로 채운다.
  영상이 없고 이미지만 있는 장면은 이미지를 장면 길이만큼 놓는다.
- A1: 문장 음성을 timeline.csv의 '편집 음성 시작' 위치에.
- 파일 경로는 XML 파일 위치 기준 상대 경로(ZIP을 푼 폴더 구조 그대로)다.
  프리미어가 파일을 못 찾으면 [미디어 연결] 창에서 파일 하나만 찾아 주면 나머지는 자동으로 연결된다.
"""
import re
import wave
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote
from xml.sax.saxutils import escape

import media

FPS = media.FPS


def frames(sec: float) -> int:
    return int(round(sec * FPS))


def video_seconds(path: Path) -> float:
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", media.run(["-i", str(path)]).stderr)
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0.0


def last_frame(video: Path, out: Path) -> None:
    """클립 마지막 화면을 PNG로 (정지 화면으로 늘릴 때 사용). 이미 최신이면 다시 만들지 않는다."""
    if out.exists() and out.stat().st_mtime >= video.stat().st_mtime:
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    media.check(["-y", "-sseof", "-0.3", "-i", str(video), "-frames:v", "1", "-update", "1", str(out)], "마지막 화면 추출")


@dataclass
class Piece:
    """타임라인에 놓을 파일 하나. zip_path = ZIP 안 경로(= XML 기준 상대 경로)."""
    zip_path: str
    src: Path
    start: int  # 타임라인 위치 (프레임)
    end: int
    src_in: int = 0  # 원본 파일 안에서 쓰는 구간 (프레임)
    file_frames: int = 0  # 원본 파일 전체 길이 (프레임). 정지 이미지는 0
    kind: str = "video"  # video | still | audio
    rate: int = 44100
    channels: int = 1


@dataclass
class Plan:
    width: int
    height: int
    video: list[Piece] = field(default_factory=list)
    audio: list[Piece] = field(default_factory=list)

    @property
    def duration(self) -> int:
        return max([p.end for p in self.video + self.audio] or [0])


def wav_info(path: Path) -> tuple[int, int]:
    with wave.open(str(path), "rb") as wf:
        return wf.getframerate(), wf.getnchannels()


# ── XML ─────────────────────────────────────────────

def _rate() -> str:
    return f"<rate><timebase>{FPS}</timebase><ntsc>FALSE</ntsc></rate>"


def _pathurl(zip_path: str) -> str:
    return quote(zip_path, safe="/")


def _file(fid: str, p: Piece, plan: Plan) -> str:
    name = escape(Path(p.zip_path).name)
    if p.kind == "audio":
        media_xml = (f"<audio><samplecharacteristics><depth>16</depth><samplerate>{p.rate}</samplerate></samplecharacteristics>"
                     f"<channelcount>{p.channels}</channelcount></audio>")
    else:
        media_xml = (f"<video><samplecharacteristics>{_rate()}<width>{plan.width}</width><height>{plan.height}</height>"
                     "<anamorphic>FALSE</anamorphic><pixelaspectratio>square</pixelaspectratio>"
                     "<fielddominance>none</fielddominance></samplecharacteristics></video>")
    dur = f"<duration>{p.file_frames}</duration>" if p.file_frames else ""
    return (f'<file id="{fid}"><name>{name}</name><pathurl>{_pathurl(p.zip_path)}</pathurl>{_rate()}{dur}'
            f"<media>{media_xml}</media></file>")


def _clipitem(n: int, fid: str, p: Piece, plan: Plan, seen: set[str]) -> str:
    length = p.end - p.start
    # 같은 파일을 두 번 쓰면 두 번째부터는 id만 참조한다
    file_xml = f'<file id="{fid}"/>' if fid in seen else _file(fid, p, plan)
    seen.add(fid)
    track = ("<sourcetrack><mediatype>audio</mediatype><trackindex>1</trackindex></sourcetrack>" if p.kind == "audio" else "")
    total = p.file_frames or length
    return (f'<clipitem id="clipitem-{n}"><name>{escape(Path(p.zip_path).stem)}</name><enabled>TRUE</enabled>'
            f"<duration>{total}</duration>{_rate()}<start>{p.start}</start><end>{p.end}</end>"
            f"<in>{p.src_in}</in><out>{p.src_in + length}</out>{file_xml}{track}</clipitem>")


def build(plan: Plan, sequence_name: str) -> str:
    seen: set[str] = set()
    ids: dict[str, str] = {}

    def fid(p: Piece) -> str:
        return ids.setdefault(p.zip_path, f"file-{len(ids) + 1}")

    n = 0
    video_items, audio_items = [], []
    for p in plan.video:
        n += 1
        video_items.append(_clipitem(n, fid(p), p, plan, seen))
    for p in plan.audio:
        n += 1
        audio_items.append(_clipitem(n, fid(p), p, plan, seen))
    fmt = (f"<format><samplecharacteristics>{_rate()}<width>{plan.width}</width><height>{plan.height}</height>"
           "<anamorphic>FALSE</anamorphic><pixelaspectratio>square</pixelaspectratio><fielddominance>none</fielddominance>"
           "</samplecharacteristics></format>")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n<xmeml version="4">'
        f'<sequence id="sequence-1"><name>{escape(sequence_name)}</name><duration>{plan.duration}</duration>{_rate()}'
        f"<media><video>{fmt}<track>{''.join(video_items)}</track></video>"
        "<audio><numOutputChannels>2</numOutputChannels><format><samplecharacteristics><depth>16</depth>"
        "<samplerate>48000</samplerate></samplecharacteristics></format>"
        f"<track>{''.join(audio_items)}</track></audio></media>"
        f"<timecode>{_rate()}<string>00:00:00:00</string><frame>0</frame><displayformat>NDF</displayformat></timecode>"
        "</sequence></xmeml>\n"
    )
