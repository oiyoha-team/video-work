"""6 결과물 다운로드: 장면별 영상 클립·음성·이미지와 편집용 자료(자막·타임라인·스크립트)를 내려준다.

최종 편집은 사용자가 편집 툴에서 직접 한다. 그래서 파일 이름을 장면 순서대로 맞추고,
timeline.csv에 장면별 시간과 파일 이름을 정리해 바로 배치할 수 있게 한다.
"""
import csv
import io
import os
import re
import tempfile
import zipfile
from pathlib import Path

from planning import script_writer, store
from planning.labels import role_label
from planning.text import split_sentences
from schemas import Script

GROUPS = [
    ("clips", "영상 클립"),
    ("audio", "음성 (TTS)"),
    ("images", "장면 이미지"),
    ("docs", "편집용 자료"),
]
FOLDERS = {"clips": "영상클립", "audio": "음성", "images": "이미지", "docs": ""}

GUIDE = """[오이요하 퍼포먼스 영상 · 편집용 결과물]

영상클립/  장면 순서대로 번호가 붙은 클립 (scene01.mp4, scene02.mp4 ...)
음성/      문장별 대사 음성 (scene01_1.wav, scene01_2.wav ...) — 장면 번호_문장 번호, 대사가 없는 장면은 파일이 없습니다
이미지/    영상 클립의 원본 장면 이미지
timeline.csv   문장 한 줄씩: 장면 시작·끝 시간, 대사, 파일 이름 (엑셀에서 열림)
subtitles.srt  대사 문장으로 만든 자막 초안 — 편집 툴에서 '자막 가져오기'로 불러오세요
script.txt     확정된 대사 스크립트 (한 줄 = 한 문장)

편집 순서 예시
1. 영상클립을 번호 순서대로 타임라인에 이어 붙입니다.
2. 같은 장면 번호의 음성을 문장 순서대로 클립 위에 올립니다. (timeline.csv의 '장면 시작' 참고)
3. subtitles.srt를 불러와 자막을 얹고 폰트·위치를 다듬습니다.
"""


def _srt_time(sec: float) -> str:
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _subtitle_cues(script: Script) -> list[tuple[float, float, str]]:
    """대사 문장을 장면 길이 안에서 글자 수 비율대로 나눠 자막 초안을 만든다."""
    cues = []
    for s in script.scenes:
        sentences = split_sentences(s.dialogue)
        weights = [max(1, len(re.findall(r"[가-힣A-Za-z0-9]", x))) for x in sentences]
        t = s.start
        for sentence, w in zip(sentences, weights):
            end = t + (s.end - s.start) * w / sum(weights)
            cues.append((t, end, sentence))
            t = end
    return cues


def build_srt(script: Script) -> str:
    return "\n".join(
        f"{n}\n{_srt_time(a)} --> {_srt_time(b)}\n{text}\n" for n, (a, b, text) in enumerate(_subtitle_cues(script), 1)
    )


def _scene_name(i: int) -> str:
    return f"scene{i + 1:02d}"


def _write_docs(project_id: str, script: Script) -> Path:
    """편집용 자료를 export/ 폴더에 (다시) 만든다."""
    prod = store.get_production(project_id)
    out = store.project_dir(project_id) / "export"
    out.mkdir(exist_ok=True)

    (out / "subtitles.srt").write_text(build_srt(script), encoding="utf-8")
    (out / "script.txt").write_text(script_writer.to_text(script), encoding="utf-8")
    (out / "script.json").write_text(script.model_dump_json(indent=2), encoding="utf-8")
    (out / "README.txt").write_text(GUIDE, encoding="utf-8")

    buf = io.StringIO()
    w = csv.writer(buf)
    # 한 행 = 한 문장 (대사 없는 장면은 한 행)
    w.writerow(["장면", "문장", "장면 시작(초)", "장면 끝(초)", "장면 길이(초)", "역할", "대사", "영상 파일", "음성 파일", "음성 길이(초)"])
    for i, s in enumerate(script.scenes):
        va, sa = prod.visual.scenes.get(s.id), prod.sound.scenes.get(s.id)
        name = _scene_name(i)
        clip = f"영상클립/{name}.mp4" if va and va.video else ""
        sentences = split_sentences(s.dialogue) or [""]
        sound_lines = sa.lines if sa else []
        for n, sentence in enumerate(sentences, 1):
            line = sound_lines[n - 1] if n <= len(sound_lines) else None
            w.writerow([
                i + 1, n if sentence else "", f"{s.start:.2f}", f"{s.end:.2f}", f"{s.end - s.start:.2f}", role_label(s.role),
                sentence, clip,
                f"음성/{name}_{n}.wav" if line and line.audio else "",
                f"{line.duration:.2f}" if line and line.audio else "",
            ])
    # 엑셀에서 한글이 깨지지 않도록 BOM 포함
    (out / "timeline.csv").write_text(buf.getvalue(), encoding="utf-8-sig")
    return out


def list_items(project_id: str) -> list[dict]:
    """내려받을 수 있는 모든 파일. key는 ZIP 선택에 쓰인다."""
    script = store.get_script(project_id)
    if script is None:
        raise ValueError("스크립트가 없습니다.")
    prod = store.get_production(project_id)
    pdir = store.project_dir(project_id)
    _write_docs(project_id, script)

    items: list[dict] = []

    def add(key: str, group: str, label: str, rel: str | None, filename: str, scene: int | None = None):
        if not rel or not (pdir / rel).exists():
            return
        folder = FOLDERS[group]
        items.append({
            "key": key,
            "group": group,
            "label": label,
            "path": rel,
            "filename": f"{folder}/{filename}" if folder else filename,
            "size": (pdir / rel).stat().st_size,
            "scene": scene,
        })

    for i, s in enumerate(script.scenes):
        va, sa = prod.visual.scenes.get(s.id), prod.sound.scenes.get(s.id)
        name, label = _scene_name(i), f"#{i + 1:02d} {role_label(s.role) if s.role else ''}".strip()
        add(f"clip:{s.id}", "clips", label, va.video if va else None, f"{name}.mp4", i + 1)
        for n, line in enumerate(sa.lines if sa else [], 1):
            add(f"audio:{s.id}:{n}", "audio", f"#{i + 1:02d}-{n} {line.text}", line.audio, f"{name}_{n}.wav", i + 1)
        add(f"image:{s.id}", "images", label, va.image if va else None, f"{name}.jpg", i + 1)

    for key, label in [("timeline.csv", "타임라인 (장면별 시간·파일 정리)"), ("subtitles.srt", "자막 (SRT)"),
                       ("script.txt", "기획안 (텍스트)"), ("script.json", "기획안 (JSON)"), ("README.txt", "편집 안내")]:
        add(f"doc:{key}", "docs", label, f"export/{key}", key)
    return items


def build_zip(project_id: str, keys: list[str] | None) -> Path:
    """선택한 항목(없으면 전체)을 ZIP으로 묶어 임시 파일 경로를 반환한다."""
    items = list_items(project_id)
    if keys:
        wanted = set(keys)
        items = [it for it in items if it["key"] in wanted]
    if not items:
        raise ValueError("내려받을 파일이 없습니다.")
    pdir = store.project_dir(project_id)
    fd, name = tempfile.mkstemp(suffix=".zip")
    os.close(fd)  # Windows: 열린 핸들이 남으면 전송 후 삭제가 안 된다
    tmp = Path(name)
    with zipfile.ZipFile(tmp, "w") as zf:
        for it in items:
            # 영상·음성은 압축 효과가 적어 그대로 저장, 텍스트만 압축
            method = zipfile.ZIP_DEFLATED if it["group"] == "docs" else zipfile.ZIP_STORED
            zf.write(pdir / it["path"], it["filename"], compress_type=method)
    return tmp
