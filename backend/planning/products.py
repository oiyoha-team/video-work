"""Step 2: 제품 정보 — 프로젝트별 작업본 + 재사용 가능한 제품 라이브러리 + md 파싱.

프로젝트에는 항상 제품 '스냅샷'(projects/{id}/product/)을 둔다.
라이브러리(data/products/{library_id}/)를 나중에 수정해도 과거 기획안은 바뀌지 않는다.
"""
import re
import shutil
import uuid
from pathlib import Path

from config import PRODUCTS_DIR
from llm import claude_client
from llm.claude_client import strict_object
from schemas import Product, ProductImage
from schemas.product import MAX_IMAGES_PER_KIND

from . import store

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


# ── 이미지 ─────────────────────────────────────────────

KIND_LABELS = {"styled": "연출컷", "cutout": "누끼컷"}


def check_upload(project_id: str, kind: str, filenames: list[str]) -> None:
    """저장 전에 종류·형식·장수(각 최대 5장)를 한꺼번에 확인한다 (일부만 올라가는 일이 없도록)."""
    if kind not in KIND_LABELS:
        raise ValueError("kind는 styled 또는 cutout 이어야 합니다.")
    for name in filenames:
        ext = Path(name).suffix.lower()
        if ext not in IMAGE_EXTS:
            raise ValueError(f"지원하지 않는 이미지 형식입니다: {name} (jpg / png / webp)")
    have = len(getattr(store.get_product(project_id).images, kind))
    if have + len(filenames) > MAX_IMAGES_PER_KIND:
        left = MAX_IMAGES_PER_KIND - have
        status = "이미 모두 찼습니다. 기존 이미지를 지운 뒤 추가하세요." if left <= 0 else f"지금은 {left}장만 더 추가할 수 있습니다."
        raise ValueError(f"{KIND_LABELS[kind]}은 최대 {MAX_IMAGES_PER_KIND}장까지 넣을 수 있습니다. {status}")


def add_image(project_id: str, kind: str, filename: str, data: bytes) -> Product:
    check_upload(project_id, kind, [filename])
    ext = Path(filename).suffix.lower()
    product = store.get_product(project_id)
    image_id = uuid.uuid4().hex[:8]
    rel = f"{kind}/{image_id}{ext}"
    out = store.product_dir(project_id) / rel
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    getattr(product.images, kind).append(ProductImage(id=image_id, path=rel, note=Path(filename).stem))
    store.save_product(project_id, product)
    return product


def remove_image(project_id: str, kind: str, image_id: str) -> Product:
    product = store.get_product(project_id)
    images: list[ProductImage] = getattr(product.images, kind)
    for img in [i for i in images if i.id == image_id]:
        (store.product_dir(project_id) / img.path).unlink(missing_ok=True)
        images.remove(img)
    store.save_product(project_id, product)
    return product


def update_fields(project_id: str, incoming: Product) -> Product:
    """텍스트 필드만 갱신 (이미지 목록은 업로드/삭제 API로만 변경)."""
    product = store.get_product(project_id)
    data = incoming.model_dump(exclude={"images", "library_id"})
    for key, value in data.items():
        setattr(product, key, value)
    for kind in ("styled", "cutout"):
        notes = {i.id: i.note for i in getattr(incoming.images, kind)}
        for img in getattr(product.images, kind):
            img.note = notes.get(img.id, img.note)
    store.save_product(project_id, product)
    return product


# ── 라이브러리 ─────────────────────────────────────────────

def _library_dir(library_id: str) -> Path:
    if not library_id.isalnum():
        raise FileNotFoundError(library_id)
    return PRODUCTS_DIR / library_id


def list_library() -> list[dict]:
    out = []
    for path in PRODUCTS_DIR.glob("*/product.json"):
        try:
            p = Product.model_validate(store.read_json(path))
            out.append({"library_id": path.parent.name, "name": p.name, "updated_at": path.stat().st_mtime})
        except Exception:
            continue
    return sorted(out, key=lambda x: x["updated_at"], reverse=True)


def _copy_tree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def save_to_library(project_id: str, overwrite: bool) -> Product:
    product = store.get_product(project_id)
    if not product.name.strip():
        raise ValueError("제품명을 입력해야 저장할 수 있습니다.")
    if overwrite and product.library_id and _library_dir(product.library_id).exists():
        library_id = product.library_id
    else:
        library_id = uuid.uuid4().hex[:10]
    product.library_id = library_id
    store.save_product(project_id, product)
    _copy_tree(store.product_dir(project_id), _library_dir(library_id))
    return product


def load_from_library(project_id: str, library_id: str) -> Product:
    src = _library_dir(library_id)
    if not (src / "product.json").exists():
        raise FileNotFoundError(library_id)
    _copy_tree(src, store.product_dir(project_id))
    product = store.get_product(project_id)
    product.library_id = library_id
    store.save_product(project_id, product)
    return product


def delete_from_library(library_id: str) -> None:
    shutil.rmtree(_library_dir(library_id), ignore_errors=True)


# ── md 파싱 ─────────────────────────────────────────────
# 기준 양식: product_template.md (제품 정보 입력서)
#   ## 1. 제품명 / ## 2. 제품 USP / ## 3. 제품 특징 / ## 4. 사회적·수치적 근거 및 권위
#   ## 5. 제품 지칭 키워드 / ## 6. 들어가면 안 되는 표현 / ## 7. 상세페이지 URL / ## 기타 메모

# 헤딩 키워드 → 필드. 위에서부터 먼저 매칭되는 것을 사용 (구체적인 것을 앞에)
SECTION_KEYS = [
    ("forbidden_phrases", ["들어가면 안", "안 되는 표현", "안되는 표현", "금지", "주의", "심의", "forbidden"]),
    ("evidence", ["근거", "권위", "수치", "인증", "임상", "evidence"]),
    ("keywords", ["지칭", "키워드", "keyword"]),
    ("detail_url", ["상세페이지", "url", "링크", "link"]),
    ("usp", ["usp", "소구", "강점", "셀링", "차별"]),
    ("features", ["특징", "스펙", "성분", "기능", "feature", "spec"]),
    ("name", ["제품명", "상품명", "product name", "name"]),
    ("extra", ["기타", "메모", "참고", "note", "etc"]),
]
LIST_FIELDS = {"features", "keywords", "forbidden_phrases"}
COMMA_LIST_FIELDS = {"keywords", "forbidden_phrases"}  # 한 줄에 쉼표로 나열해도 항목으로 나눈다
EMPTY_VALUES = {"없음", "없습니다", "해당 없음", "none", "n/a", "-"}


def _match_section(heading: str) -> str | None:
    h = heading.lower()
    for field, keys in SECTION_KEYS:
        if any(k in h for k in keys):
            return field
    return None


def _bullets(lines: list[str], split_commas: bool) -> list[str]:
    items = []
    for line in lines:
        s = re.sub(r"^\s*(?:[-*+•]|\d+[.)])\s+", "", line).strip()
        parts = [x.strip() for x in re.split(r"[,，、]", s)] if split_commas else [s]
        items += [x for x in parts if x and x.lower() not in EMPTY_VALUES]
    return items


def parse_markdown_rules(md: str) -> tuple[dict, bool]:
    """규칙 기반 파싱. (필드 dict, 알려진 섹션을 하나라도 찾았는지)"""
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for raw in md.splitlines():
        if re.match(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$", raw):  # 구분선
            continue
        m = re.match(r"^\s*#{1,6}\s+(.+?)\s*#*\s*$", raw)
        if m:
            current = _match_section(m.group(1).strip())
            if current:
                sections.setdefault(current, [])
            continue
        # "제품명: 무쿠리셋3" 같은 한 줄 형식도 지원
        kv = re.match(r"^\s*(?:[-*]\s*)?\**([^:：*]{1,20})\**\s*[:：]\s*(.+)$", raw)
        if kv and (field := _match_section(kv.group(1))) and field not in LIST_FIELDS:
            sections.setdefault(field, []).append(kv.group(2))
            continue
        if current and raw.strip():
            sections[current].append(raw)

    out: dict = {}
    for field, lines in sections.items():
        if field in LIST_FIELDS:
            out[field] = _bullets(lines, field in COMMA_LIST_FIELDS)
        else:
            text = "\n".join(line.strip() for line in lines if line.strip())
            out[field] = "" if text.lower() in EMPTY_VALUES else text
    for one_line in ("name", "detail_url"):
        if out.get(one_line):
            out[one_line] = out[one_line].splitlines()[0].strip()
    return out, bool(sections)


MD_SYSTEM = """당신은 마케팅 문서에서 제품 정보를 정리하는 도우미입니다.
주어진 문서에서 아래 항목을 추출하세요. 문서에 없는 내용은 지어내지 말고 빈 값으로 두세요. 모든 값은 한국어로.
- name: 제품명
- usp: 제품 USP (핵심 소구점, 문단 그대로)
- features: 제품 특징 (항목별)
- evidence: 사회적·수치적 근거 및 권위 (수치·인증·성분 함량 등, 원문 그대로)
- keywords: 제품을 부르는 지칭 키워드 (항목별)
- forbidden_phrases: 광고에 들어가면 안 되는 표현 (항목별)
- detail_url: 상세페이지 URL
- extra: 그 밖의 메모"""


def parse_markdown(md: str) -> dict:
    """md → 제품 필드 dict. 정해진 헤딩이 없으면 Claude로 구조화(연결된 경우)."""
    fields, found = parse_markdown_rules(md)
    if found:
        return {"fields": fields, "method": "rules"}
    if claude_client.is_configured():
        schema = strict_object({
            "name": {"type": "string"},
            "usp": {"type": "string"},
            "features": {"type": "array", "items": {"type": "string"}},
            "evidence": {"type": "string"},
            "keywords": {"type": "array", "items": {"type": "string"}},
            "forbidden_phrases": {"type": "array", "items": {"type": "string"}},
            "detail_url": {"type": "string"},
            "extra": {"type": "string"},
        })
        result = claude_client.json_call(MD_SYSTEM, [{"role": "user", "content": md}], schema, max_tokens=8000, effort="low")
        return {"fields": result, "method": "claude"}
    fields.setdefault("extra", md.strip())
    return {
        "fields": fields,
        "method": "fallback",
        "warning": "양식의 제목(## 1. 제품명, ## 2. 제품 USP …)을 찾지 못해 전체 내용을 '기타 메모'에 넣었습니다. 템플릿 양식을 사용하거나 Claude API를 연결하세요.",
    }
