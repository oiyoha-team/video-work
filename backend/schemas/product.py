from pydantic import BaseModel, Field, field_validator

MAX_IMAGES_PER_KIND = 5  # 연출컷·누끼컷 각각 최대 장수


class ProductImage(BaseModel):
    id: str
    path: str  # 제품 폴더 기준 상대경로 (styled/xxx.jpg)
    note: str = ""


class ProductImages(BaseModel):
    styled: list[ProductImage] = Field(default_factory=list)  # 연출컷
    cutout: list[ProductImage] = Field(default_factory=list)  # 누끼컷


class Product(BaseModel):
    """제품 정보 입력서(md) 양식과 같은 순서의 필드."""

    library_id: str | None = None  # 라이브러리에 저장된 경우의 id
    name: str = ""  # 1. 제품명
    usp: str = ""  # 2. 제품 USP (문단)
    features: list[str] = Field(default_factory=list)  # 3. 제품 특징
    evidence: str = ""  # 4. 사회적·수치적 근거 및 권위
    keywords: list[str] = Field(default_factory=list)  # 5. 제품 지칭 키워드
    forbidden_phrases: list[str] = Field(default_factory=list)  # 6. 들어가면 안 되는 표현
    detail_url: str = ""  # 7. 상세페이지 URL
    extra: str = ""  # 기타 메모
    images: ProductImages = Field(default_factory=ProductImages)

    @field_validator("usp", mode="before")
    @classmethod
    def _usp_from_list(cls, v):
        # 이전 버전에서 저장한 제품(USP 목록)도 불러올 수 있게
        return "\n".join(v) if isinstance(v, list) else v
