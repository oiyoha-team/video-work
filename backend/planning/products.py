"""Step 2: 제품 정보 — 프로젝트별 작업본 + 재사용 가능한 제품 라이브러리 + md 파싱.

프로젝트에는 항상 제품 '스냅샷'(projects/{id}/product/)을 둔다.
라이브러리(data/products/{library_id}/)를 나중에 수정해도 과거 기획안은 바뀌지 않는다.
"""
import io
import re
import shutil
import tempfile
import uuid
import zipfile
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
    _sync_images_to_library(project_id, product)
    return product


def remove_image(project_id: str, kind: str, image_id: str) -> Product:
    product = store.get_product(project_id)
    images: list[ProductImage] = getattr(product.images, kind)
    for img in [i for i in images if i.id == image_id]:
        (store.product_dir(project_id) / img.path).unlink(missing_ok=True)
        images.remove(img)
    store.save_product(project_id, product)
    _sync_images_to_library(project_id, product)
    return product


def _sync_images_to_library(project_id: str, product: Product) -> None:
    """템플릿을 쓰는 중이면 이미지 추가·삭제를 템플릿에도 바로 반영한다 (글 내용은 [템플릿에 저장] 때만)."""
    if not product.library_id:
        return
    lib = _library_dir(product.library_id)
    path = lib / "product.json"
    if not path.exists():
        return
    for kind in ("styled", "cutout"):
        src = store.product_dir(project_id) / kind
        shutil.rmtree(lib / kind, ignore_errors=True)
        if src.exists():
            shutil.copytree(src, lib / kind)
    saved = Product.model_validate(store.read_json(path))
    saved.images = product.images.model_copy(deep=True)
    store.write_json(path, saved)


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
            out.append({
                "library_id": path.parent.name,
                "name": p.template_name or p.name,  # 템플릿 이름 (없으면 제품명)
                "product_name": p.name,
                "updated_at": path.stat().st_mtime,
            })
        except Exception:
            continue
    # 템플릿 이름 순 (템플릿1, 템플릿2 … 순서가 유지되도록 숫자는 숫자로 비교)
    return sorted(out, key=lambda x: _natural_key(x["name"]))


def _natural_key(s: str) -> list:
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def _next_template_name() -> str:
    used = {item["name"] for item in list_library()}
    n = 1
    while f"템플릿{n}" in used:
        n += 1
    return f"템플릿{n}"


def rename_template(library_id: str, name: str) -> dict:
    name = name.strip()
    if not name:
        raise ValueError("템플릿 이름을 입력하세요.")
    path = _library_dir(library_id) / "product.json"
    if not path.exists():
        raise FileNotFoundError(library_id)
    product = Product.model_validate(store.read_json(path))
    product.template_name = name
    store.write_json(path, product)
    return {"library_id": library_id, "name": name}


def _copy_tree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def save_to_library(project_id: str, overwrite: bool, template_name: str = "") -> Product:
    product = store.get_product(project_id)
    if not product.name.strip():
        raise ValueError("제품명을 입력해야 저장할 수 있습니다.")
    if overwrite and product.library_id and _library_dir(product.library_id).exists():
        library_id = product.library_id
        # 다른 곳에서 이름을 바꿨을 수 있으므로 템플릿의 현재 이름을 유지
        current = Product.model_validate(store.read_json(_library_dir(library_id) / "product.json"))
        product.template_name = template_name.strip() or current.template_name or product.template_name
    else:
        library_id = uuid.uuid4().hex[:10]
        product.template_name = template_name.strip() or _next_template_name()
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


# ── 제품 정보 묶음 (md + 이미지) ─────────────────────────────────────────────

BUNDLE_FOLDERS = {"styled": "연출컷", "cutout": "누끼컷"}


def product_to_markdown(p: Product) -> str:
    """제품 정보 입력서 양식(md). 화면의 '현재 내용 받기'와 같은 형식."""
    def items(values: list[str], bullet: bool) -> str:
        if not values:
            return "없음"
        return "\n".join(f"- {v}" for v in values) if bullet else ", ".join(values)

    sections = [
        ("1. 제품명", p.name),
        ("2. 제품 USP", p.usp),
        ("3. 제품 특징", items(p.features, True)),
        ("4. 사회적·수치적 근거 및 권위", p.evidence),
        ("5. 제품 지칭 키워드", items(p.keywords, False)),
        ("6. 들어가면 안 되는 표현", items(p.forbidden_phrases, False)),
        ("7. 상세페이지 URL", p.detail_url),
    ]
    if p.extra.strip():
        sections.append(("기타 메모", p.extra))
    return "# 제품 정보 입력서\n\n" + "\n".join(f"---\n\n## {h}\n\n{(v or '').strip() or '없음'}\n" for h, v in sections)


def export_bundle(project_id: str) -> Path:
    """md 1개 + 연출컷/·누끼컷/ 폴더를 ZIP 하나로. 다시 올리면 글과 이미지가 함께 채워진다."""
    product = store.get_product(project_id)
    pdir = store.product_dir(project_id)
    fd, name = tempfile.mkstemp(suffix=".zip")
    import os
    os.close(fd)
    with zipfile.ZipFile(name, "w") as zf:
        zf.writestr("제품정보.md", product_to_markdown(product))
        for kind, folder in BUNDLE_FOLDERS.items():
            for n, img in enumerate(getattr(product.images, kind), 1):
                src = pdir / img.path
                if src.exists():
                    note = re.sub(r'[\\/:*?"<>|\s]+', "_", img.note).strip("._")
                    zf.write(src, f"{folder}/{n:02d}{'_' + note if note else ''}{src.suffix}", compress_type=zipfile.ZIP_STORED)
    return Path(name)


def _decode(raw: bytes) -> str:
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp949", errors="replace")


def import_bundle(project_id: str, filename: str, data: bytes) -> dict:
    """md 또는 ZIP(md + 연출컷/·누끼컷/ 폴더)을 읽는다. 글은 화면에 채울 값으로 돌려주고, 이미지는 바로 추가한다."""
    if not filename.lower().endswith(".zip"):
        return {**parse_markdown(_decode(data)), "images_added": 0, "images_skipped": 0}

    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise ValueError("ZIP 파일을 열 수 없습니다.") from e
    names = [n for n in zf.namelist() if not n.endswith("/")]
    md_name = next((n for n in names if n.lower().endswith((".md", ".markdown", ".txt"))), None)
    result = parse_markdown(_decode(zf.read(md_name))) if md_name else {"fields": {}, "method": "none"}

    added = skipped = 0
    for n in names:
        if Path(n).suffix.lower() not in IMAGE_EXTS:
            continue
        kind = "cutout" if "누끼" in n or "cutout" in n.lower() else "styled" if "연출" in n or "styled" in n.lower() else None
        if kind is None:
            skipped += 1
            continue
        if len(getattr(store.get_product(project_id).images, kind)) >= MAX_IMAGES_PER_KIND:
            skipped += 1
            continue
        stem = re.sub(r"^\d+_?", "", Path(n).stem) or Path(n).stem
        add_image(project_id, kind, stem + Path(n).suffix, zf.read(n))
        added += 1
    return {**result, "images_added": added, "images_skipped": skipped}
