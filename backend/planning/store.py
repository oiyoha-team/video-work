"""프로젝트 폴더 입출력. 모든 산출물은 data/projects/{id}/ 아래 JSON으로 저장된다."""
import json
import shutil
import threading
import uuid
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

from config import PROJECTS_DIR
from schemas import Gate, Product, Production, Project, ReferenceAnalysis, Script

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def lock(project_id: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(project_id, threading.Lock())


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def project_dir(project_id: str) -> Path:
    # id는 우리가 생성한 hex 문자열만 허용 (경로 탈출 방지)
    if not project_id.isalnum():
        raise FileNotFoundError(project_id)
    return PROJECTS_DIR / project_id


def reference_dir(project_id: str) -> Path:
    return project_dir(project_id) / "reference"


def product_dir(project_id: str) -> Path:
    return project_dir(project_id) / "product"


def write_json(path: Path, data: BaseModel | dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = data.model_dump_json(indent=2) if isinstance(data, BaseModel) else json.dumps(data, ensure_ascii=False, indent=2)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


# ── project.json ─────────────────────────────────────────────

def create_project(name: str) -> Project:
    pid = uuid.uuid4().hex[:12]
    ts = now()
    project = Project(id=pid, name=name or "새 기획안", created_at=ts, updated_at=ts)
    write_json(project_dir(pid) / "project.json", project)
    return project


def list_projects() -> list[Project]:
    out = []
    for p in PROJECTS_DIR.glob("*/project.json"):
        try:
            out.append(Project.model_validate(read_json(p)))
        except Exception:
            continue
    return sorted(out, key=lambda x: x.updated_at, reverse=True)


def get_project(project_id: str) -> Project:
    path = project_dir(project_id) / "project.json"
    if not path.exists():
        raise FileNotFoundError(project_id)
    return Project.model_validate(read_json(path))


def save_project(project: Project) -> Project:
    project.updated_at = now()
    write_json(project_dir(project.id) / "project.json", project)
    return project


def update_project(project_id: str, **changes) -> Project:
    with lock(project_id):
        project = get_project(project_id)
        for key, value in changes.items():
            setattr(project, key, value)
        return save_project(project)


def delete_project(project_id: str) -> None:
    shutil.rmtree(project_dir(project_id), ignore_errors=True)


# ── 단계별 산출물 ─────────────────────────────────────────────

def get_analysis(project_id: str) -> ReferenceAnalysis | None:
    path = reference_dir(project_id) / "analysis.json"
    return ReferenceAnalysis.model_validate(read_json(path)) if path.exists() else None


def save_analysis(project_id: str, analysis: ReferenceAnalysis) -> None:
    write_json(reference_dir(project_id) / "analysis.json", analysis)
    save_scene_analysis(project_id, analysis)


def save_scene_analysis(project_id: str, analysis: ReferenceAnalysis) -> None:
    """레퍼런스 장면 분석만 따로 저장한다 → 영상 제작 단계에서 이미지를 만들 때 사용.

    기획안(script.json)에는 대사만 두고, 화면 정보는 이 파일을 ref_segment(=index)로 찾아 쓴다.
    """
    scenes = {
        "visual_style": analysis.overall.visual_style,
        "aspect_ratio": analysis.source.detected_aspect_ratio,
        "scenes": [
            {
                "index": s.index,
                "start": s.start,
                "end": s.end,
                "frames": [f"reference/{f}" for f in s.frames],  # 프로젝트 폴더 기준
                "shot_type": s.shot_type,
                "scene": s.scene,
                "detail": s.detail.model_dump(),
            }
            for s in analysis.segments
        ],
    }
    write_json(project_dir(project_id) / "scene_analysis" / "scenes.json", scenes)


def get_scene_analysis(project_id: str) -> dict | None:
    path = project_dir(project_id) / "scene_analysis" / "scenes.json"
    return read_json(path) if path.exists() else None


def get_product(project_id: str) -> Product:
    path = product_dir(project_id) / "product.json"
    return Product.model_validate(read_json(path)) if path.exists() else Product()


def save_product(project_id: str, product: Product) -> None:
    write_json(product_dir(project_id) / "product.json", product)


def get_script(project_id: str) -> Script | None:
    path = project_dir(project_id) / "script.json"
    return Script.model_validate(read_json(path)) if path.exists() else None


def save_script(project_id: str, script: Script) -> None:
    write_json(project_dir(project_id) / "script.json", script)


def get_production(project_id: str) -> Production:
    path = project_dir(project_id) / "production.json"
    return Production.model_validate(read_json(path)) if path.exists() else Production()


def save_production(project_id: str, production: Production) -> None:
    write_json(project_dir(project_id) / "production.json", production)


def get_gates(project_id: str) -> list[Gate]:
    path = project_dir(project_id) / "gates.json"
    return [Gate.model_validate(g) for g in read_json(path)] if path.exists() else []


def save_gates(project_id: str, gates: list[Gate]) -> None:
    write_json(project_dir(project_id) / "gates.json", [g.model_dump() for g in gates])


def get_chat(project_id: str) -> list[dict]:
    path = project_dir(project_id) / "chat.json"
    return read_json(path) if path.exists() else []


def save_chat(project_id: str, messages: list[dict]) -> None:
    write_json(project_dir(project_id) / "chat.json", messages)
