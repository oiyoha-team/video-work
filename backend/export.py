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

import media
import premiere_xml
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

GUIDE = """[퍼포먼스 영상 · 편집용 결과물] 프로젝트: {name}

모든 파일 이름은 프로젝트명({p})으로 시작합니다. 다른 프로젝트 결과물과 한 폴더에 모아도 섞이지 않습니다.

영상클립/  장면 순서대로 번호가 붙은 클립 ({p}_scene01.mp4 … 장면에 컷이 여러 개면 {p}_scene01-1.mp4, {p}_scene01-2.mp4 …)
음성/      문장별 대사 음성 ({p}_scene01_1.wav, {p}_scene01_2.wav ...) — 장면 번호_문장 번호, 대사가 없는 장면은 파일이 없습니다
이미지/    영상 클립의 원본 장면 이미지
영상클립/정지화면/  음성이 클립보다 길어 늘어난 장면을 채우는 클립 마지막 화면
{p}_premiere.xml   ★ 프리미어 타임라인 — 가져오면 영상·음성이 제 위치에 깔린 시퀀스가 열립니다
{p}_subtitles_premiere.srt  ★ 프리미어용 자막 — 실제 음성 길이에 맞춘 시간 · 화면 비율에 맞춘 두 줄 나눔
{p}_timeline.csv   참고용 표: 장면·문장별 시간, 대사, 파일 이름 (엑셀에서 열림. 이 파일을 고쳐도 프리미어에는 반영되지 않습니다)
{p}_subtitles.srt  레퍼런스 장면 시간에 맞춘 자막 (음성을 장면 길이에 맞춰 줄여 쓸 때만 사용)
{p}_script.txt     확정된 대사 스크립트 (한 줄 = 한 문장)

프리미어 편집 순서
1. ZIP을 푼 폴더 구조를 그대로 둔 채, 프리미어에서 [파일 > 가져오기]로 {p}_premiere.xml 을 엽니다.
   → 프로젝트 패널에 시퀀스가 생깁니다. 더블클릭하면 영상(V1)과 음성(A1)이 이미 제 시간에 놓여 있습니다.
   음성이 클립보다 긴 장면은 클립 마지막 화면(정지 화면)이 이어 붙어 있고,
   영상 없이 이미지만 만든 장면은 이미지가 장면 길이만큼 놓여 있습니다.
   ※ [미디어 연결] 창이 뜨면: [찾기]를 눌러 표시된 파일 하나만 골라 주세요. 나머지는 자동으로 연결됩니다.
2. {p}_subtitles_premiere.srt 를 가져온 뒤, 타임라인 맨 앞(0초)에 끌어다 놓습니다.
   → 캡션 트랙이 생기고 음성과 시간이 맞습니다. 글꼴·크기·위치는 [창 > 텍스트]의 캡션 탭에서
     자막을 모두 선택(Ctrl+A)한 뒤 한 번에 바꿉니다.
"""


def file_prefix(project_name: str) -> str:
    """결과물 파일 이름 앞에 붙일 프로젝트명. 파일 이름에 못 쓰는 글자와 띄어쓰기는 _로 바꾼다."""
    safe = re.sub(r'[\\/:*?"<>|\s]+', "_", project_name.strip()).strip("._")
    return safe[:40] or "프로젝트"

# 프리미어 자막 한 줄 최대 글자 수 (화면 비율별). 넘으면 두 줄로, 두 줄도 넘으면 자막을 나눈다.
CAPTION_CHARS = {"9:16": 16, "4:5": 20, "1:1": 20, "16:9": 28}
SENTENCE_GAP = 0.15  # 같은 장면 안 문장 음성 사이 간격(초)


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


def edit_timeline(script: Script, prod) -> list[dict]:
    """편집 기준 타임라인: 장면을 순서대로 이어 붙이되, 음성이 클립보다 길면 장면을 음성 길이만큼 늘린다.

    장면마다 {start, end, lines: [(start, end, text, has_audio)]} — 프리미어 자막과 timeline.csv가 같은 값을 쓴다.
    """
    out, t = [], 0.0
    for s in script.scenes:
        clip_len = max(s.end - s.start, 0.1)
        sentences = split_sentences(s.dialogue)
        sa = prod.sound.scenes.get(s.id)
        voiced = sa and len(sa.lines) == len(sentences) and all(x.audio and x.duration > 0 for x in sa.lines)
        lines = []
        if voiced:
            cur = t
            for x in sa.lines:
                lines.append((cur, cur + x.duration, x.text, True))
                cur += x.duration + SENTENCE_GAP
            length = max(clip_len, cur - SENTENCE_GAP - t)
        else:
            # 음성이 없으면 장면 길이 안에서 글자 수 비율로 나눈다
            weights = [max(1, len(re.findall(r"[가-힣A-Za-z0-9]", x))) for x in sentences]
            cur = t
            for sentence, w in zip(sentences, weights):
                end = cur + clip_len * w / sum(weights)
                lines.append((cur, end, sentence, False))
                cur = end
            length = clip_len
        out.append({"start": t, "end": t + length, "lines": lines})
        t += length
    return out


def _wrap(text: str, width: int) -> list[str]:
    """띄어쓰기 기준으로 width 글자 안쪽에서 줄을 나눈다 (띄어쓰기 없이 길면 글자 단위로)."""
    lines, cur = [], ""
    for word in text.split():
        while len(word) > width:  # 한 단어가 한 줄보다 긴 경우
            if cur:
                lines.append(cur)
                cur = ""
            lines.append(word[:width])
            word = word[width:]
        if cur and len(cur) + 1 + len(word) > width:
            lines.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}" if cur else word
    if cur:
        lines.append(cur)
    return lines


def _two_lines(words: list[str], width: int) -> str | None:
    """단어들을 두 줄 이하로, 두 줄이면 길이가 비슷하게 나눈다. 안 들어가면 None."""
    one = " ".join(words)
    if len(one) <= width:
        return one
    best = None
    for i in range(1, len(words)):
        top, bottom = " ".join(words[:i]), " ".join(words[i:])
        if len(top) <= width and len(bottom) <= width:
            score = abs(len(top) - len(bottom))
            if best is None or score < best[0]:
                best = (score, f"{top}\n{bottom}")
    return best[1] if best else None


def _caption_chunks(text: str, width: int) -> list[str]:
    """문장을 자막 여러 개(각 최대 두 줄)로 나눈다. 조각 길이를 고르게 맞춰
    끝에 한두 단어만 따로 남거나 말이 어색하게 끊기는 일을 줄인다."""
    words = [w for line in _wrap(text, width) for w in line.split()]  # 너무 긴 단어는 _wrap이 미리 자름
    if not words:
        return []
    total = sum(len(w) for w in words) + len(words) - 1
    k = max(1, -(-total // (width * 2)))  # 필요한 최소 자막 수
    while k <= len(words):
        target = total / k
        groups, cur, acc = [], [], 0
        for i, w in enumerate(words):
            cur.append(w)
            acc += len(w) + 1
            left_words, left_groups = len(words) - i - 1, k - len(groups) - 1
            # 목표 길이에 닿았거나, 남은 단어가 남은 자막 수만큼밖에 없으면 끊는다
            if left_groups > 0 and (acc >= target * (len(groups) + 1) or left_words == left_groups):
                groups.append(cur)
                cur = []
        if cur:
            groups.append(cur)
        chunks = [_two_lines(g, width) for g in groups]
        if all(chunks):
            return chunks
        k += 1
    return _wrap(text, width)  # 예외적인 경우: 한 줄씩


def premiere_cues(script: Script, prod) -> list[tuple[float, float, str]]:
    """한 자막 = 최대 두 줄. 더 길면 문장 음성 시간을 글자 수 비율로 나눠 여러 자막으로 만든다."""
    width = CAPTION_CHARS.get(script.meta.aspect_ratio, 20)
    cues = []
    for scene in edit_timeline(script, prod):
        for a, b, text, _ in scene["lines"]:
            chunks = _caption_chunks(text, width)
            if not chunks:
                continue
            total = sum(len(c) for c in chunks)
            t = a
            for k, c in enumerate(chunks):
                end = b if k == len(chunks) - 1 else t + (b - a) * len(c) / total
                cues.append((t, end, c))
                t = end
    # 프리미어는 겹치거나 길이 0인 자막을 싫어하므로 정리
    cleaned = []
    for a, b, text in cues:
        if cleaned and a < cleaned[-1][1]:
            a = cleaned[-1][1]
        if b - a >= 0.05:
            cleaned.append((a, b, text))
    return cleaned


def build_premiere_srt(script: Script, prod) -> str:
    return "".join(
        f"{n}\n{_srt_time(a)} --> {_srt_time(b)}\n{text}\n\n" for n, (a, b, text) in enumerate(premiere_cues(script, prod), 1)
    )


def _scene_name(i: int) -> str:
    return f"scene{i + 1:02d}"


def scene_cuts(prod, scene, i: int) -> list[tuple[str, object, str]]:
    """장면의 컷 [(컷 id, 컷, 파일 이름)]. 컷이 하나면 scene01, 여러 개면 scene01-1, scene01-2 …"""
    from visual.cuts import scene_cut_ids  # 순환 import 방지

    ids = scene_cut_ids(prod, scene.id)
    name = _scene_name(i)
    out = []
    for k, cid in enumerate(ids, 1):
        c = prod.visual.scenes.get(cid)
        if c is not None:
            out.append((cid, c, name if len(ids) == 1 else f"{name}-{k}"))
    return out


def _write_docs(project_id: str, script: Script, prefix: str) -> Path:
    """편집용 자료를 export/ 폴더에 (다시) 만든다. 안에 적는 파일 이름은 내려받을 때의 이름(프로젝트명 포함)과 같다."""
    prod = store.get_production(project_id)
    out = store.project_dir(project_id) / "export"
    out.mkdir(exist_ok=True)

    (out / "subtitles.srt").write_text(build_srt(script), encoding="utf-8")
    # 윈도우 프리미어에서 한글이 깨지지 않도록 BOM 포함 UTF-8 + 윈도우 줄바꿈(CRLF)
    with open(out / "subtitles_premiere.srt", "w", encoding="utf-8-sig", newline="\r\n") as f:
        f.write(build_premiere_srt(script, prod))
    timeline = edit_timeline(script, prod)
    (out / "script.txt").write_text(script_writer.to_text(script), encoding="utf-8")
    (out / "script.json").write_text(script.model_dump_json(indent=2), encoding="utf-8")
    (out / "README.txt").write_text(GUIDE.format(name=store.get_project(project_id).name, p=prefix), encoding="utf-8")

    buf = io.StringIO()
    w = csv.writer(buf)
    # 한 행 = 한 문장 (대사 없는 장면은 한 행)
    w.writerow([
        "장면", "문장", "편집 장면 시작(초)", "편집 장면 끝(초)", "편집 음성 시작(초)", "역할", "대사",
        "영상 파일", "음성 파일", "음성 길이(초)", "클립 길이(초)", "레퍼런스 시작(초)", "레퍼런스 끝(초)",
    ])
    for i, (s, tl) in enumerate(zip(script.scenes, timeline)):
        sa = prod.sound.scenes.get(s.id)
        name = _scene_name(i)
        clip = " / ".join(f"영상클립/{prefix}_{cn}.mp4" if c.video else "(앞 장면 클립 이어짐)"
                          for _, c, cn in scene_cuts(prod, s, i) if c.video or c.link_prev)
        sentences = split_sentences(s.dialogue) or [""]
        sound_lines = sa.lines if sa else []
        for n, sentence in enumerate(sentences, 1):
            line = sound_lines[n - 1] if n <= len(sound_lines) else None
            voiced = bool(line and line.audio)
            cue = tl["lines"][n - 1] if n <= len(tl["lines"]) else None
            w.writerow([
                i + 1, n if sentence else "", f"{tl['start']:.2f}", f"{tl['end']:.2f}",
                f"{cue[0]:.2f}" if cue and voiced else "", role_label(s.role), sentence, clip,
                f"음성/{prefix}_{name}_{n}.wav" if voiced else "", f"{line.duration:.2f}" if voiced else "",
                f"{s.end - s.start:.2f}", f"{s.start:.2f}", f"{s.end:.2f}",
            ])
    # 엑셀에서 한글이 깨지지 않도록 BOM 포함
    (out / "timeline.csv").write_text(buf.getvalue(), encoding="utf-8-sig")

    plan = premiere_plan(project_id, script, prod, prefix, timeline)
    (out / "premiere.xml").write_text(premiere_xml.build(plan, f"{prefix}_편집"), encoding="utf-8")
    return plan


HOLD_DIR = "export/holds"


def premiere_plan(project_id: str, script: Script, prod, prefix: str, timeline: list[dict]) -> premiere_xml.Plan:
    """프리미어 타임라인 배치. 경로는 ZIP 안 경로(= XML 기준 상대 경로)와 같다."""
    pdir = store.project_dir(project_id)
    width, height = media.RESOLUTIONS.get(script.meta.aspect_ratio, (1080, 1920))
    plan = premiere_xml.Plan(width=width, height=height)
    f = premiere_xml.frames
    # 앞 장면 컷을 이어 쓰는 컷은 대표 컷의 클립을 이어서(같은 파일의 다음 구간) 놓는다
    shot: dict = {}  # {"va": 대표 컷, "cn": 파일 이름, "used": 이미 쓴 프레임}
    for i, (s, tl) in enumerate(zip(script.scenes, timeline)):
        name = _scene_name(i)
        sa = prod.sound.scenes.get(s.id)
        a, b = f(tl["start"]), f(tl["end"])
        cuts = scene_cuts(prod, s, i)
        for k, (_cid, va, cn) in enumerate(cuts):
            # 컷 위치는 장면 시작 기준. 마지막 컷은 장면 끝까지 (음성이 길어 늘어난 부분 포함)
            ca = a if k == 0 else min(b, a + f(va.start))
            cb = b if k == len(cuts) - 1 else min(b, a + f(va.end))
            if cb - ca < 1:
                continue
            used = 0
            if va.link_prev and shot:  # 같은 샷이 이어짐 → 대표 컷 파일을 이어서
                va, cn, used = shot["va"], shot["cn"], shot["used"]
            else:
                shot = {"va": va, "cn": cn, "used": 0}
            if va.video and (pdir / va.video).exists():
                src = pdir / va.video
                total = f(premiere_xml.video_seconds(src)) or (used + cb - ca)
                use = max(0, min(total - used, cb - ca))
                if use >= 1:
                    plan.video.append(premiere_xml.Piece(f"영상클립/{prefix}_{cn}.mp4", src, ca, ca + use, src_in=used, file_frames=total))
                if cb - ca - use >= 1:  # 클립이 컷보다 짧은 만큼 마지막 화면으로 채운다
                    hold = pdir / HOLD_DIR / f"{Path(va.video).stem}_hold.png"
                    premiere_xml.last_frame(src, hold)
                    plan.video.append(premiere_xml.Piece(f"영상클립/정지화면/{prefix}_{cn}_정지.png", hold, ca + use, cb, kind="still"))
            elif va.image and (pdir / va.image).exists():  # 영상 없이 이미지만 만든 컷
                plan.video.append(premiere_xml.Piece(f"이미지/{prefix}_{cn}{Path(va.image).suffix}", pdir / va.image, ca, cb, kind="still"))
            shot["used"] = used + (cb - ca)
        for n, (line, cue) in enumerate(zip(sa.lines if sa else [], tl["lines"]), 1):
            if not (cue[3] and line.audio and (pdir / line.audio).exists()):
                continue
            src = pdir / line.audio
            rate, channels = premiere_xml.wav_info(src)
            length = max(1, f(line.duration))
            plan.audio.append(premiere_xml.Piece(f"음성/{prefix}_{name}_{n}.wav", src, f(cue[0]), f(cue[0]) + length,
                                                 file_frames=length, kind="audio", rate=rate, channels=channels))
    return plan


def list_items(project_id: str) -> list[dict]:
    """내려받을 수 있는 모든 파일. key는 ZIP 선택에 쓰인다."""
    script = store.get_script(project_id)
    if script is None:
        raise ValueError("스크립트가 없습니다.")
    prod = store.get_production(project_id)
    pdir = store.project_dir(project_id)
    prefix = file_prefix(store.get_project(project_id).name)
    plan = _write_docs(project_id, script, prefix)

    items: list[dict] = []

    def add(key: str, group: str, label: str, rel: str | None, filename: str, scene: int | None = None, full_name: str = ""):
        if not rel or not (pdir / rel).exists():
            return
        folder = FOLDERS[group]
        items.append({
            "key": key,
            "group": group,
            "label": label,
            "path": rel,
            "filename": full_name or (f"{folder}/{prefix}_{filename}" if folder else f"{prefix}_{filename}"),
            "size": (pdir / rel).stat().st_size,
            "scene": scene,
        })

    # 정지 화면 (프리미어 타임라인에서 늘어난 장면을 채움)
    for piece in plan.video:
        if piece.zip_path.startswith("영상클립/정지화면/"):
            m = re.search(r"scene(\d+(?:-\d+)?)", piece.zip_path)
            n = int(m.group(1).split("-")[0])
            add(f"hold:{m.group(1)}", "images", f"#{m.group(1)} 정지 화면 (클립보다 길어진 부분)", piece.src.relative_to(pdir).as_posix(), "",
                n, full_name=piece.zip_path)

    for i, s in enumerate(script.scenes):
        sa = prod.sound.scenes.get(s.id)
        name, role = _scene_name(i), role_label(s.role) if s.role else ""
        cuts = scene_cuts(prod, s, i)
        for k, (cid, va, cn) in enumerate(cuts, 1):
            label = f"#{i + 1:02d}{f' 컷{k}' if len(cuts) > 1 else ''} {role}".strip()
            add(f"clip:{cid}", "clips", label, va.video, f"{cn}.mp4", i + 1)
        for n, line in enumerate(sa.lines if sa else [], 1):
            add(f"audio:{s.id}:{n}", "audio", f"#{i + 1:02d}-{n} {line.text}", line.audio, f"{name}_{n}.wav", i + 1)
        for k, (cid, va, cn) in enumerate(cuts, 1):
            label = f"#{i + 1:02d}{f' 컷{k}' if len(cuts) > 1 else ''} {role}".strip()
            add(f"image:{cid}", "images", label, va.image, f"{cn}{Path(va.image).suffix if va.image else '.jpg'}", i + 1)

    for key, label in [("premiere.xml", "★ 프리미어 타임라인 — 가져오면 영상·음성 자동 배치"),
                       ("timeline.csv", "타임라인 표 (참고용 · 장면별 시간·파일 정리)"),
                       ("subtitles_premiere.srt", "자막 — 프리미어용 (음성 길이에 맞춤)"),
                       ("subtitles.srt", "자막 — 레퍼런스 장면 시간 기준"),
                       ("script.txt", "기획안 (텍스트)"), ("script.json", "기획안 (JSON)"), ("README.txt", "편집 안내")]:
        add(f"doc:{key}", "docs", label, f"export/{key}", key)
    for it in items:
        if it["key"] == "doc:premiere.xml":
            it["needs"] = [p.zip_path for p in plan.video + plan.audio]  # 이 XML이 쓰는 파일
    return items


def build_zip(project_id: str, keys: list[str] | None) -> Path:
    """선택한 항목(없으면 전체)을 ZIP으로 묶어 임시 파일 경로를 반환한다."""
    items = list_items(project_id)
    if keys:
        wanted = set(keys)
        # 프리미어 타임라인을 고르면 그 타임라인이 쓰는 영상·음성·정지 화면도 함께 넣는다
        needs = {f for it in items if it["key"] in wanted for f in it.get("needs", [])}
        items = [it for it in items if it["key"] in wanted or it["filename"] in needs]
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
