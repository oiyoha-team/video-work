"""퍼포먼스 영상 자동화 — API 서버.

실행: backend 폴더에서 `uvicorn main:app --port 8000`
단계 전환 규칙은 workflow.py, 승인 알림은 gates.py / notify/ 참고.
"""
import hmac
import shutil
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.background import BackgroundTask

import config
import export
import gates
import workflow
from llm import claude_client
from llm.claude_client import ClaudeError, ClaudeNotConfigured
from notify import flow
from planning import chat_agent, products, script_writer, store, url_download, video_ingest
from planning.text import split_sentences
from schemas import AspectRatio, JobState, Product, Project, ReferenceAnalysis, Script, TTSSettings
from sound import engine as sound_engine
from sound import pipeline as sound_pipeline
from sound import typecast
from visual import catalog as visual_catalog
from visual import engine as visual_engine
from visual import pipeline as visual_pipeline

VIDEO_EXTS = {".mp4", ".mov", ".webm", ".m4v", ".mkv"}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # 서버가 꺼지면서 중단된 작업 상태 정리
    for p in store.list_projects():
        changed = {
            f: JobState(status="error", message="서버 재시작으로 중단되었습니다. 다시 실행하세요.")
            for f in Project.JOB_FIELDS
            if getattr(p, f).status == "running"
        }
        if changed:
            store.update_project(p.id, **changed)
    visual_catalog.start_scheduler()  # 힉스필드 모델 목록 12시간마다 갱신
    yield


app = FastAPI(title="퍼포먼스 영상 자동화", lifespan=lifespan)


@app.exception_handler(FileNotFoundError)
async def _not_found(_req: Request, exc: FileNotFoundError):
    return JSONResponse(status_code=404, content={"detail": f"찾을 수 없습니다: {exc}"})


@app.exception_handler(ValueError)
async def _bad_request(_req: Request, exc: ValueError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(ClaudeNotConfigured)
async def _claude_missing(_req: Request, exc: ClaudeNotConfigured):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(ClaudeError)
async def _claude_error(_req: Request, exc: ClaudeError):
    return JSONResponse(status_code=502, content={"detail": str(exc)})


# ── 상태 ─────────────────────────────────────────────

@app.get("/api/status")
def status():
    return {
        "platform": config.PLATFORM,
        "launcher": config.LAUNCHER,
        "claude_configured": claude_client.is_configured(),
        "claude_model": config.CLAUDE_MODEL,
        "stt_engine": config.STT_ENGINE,
        "whisper_model": config.WHISPER_MODEL,
        "visual_engine": visual_engine.get_engine().label,
        "sound_engine": sound_engine.get_engine().label,
        "visual_engine_id": visual_engine.get_engine().name,
        "sound_engine_id": sound_engine.get_engine().name,
        "flow_enabled": flow.is_enabled(),
        "max_video_sec": config.MAX_VIDEO_SEC,
        "aspect_ratios": config.ASPECT_RATIOS,
    }


# ── 프로젝트 ─────────────────────────────────────────────

class NewProject(BaseModel):
    name: str = ""


@app.get("/api/projects")
def list_projects():
    return store.list_projects()


@app.post("/api/projects")
def create_project(body: NewProject):
    name = " ".join(body.name.split())
    if not name:
        raise ValueError("프로젝트 이름을 입력하세요.")
    # 결과물 파일 이름에 프로젝트명이 들어가므로 같은 이름은 막는다 (파일이 섞이지 않도록)
    if any(p.name.strip().lower() == name.lower() for p in store.list_projects()):
        raise ValueError(f"'{name}' 이름의 프로젝트가 이미 있습니다. 다른 이름을 쓰거나 목록에서 불러오세요.")
    return store.create_project(name)


@app.get("/api/projects/{pid}")
def get_project(pid: str):
    return store.get_project(pid)


@app.delete("/api/projects/{pid}")
def delete_project(pid: str):
    store.get_project(pid)
    store.delete_project(pid)
    return {"ok": True}


class AspectBody(BaseModel):
    aspect_ratio: AspectRatio | None


@app.put("/api/projects/{pid}/aspect-ratio")
def set_aspect_ratio(pid: str, body: AspectBody):
    project = store.update_project(pid, aspect_ratio=body.aspect_ratio)
    script = store.get_script(pid)
    analysis = store.get_analysis(pid)
    if script and analysis:
        script.meta.aspect_ratio = body.aspect_ratio or analysis.source.detected_aspect_ratio
        store.save_script(pid, script)
    return project


# ── Step 1: 레퍼런스 ─────────────────────────────────────────────

@app.post("/api/projects/{pid}/reference")
def upload_reference(pid: str, file: UploadFile = File(...)):
    project = store.get_project(pid)
    if project.analysis_job.status == "running":
        raise HTTPException(409, "분석이 진행 중입니다.")
    ext = Path(file.filename or "").suffix.lower()
    if ext not in VIDEO_EXTS:
        raise ValueError(f"지원하지 않는 영상 형식입니다: {ext or '(없음)'} — mp4/mov/webm 권장")

    ref_dir = _fresh_reference_dir(pid)
    dest = ref_dir / f"source{ext}"
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    return _start_reference(pid, dest)


def _fresh_reference_dir(pid: str) -> Path:
    ref_dir = store.reference_dir(pid)
    if ref_dir.exists():
        shutil.rmtree(ref_dir)
    ref_dir.mkdir(parents=True)
    return ref_dir


def _start_reference(pid: str, dest: Path) -> dict:
    """reference/source.* 에 영상이 놓인 뒤: 길이 확인 → 이후 단계 초기화 → 분석 시작."""
    ref_dir = dest.parent
    try:
        info = video_ingest.probe(dest)
    except ValueError:
        shutil.rmtree(ref_dir)
        raise
    if info.duration > config.MAX_VIDEO_SEC + 0.5:
        shutil.rmtree(ref_dir)
        raise ValueError(f"영상 길이가 {info.duration:.1f}초입니다. {config.MAX_VIDEO_SEC // 60}분 이하 영상만 사용할 수 있습니다.")

    # 레퍼런스가 바뀌면 이후 단계 산출물은 모두 무효
    pdir = store.project_dir(pid)
    for name in ("script.json", "script.txt", "chat.json", "production.json"):
        (pdir / name).unlink(missing_ok=True)
    for d in ("visual", "sound", "export"):
        shutil.rmtree(pdir / d, ignore_errors=True)
    store.update_project(pid, step=1, completed=False, **{f: JobState() for f in Project.JOB_FIELDS})
    shutil.rmtree(_candidates_dir(pid), ignore_errors=True)
    workflow.start_analysis(pid)
    return {"duration": info.duration, "width": info.width, "height": info.height}


# 링크로 넣기: 받은 영상이 하나면 바로 분석, 여러 개면 후보 목록을 돌려주고 화면에서 고르게 한다
class ReferenceUrlBody(BaseModel):
    url: str


class SelectCandidateBody(BaseModel):
    id: str


def _candidates_dir(pid: str) -> Path:
    return store.project_dir(pid) / "url_candidates"


def _use_candidate(pid: str, cand: dict) -> dict:
    src = _candidates_dir(pid) / cand["file"]
    if not src.exists():
        raise ValueError("받아둔 영상을 찾을 수 없습니다. 링크를 다시 넣어주세요.")
    ref_dir = _fresh_reference_dir(pid)
    dest = ref_dir / f"source{src.suffix.lower()}"
    shutil.move(str(src), dest)
    return _start_reference(pid, dest)


@app.post("/api/projects/{pid}/reference/url")
def reference_from_url(pid: str, body: ReferenceUrlBody):
    project = store.get_project(pid)
    if project.analysis_job.status == "running":
        raise HTTPException(409, "분석이 진행 중입니다.")
    cdir = _candidates_dir(pid)
    candidates = url_download.as_dicts(url_download.download_candidates(body.url, cdir))
    if len(candidates) == 1:
        return {"started": True, **_use_candidate(pid, candidates[0])}
    store.write_json(cdir / "candidates.json", candidates)
    return {"started": False, "candidates": candidates}


@app.get("/api/projects/{pid}/reference/url/candidates")
def reference_candidates(pid: str):
    path = _candidates_dir(pid) / "candidates.json"
    return store.read_json(path) if path.exists() else []


@app.post("/api/projects/{pid}/reference/url/select")
def reference_select_candidate(pid: str, body: SelectCandidateBody):
    project = store.get_project(pid)
    if project.analysis_job.status == "running":
        raise HTTPException(409, "분석이 진행 중입니다.")
    path = _candidates_dir(pid) / "candidates.json"
    candidates = store.read_json(path) if path.exists() else []
    cand = next((c for c in candidates if c["id"] == body.id), None)
    if cand is None:
        raise ValueError("선택한 영상을 찾을 수 없습니다. 링크를 다시 넣어주세요.")
    return {"started": True, **_use_candidate(pid, cand)}


@app.delete("/api/projects/{pid}/reference/url/candidates")
def reference_cancel_candidates(pid: str):
    shutil.rmtree(_candidates_dir(pid), ignore_errors=True)
    return {"ok": True}


@app.post("/api/projects/{pid}/analyze")
def rerun_analysis(pid: str):
    project = store.get_project(pid)
    if project.analysis_job.status == "running":
        raise HTTPException(409, "분석이 이미 진행 중입니다.")
    if not any(store.reference_dir(pid).glob("source.*")):
        raise ValueError("레퍼런스 영상을 먼저 업로드하세요.")
    workflow.start_analysis(pid)
    return {"ok": True}


@app.get("/api/projects/{pid}/analysis")
def get_analysis(pid: str):
    return store.get_analysis(pid)


@app.put("/api/projects/{pid}/analysis")
def save_analysis(pid: str, body: ReferenceAnalysis):
    current = store.get_analysis(pid)
    if current is None:
        raise ValueError("분석 결과가 없습니다.")
    body.source = current.source  # 영상 메타데이터는 수정 불가
    body.confirmed = current.confirmed
    store.save_analysis(pid, body)
    return body


@app.post("/api/projects/{pid}/analysis/confirm")
def confirm_analysis(pid: str):
    return workflow.confirm_analysis(pid)


# ── Step 2: 제품 ─────────────────────────────────────────────

@app.get("/api/projects/{pid}/product")
def get_product(pid: str):
    store.get_project(pid)
    return store.get_product(pid)


@app.put("/api/projects/{pid}/product")
def update_product(pid: str, body: Product):
    store.get_project(pid)
    return products.update_fields(pid, body)


@app.post("/api/projects/{pid}/product/images/{kind}")
async def upload_product_images(pid: str, kind: str, files: list[UploadFile] = File(...)):
    store.get_project(pid)
    products.check_upload(pid, kind, [f.filename or "image.jpg" for f in files])
    product = None
    for f in files:
        product = products.add_image(pid, kind, f.filename or "image.jpg", await f.read())
    return product


@app.delete("/api/projects/{pid}/product/images/{kind}/{image_id}")
def delete_product_image(pid: str, kind: str, image_id: str):
    return products.remove_image(pid, kind, image_id)


class SaveLibraryBody(BaseModel):
    overwrite: bool = True
    template_name: str = ""


class RenameBody(BaseModel):
    name: str


@app.post("/api/projects/{pid}/product/save-to-library")
def save_product_to_library(pid: str, body: SaveLibraryBody):
    store.get_project(pid)
    return products.save_to_library(pid, body.overwrite, body.template_name)


@app.post("/api/projects/{pid}/product/load/{library_id}")
def load_product_from_library(pid: str, library_id: str):
    store.get_project(pid)
    return products.load_from_library(pid, library_id)


@app.post("/api/projects/{pid}/product/confirm")
def confirm_product(pid: str):
    return workflow.confirm_product(pid)


@app.get("/api/products")
def list_library():
    return products.list_library()


@app.put("/api/products/{library_id}/name")
def rename_library_product(library_id: str, body: RenameBody):
    return products.rename_template(library_id, body.name)


@app.delete("/api/products/{library_id}")
def delete_library_product(library_id: str):
    products.delete_from_library(library_id)
    return {"ok": True}


@app.get("/api/projects/{pid}/product/bundle")
def download_product_bundle(pid: str):
    """제품 정보 md + 연출컷·누끼컷을 ZIP 하나로 내려받는다."""
    product = store.get_product(pid)
    path = products.export_bundle(pid)
    name = f"{export.file_prefix(product.template_name or product.name or '제품정보')}_제품정보.zip"
    return FileResponse(path, media_type="application/zip", filename=name, background=BackgroundTask(path.unlink, missing_ok=True))


@app.post("/api/projects/{pid}/product/import")
async def import_product_bundle(pid: str, file: UploadFile = File(...)):
    """md 또는 ZIP(md + 연출컷/·누끼컷/)을 올린다. 이미지는 바로 추가되고, 글은 화면 입력란에 채운다."""
    store.get_project(pid)
    result = products.import_bundle(pid, file.filename or "", await file.read())
    return {**result, "product": store.get_product(pid)}


@app.post("/api/products/parse-md")
async def parse_markdown(file: UploadFile = File(...)):
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp949", errors="replace")
    return products.parse_markdown(text)


# ── Step 3: 스크립트 ─────────────────────────────────────────────

@app.get("/api/projects/{pid}/script")
def get_script(pid: str):
    return store.get_script(pid)


@app.post("/api/projects/{pid}/script/generate")
def generate_script(pid: str):
    project = store.get_project(pid)
    if project.script_job.status == "running":
        raise HTTPException(409, "스크립트 작성이 이미 진행 중입니다.")
    script = store.get_script(pid)
    if script and script.status == "final":
        raise ValueError("확정된 스크립트입니다. 편집을 다시 연 뒤 재생성하세요.")
    workflow.start_script(pid)
    return {"ok": True}


class RegenBody(BaseModel):
    instruction: str = ""


@app.post("/api/projects/{pid}/script/scenes/{scene_id}/regenerate")
def regenerate_scene(pid: str, scene_id: str, body: RegenBody):
    with store.lock(pid):
        script = script_writer.regenerate_scene(pid, scene_id, body.instruction)
        store.save_script(pid, script)
    return script


@app.put("/api/projects/{pid}/script")
def save_script(pid: str, body: Script):
    current = store.get_script(pid)
    if current is None:
        raise ValueError("스크립트가 없습니다.")
    if current.status == "final":
        raise ValueError("확정된 스크립트입니다. 편집을 다시 열어야 수정할 수 있습니다.")
    body.status = "draft"
    store.save_script(pid, body)
    return body


@app.get("/api/projects/{pid}/chat")
def get_chat(pid: str):
    store.get_project(pid)
    return store.get_chat(pid)


class ChatBody(BaseModel):
    message: str


@app.post("/api/projects/{pid}/chat")
def send_chat(pid: str, body: ChatBody):
    if not body.message.strip():
        raise ValueError("메시지를 입력하세요.")
    return chat_agent.send(pid, body.message.strip())


class ResolveBody(BaseModel):
    apply: bool


@app.post("/api/projects/{pid}/chat/{message_id}/resolve")
def resolve_chat(pid: str, message_id: str, body: ResolveBody):
    with store.lock(pid):
        return chat_agent.resolve(pid, message_id, body.apply)


# ── Step 4: 기획 확정 / 내보내기 ─────────────────────────────────────────────

@app.post("/api/projects/{pid}/script/finalize")
def finalize_script(pid: str):
    return workflow.finalize_script(pid)


@app.post("/api/projects/{pid}/script/reopen")
def reopen_script(pid: str):
    script = store.get_script(pid)
    if script is None:
        raise ValueError("스크립트가 없습니다.")
    script.status = "draft"
    store.save_script(pid, script)
    return script


@app.get("/api/projects/{pid}/script/text", response_class=PlainTextResponse)
def script_text(pid: str):
    script = store.get_script(pid)
    if script is None:
        raise ValueError("스크립트가 없습니다.")
    return script_writer.to_text(script)


# ── Step 5: 영상 제작 (비주얼 ∥ 사운드) ─────────────────────────────────────────────

@app.post("/api/projects/{pid}/production/start")
def start_production(pid: str):
    return workflow.start_production(pid)


@app.get("/api/projects/{pid}/production")
def get_production(pid: str):
    data = store.get_production(pid).model_dump()
    data["visual"]["image_model"] = visual_pipeline.image_model(pid)
    data["visual"]["video_model"] = visual_pipeline.video_model(pid)
    return {**data, "status": workflow.production_status(pid)}


@app.get("/api/projects/{pid}/production/estimate")
def production_estimate(pid: str):
    """생성 전 예상 비용 (USD). 단가는 힉스필드 견적 기준(2026-11-18)이며 실제 청구와 다를 수 있다."""
    script = store.get_script(pid)
    if script is None:
        raise ValueError("스크립트가 없습니다.")
    real = visual_engine.get_engine().name == "higgsfield"
    if not real:
        return {"scenes": len(script.scenes), "video_seconds": 0, "video_model": "mock", "image_model": "mock", "images_usd": 0, "videos_usd": 0,
                "total_usd": 0, "billable": False, "priced": True, "image_usd_each": 0, "scene_video_usd": {s.id: 0 for s in script.scenes}}
    ispec = visual_catalog.spec("image", visual_pipeline.image_model(pid)) or {}
    vspec = visual_catalog.spec("video", visual_pipeline.video_model(pid)) or {}
    secs = {s.id: visual_catalog.clip_seconds(vspec, s.end - s.start) if vspec else 0 for s in script.scenes}
    img_usd, per_sec = ispec.get("usd"), vspec.get("usd_per_sec")
    per_scene = {sid: round(sec * (per_sec or 0), 3) for sid, sec in secs.items()}
    images = round(len(script.scenes) * (img_usd or 0), 2)
    videos = round(sum(per_scene.values()), 2)
    return {"scenes": len(script.scenes), "video_seconds": sum(secs.values()), "video_model": vspec.get("label", "-"),
            "image_model": ispec.get("label", "-"), "images_usd": images, "videos_usd": videos, "total_usd": round(images + videos, 2),
            "billable": True, "priced": img_usd is not None and per_sec is not None,
            "image_usd_each": img_usd or 0, "scene_video_usd": per_scene}


@app.get("/api/visual/models")
def visual_models(refresh: bool = False):
    """힉스필드 이미지·영상 모델 목록 (12시간마다 자동 갱신, refresh=true면 지금 바로)."""
    if visual_engine.get_engine().name != "higgsfield":
        return {"updated_at": None, "image": [], "video": []}
    cat = visual_catalog.refresh() if refresh else visual_catalog.get()
    img = [{"id": s["id"], "label": s["label"], "usd": s["usd"], "max_images": s["max_images"]} for s in cat["image"].values()]
    vid = [{"id": s["id"], "label": s["label"], "usd_per_sec": s["usd_per_sec"], "resolution": s["resolution"],
            "min_sec": s["dur_enum"][0] if s["dur_enum"] else s["dur_min"], "max_sec": s["dur_enum"][-1] if s["dur_enum"] else s["dur_max"]}
           for s in cat["video"].values()]
    return {"updated_at": cat.get("updated_at"), "image": img, "video": vid,
            "default_image": config.HIGGSFIELD_IMAGE_MODEL, "default_video": config.HIGGSFIELD_VIDEO_MODEL}


class ModelBody(BaseModel):
    image_model: str | None = None
    video_model: str | None = None


@app.put("/api/projects/{pid}/visual/model")
def set_models(pid: str, body: ModelBody):
    if body.image_model and not visual_catalog.spec("image", body.image_model):
        raise ValueError("지원하지 않는 이미지 모델입니다.")
    if body.video_model and not visual_catalog.spec("video", body.video_model):
        raise ValueError("지원하지 않는 영상 모델입니다.")
    with store.lock(pid):
        prod = store.get_production(pid)
        if body.image_model:
            prod.visual.image_model = body.image_model
        if body.video_model:
            prod.visual.video_model = body.video_model
        store.save_production(pid, prod)
    return get_production(pid)


@app.get("/api/voices")
def list_voices(gender: str = "", age: str = ""):
    """타입캐스트 목소리 목록 (5단계 목소리 선택용): 이름·성별·연령·샘플 음성."""
    if not typecast.is_configured():
        return []
    out = []
    for v in typecast.list_voices():
        if (gender and v.get("gender") != gender) or (age and v.get("age") != age):
            continue
        out.append({
            "voice_id": v["voice_id"],
            "name": v["voice_name"].get("kor") or v["voice_name"].get("eng"),
            "gender": v.get("gender"),
            "age": v.get("age"),
            "use_cases": v.get("use_cases") or [],
            "preview_url": v.get("preview_url"),
        })
    return out



class VoiceBody(BaseModel):
    voice_id: str


@app.put("/api/projects/{pid}/sound/voice")
def set_voice(pid: str, body: VoiceBody):
    if not any(v["voice_id"] == body.voice_id for v in typecast.list_voices()):
        raise ValueError("목소리를 찾을 수 없습니다.")
    with store.lock(pid):
        prod = store.get_production(pid)
        prod.sound.voice_id = body.voice_id
        prod.sound.voice = sound_engine.voice_label(body.voice_id)
        store.save_production(pid, prod)
    return get_production(pid)


class TTSSettingsBody(BaseModel):
    voice_id: str = ""
    tempo: float = 1.0
    emotion: str = "smart"
    emotion_intensity: float = 1.0
    pitch: int = 0


@app.put("/api/projects/{pid}/sound/settings")
def set_tts_settings(pid: str, body: TTSSettingsBody):
    if body.voice_id and not any(v["voice_id"] == body.voice_id for v in typecast.list_voices()):
        raise ValueError("목소리를 찾을 수 없습니다.")
    with store.lock(pid):
        prod = store.get_production(pid)
        if body.voice_id:
            prod.sound.voice_id = body.voice_id
            prod.sound.voice = sound_engine.voice_label(body.voice_id)
        prod.sound.settings = TTSSettings(tempo=max(0.5, min(2.0, body.tempo)), emotion=body.emotion or "smart",
                                          emotion_intensity=max(0.0, min(2.0, body.emotion_intensity)), pitch=max(-12, min(12, body.pitch)))
        store.save_production(pid, prod)
    return get_production(pid)


@app.post("/api/projects/{pid}/sound/preview")
def preview_tts(pid: str, body: TTSSettingsBody):
    """현재 설정으로 첫 문장을 읽어 본다 (저장하지 않음)."""
    script = store.get_script(pid)
    sentences = [x for s in script.scenes for x in split_sentences(s.dialogue)] if script else []
    if not sentences:
        raise ValueError("읽을 대사가 없습니다.")
    settings = TTSSettings(tempo=body.tempo, emotion=body.emotion or "smart", emotion_intensity=body.emotion_intensity, pitch=body.pitch)
    rel = "sound/_preview.wav"
    voice_id = body.voice_id or sound_pipeline.resolve_voice_id(pid)
    sound_engine.get_engine().synthesize(sentences[0], script.voice, store.project_dir(pid) / rel,
                                         next_text=sentences[1] if len(sentences) > 1 else "", voice_id=voice_id, settings=settings)
    return {"url": f"/data/projects/{pid}/{rel}", "text": sentences[0]}


class SceneIdsBody(BaseModel):
    scene_ids: list[str] | None = None


@app.post("/api/projects/{pid}/visual/images")
def generate_images(pid: str, body: SceneIdsBody | None = None):
    workflow.start_images(pid, body.scene_ids if body else None)
    return {"ok": True}


@app.post("/api/projects/{pid}/visual/videos")
def generate_videos(pid: str, body: SceneIdsBody | None = None):
    workflow.start_videos(pid, body.scene_ids if body else None)
    return {"ok": True}


@app.post("/api/projects/{pid}/visual/approve")
def approve_images(pid: str):
    """[이미지 전체 승인 → 영상화]: 전체 승인 후 영상이 없는 장면을 영상화한다."""
    workflow.approve_images_and_animate(pid)
    return {"ok": True}


@app.post("/api/projects/{pid}/visual/cast")
def regenerate_cast(pid: str):
    """새 인물 기준 이미지를 다시 만든다 (같은 인물 설정으로 얼굴만 새로). 이후 장면 이미지를 다시 만들어야 반영된다."""
    if store.get_project(pid).visual_job.status == "running":
        raise HTTPException(409, "비주얼 작업이 진행 중입니다.")
    if not store.get_production(pid).visual.character:
        raise ValueError("아직 인물 설정이 없습니다. 이미지를 먼저 생성하세요.")
    visual_pipeline.make_cast(pid)
    return get_production(pid)


@app.post("/api/projects/{pid}/visual/scenes/{scene_id}/{what}")
def regenerate_visual(pid: str, scene_id: str, what: str):
    if store.get_project(pid).visual_job.status == "running":
        raise HTTPException(409, "비주얼 작업이 진행 중입니다.")
    if what == "image":
        visual_pipeline.make_image(pid, scene_id)
    elif what == "video":
        visual_pipeline.make_video(pid, scene_id)
    else:
        raise ValueError("image 또는 video 만 가능합니다.")
    return get_production(pid)


@app.post("/api/projects/{pid}/sound/generate")
def generate_sound(pid: str, body: SceneIdsBody | None = None):
    workflow.start_sound(pid, body.scene_ids if body else None)
    return {"ok": True}


@app.post("/api/projects/{pid}/sound/scenes/{scene_id}/lines/{n}")
def regenerate_line(pid: str, scene_id: str, n: int):
    if store.get_project(pid).sound_job.status == "running":
        raise HTTPException(409, "음성 작업이 진행 중입니다.")
    sound_pipeline.make_line(pid, scene_id, n)
    return get_production(pid)



@app.post("/api/projects/{pid}/sound/scenes/{scene_id}")
def regenerate_audio(pid: str, scene_id: str):
    if store.get_project(pid).sound_job.status == "running":
        raise HTTPException(409, "음성 작업이 진행 중입니다.")
    sound_pipeline.make_audio(pid, scene_id)
    return get_production(pid)


@app.post("/api/projects/{pid}/production/confirm")
def confirm_production(pid: str):
    return workflow.confirm_production(pid)


# ── Step 6: 결과물 다운로드 (사용자가 직접 편집) ─────────────────────────────────────────────

@app.get("/api/projects/{pid}/export")
def export_items(pid: str):
    return {"groups": [{"key": k, "label": v} for k, v in export.GROUPS], "items": export.list_items(pid)}


@app.get("/api/projects/{pid}/export/zip")
def export_zip(pid: str, items: str = ""):
    """items: 쉼표로 구분한 항목 key. 비우면 전체."""
    project = store.get_project(pid)
    keys = [k for k in items.split(",") if k] or None
    path = export.build_zip(pid, keys)
    name = f"{export.file_prefix(project.name)}_결과물_{'전체' if keys is None else '선택'}.zip"
    return FileResponse(path, media_type="application/zip", filename=name, background=BackgroundTask(path.unlink, missing_ok=True))


# ── 승인 게이트 (앱 알림 센터 · Flow 공통) ─────────────────────────────────────────────

@app.get("/api/gates")
def pending_gates():
    return gates.all_pending()


@app.get("/api/projects/{pid}/gates")
def project_gates(pid: str):
    return store.get_gates(pid)


class GateAction(BaseModel):
    action: str  # approve | revise
    comment: str = ""


@app.post("/api/projects/{pid}/gates/{gate_id}")
def resolve_gate(pid: str, gate_id: str, body: GateAction):
    return workflow.resolve_gate(pid, gate_id, body.action, body.comment.strip(), via="ui")


@app.post("/api/gates/{gate_id}/preview-flow", response_class=PlainTextResponse)
def preview_flow_message(gate_id: str):
    """Flow로 나갈 메시지 미리보기 (연동 전 확인용)."""
    return flow.build_message(gates.find(gate_id))


class FlowWebhook(BaseModel):
    text: str | None = None  # 채팅 답장 원문: "진행 a1b2c3" / "수정 a1b2c3 내용"
    gate_id: str | None = None  # 버튼 방식일 때
    action: str | None = None
    comment: str = ""


@app.post("/api/flow/webhook")
def flow_webhook(body: FlowWebhook, x_webhook_secret: str = Header(default="")):
    """Flow(또는 중계 서비스)가 사람의 응답을 전달하는 입구. 원격 조정은 모두 여기로 들어온다."""
    if not config.FLOW_WEBHOOK_SECRET or not hmac.compare_digest(x_webhook_secret, config.FLOW_WEBHOOK_SECRET):
        raise HTTPException(401, "웹훅 인증 실패")
    if body.text:
        parsed = flow.parse_reply(body.text)
        if not parsed:
            return {"result": "ignored", "reason": "명령 형식이 아닙니다"}
        action, gate_id, comment = parsed
    elif body.gate_id and body.action:
        action, gate_id, comment = body.action, body.gate_id, body.comment
    else:
        raise ValueError("text 또는 gate_id+action 이 필요합니다.")
    gate = gates.find(gate_id)
    return workflow.resolve_gate(gate.project_id, gate.id, action, comment, via="flow")


# ── 정적 파일 ─────────────────────────────────────────────

app.mount("/data", StaticFiles(directory=config.DATA_DIR), name="data")
if config.FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=config.FRONTEND_DIST, html=True), name="frontend")
