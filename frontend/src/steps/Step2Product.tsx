import { useEffect, useRef, useState } from "react";
import { api, dataUrl } from "../api";
import { AutoTextarea, ErrorBox, ListEditor } from "../components/common";
import { MAX_IMAGES_PER_KIND } from "../types";
import type { LibraryItem, Product, ProductImage, Project } from "../types";

interface Props {
  project: Project;
  onNext: (p: Project) => void;
}

const MD_TEMPLATE = `# 제품 정보 입력서

---

## 1. 제품명

(제품 이름)

---

## 2. 제품 USP

(제품의 핵심 소구점을 한 문단으로)

---

## 3. 제품 특징

- (특징 1)
- (특징 2)

---

## 4. 사회적·수치적 근거 및 권위

(수치, 성분 함량, 인증, 비교 근거 등 — 광고에 이 표현 그대로 쓰입니다)

---

## 5. 제품 지칭 키워드

(키워드1), (키워드2), (키워드3)

---

## 6. 들어가면 안 되는 표현

없음

---

## 7. 상세페이지 URL

(https://...)

---

## 기타 메모

(선택 — 그 밖에 참고할 내용)
`;

function download(filename: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/markdown;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export default function Step2Product({ project, onNext }: Props) {
  const [product, setProduct] = useState<Product | null>(null);
  const [library, setLibrary] = useState<LibraryItem[]>([]);
  const [selected, setSelected] = useState("");
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const mdRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.getProduct(project.id).then(setProduct);
    api.listLibrary().then(setLibrary);
  }, [project.id]);

  if (!product) return <p className="muted">불러오는 중…</p>;

  const patch = (p: Partial<Product>) => {
    setProduct({ ...product, ...p });
    setDirty(true);
  };

  const run = async (label: string, fn: () => Promise<void>) => {
    setBusy(label);
    setError("");
    setNotice("");
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  };

  const saveFields = async () => {
    const saved = await api.saveProduct(project.id, product);
    setProduct(saved);
    setDirty(false);
    return saved;
  };

  // 서버가 돌려준 이미지 목록만 반영 (입력 중인 텍스트는 유지)
  const mergeImages = (server: Product) => setProduct((cur) => (cur ? { ...cur, images: server.images } : server));

  const uploadImages = (kind: "styled" | "cutout", list: FileList | null) => {
    if (!list || list.length === 0) return;
    const left = MAX_IMAGES_PER_KIND - product.images[kind].length;
    if (list.length > left) {
      setError(`${kind === "styled" ? "연출컷" : "누끼컷"}은 최대 ${MAX_IMAGES_PER_KIND}장까지 넣을 수 있습니다. 지금은 ${left}장만 더 추가할 수 있어요.`);
      return;
    }
    run("이미지 업로드 중", async () => mergeImages(await api.uploadProductImages(project.id, kind, list)));
  };

  const removeImage = (kind: "styled" | "cutout", img: ProductImage) =>
    run("삭제 중", async () => mergeImages(await api.deleteProductImage(project.id, kind, img.id)));

  const setNote = (kind: "styled" | "cutout", id: string, note: string) =>
    patch({ images: { ...product.images, [kind]: product.images[kind].map((i) => (i.id === id ? { ...i, note } : i)) } });

  const loadLibrary = () =>
    run("불러오는 중", async () => {
      if (!selected) return;
      if ((product.name || product.usp) && !confirm("현재 입력한 제품 정보가 저장된 제품으로 바뀝니다. 계속할까요?")) return;
      setProduct(await api.loadFromLibrary(project.id, selected));
      setDirty(false);
      setNotice("저장된 제품 정보를 불러왔습니다.");
    });

  const deleteLibrary = () =>
    run("삭제 중", async () => {
      const item = library.find((l) => l.library_id === selected);
      if (!item || !confirm(`저장된 제품 '${item.name}'을(를) 라이브러리에서 삭제할까요? (이 기획안의 정보는 유지됩니다)`)) return;
      await api.deleteLibraryItem(selected);
      setSelected("");
      setLibrary(await api.listLibrary());
    });

  const saveToLibrary = (overwrite: boolean) =>
    run("저장 중", async () => {
      await saveFields();
      const saved = await api.saveToLibrary(project.id, overwrite);
      setProduct(saved);
      setLibrary(await api.listLibrary());
      setSelected(saved.library_id ?? "");
      setNotice(overwrite ? "제품 라이브러리에 저장했습니다. 다음 기획안에서 불러올 수 있습니다." : "새 제품으로 라이브러리에 저장했습니다.");
    });

  const importMarkdown = (file: File | undefined) =>
    run("md 파일 읽는 중", async () => {
      if (!file) return;
      const res = await api.parseMarkdown(file);
      const f = res.fields;
      setProduct({
        ...product,
        name: f.name || product.name,
        usp: f.usp || product.usp,
        features: f.features?.length ? f.features : product.features,
        evidence: f.evidence || product.evidence,
        keywords: f.keywords?.length ? f.keywords : product.keywords,
        // md에 '없음'으로 적힌 경우 빈 목록이 오므로 그대로 반영
        forbidden_phrases: f.forbidden_phrases ?? product.forbidden_phrases,
        detail_url: f.detail_url || product.detail_url,
        extra: f.extra || product.extra,
      });
      setDirty(true);
      if (res.warning) setError(res.warning);
      else setNotice(`md 파일 내용을 채웠습니다 (${res.method === "claude" ? "Claude 자동 정리" : "템플릿 인식"}). 확인 후 진행하세요.`);
      if (mdRef.current) mdRef.current.value = "";
    });

  const next = () =>
    run("저장 중", async () => {
      await saveFields();
      onNext(await api.confirmProduct(project.id));
    });

  const imageSection = (kind: "styled" | "cutout", title: string, hint: string) => (
    <div className="card">
      <div className="section-head">
        <h3>
          {title}{" "}
          <span className={`count ${product.images[kind].length >= MAX_IMAGES_PER_KIND ? "full" : ""}`}>
            {product.images[kind].length}/{MAX_IMAGES_PER_KIND}
          </span>
        </h3>
        <span className="muted">{hint}</span>
      </div>
      <div className="image-grid">
        {product.images[kind].map((img) => (
          <figure key={img.id} className={`thumb ${kind}`}>
            <img src={dataUrl(project.id, "product", img.path)} alt={img.note} />
            <input value={img.note} placeholder="메모" onChange={(e) => setNote(kind, img.id, e.target.value)} />
            <button className="thumb-del" title="삭제" onClick={() => removeImage(kind, img)}>
              ×
            </button>
          </figure>
        ))}
        {product.images[kind].length < MAX_IMAGES_PER_KIND && (
        <label
          className="thumb add"
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            uploadImages(kind, e.dataTransfer.files);
          }}
        >
          <input type="file" accept="image/png,image/jpeg,image/webp" multiple hidden onChange={(e) => { uploadImages(kind, e.target.files); e.target.value = ""; }} />
          <span>+</span>
          <small>이미지 추가</small>
          <small className="muted">여러 장 선택 가능</small>
        </label>
        )}
      </div>
    </div>
  );

  return (
    <div className="stack">
      {error && <ErrorBox message={error} onClose={() => setError("")} />}
      {notice && <div className="alert ok">{notice}</div>}

      <section className="card toolbar-card">
        <div className="toolbar-group">
          <span className="label">저장된 제품</span>
          <select value={selected} onChange={(e) => setSelected(e.target.value)}>
            <option value="">{library.length ? "선택하세요" : "저장된 제품 없음"}</option>
            {library.map((l) => (
              <option key={l.library_id} value={l.library_id}>
                {l.name}
              </option>
            ))}
          </select>
          <button className="btn small" disabled={!selected || !!busy} onClick={loadLibrary}>
            불러오기
          </button>
          <button className="btn small ghost" disabled={!selected || !!busy} onClick={deleteLibrary}>
            삭제
          </button>
        </div>
        <div className="toolbar-group">
          <span className="label">md 파일로 입력</span>
          <button className="btn small" onClick={() => mdRef.current?.click()} disabled={!!busy}>
            md 파일 선택
          </button>
          <button className="btn small ghost" onClick={() => download("제품정보_입력서_템플릿.md", MD_TEMPLATE)}>
            템플릿 받기
          </button>
          <input ref={mdRef} type="file" accept=".md,.markdown,.txt" hidden onChange={(e) => importMarkdown(e.target.files?.[0])} />
        </div>
      </section>

      <div className="product-layout">
        <section className="card">
          <h3>제품 정보 입력서</h3>
          <label className="field">
            <span>
              1. 제품명 <em>*</em>
            </span>
            <input value={product.name} onChange={(e) => patch({ name: e.target.value })} placeholder="예: 무쿠리셋3" />
          </label>
          <label className="field">
            <span>
              2. 제품 USP <em>*</em>
            </span>
            <AutoTextarea minRows={3} value={product.usp} onChange={(usp) => patch({ usp })} placeholder="제품의 핵심 소구점을 한 문단으로" />
          </label>
          <div className="field">
            <span>3. 제품 특징</span>
            <ListEditor items={product.features} onChange={(features) => patch({ features })} placeholder="특징 입력 후 Enter" />
          </div>
          <label className="field">
            <span>4. 사회적·수치적 근거 및 권위</span>
            <AutoTextarea
              minRows={2}
              value={product.evidence}
              onChange={(evidence) => patch({ evidence })}
              placeholder="수치, 성분 함량, 인증, 비교 근거 — 광고에 이 표현 그대로 쓰입니다"
            />
          </label>
          <div className="field">
            <span>5. 제품 지칭 키워드</span>
            <ListEditor items={product.keywords} onChange={(keywords) => patch({ keywords })} placeholder="예: 아침 3알 다이어트 (Enter)" />
          </div>
          <div className="field">
            <span>6. 들어가면 안 되는 표현</span>
            <ListEditor
              items={product.forbidden_phrases}
              onChange={(forbidden_phrases) => patch({ forbidden_phrases })}
              placeholder="없으면 비워 두세요"
            />
          </div>
          <label className="field">
            <span>7. 상세페이지 URL</span>
            <div className="row">
              <input className="grow" value={product.detail_url} onChange={(e) => patch({ detail_url: e.target.value })} placeholder="https://" />
              {/^https?:\/\//.test(product.detail_url) && (
                <a className="btn small" href={product.detail_url} target="_blank" rel="noreferrer">
                  열기
                </a>
              )}
            </div>
          </label>
          <label className="field">
            <span>기타 메모</span>
            <AutoTextarea minRows={2} value={product.extra} onChange={(extra) => patch({ extra })} placeholder="선택" />
          </label>
        </section>

        <div className="stack">
          {imageSection("styled", "제품 연출컷", "사용 장면·분위기 컷 · 최대 5장")}
          {imageSection("cutout", "제품 누끼컷", "배경 제거된 PNG 권장 · 최대 5장")}
        </div>
      </div>

      <footer className="action-bar">
        <span className="muted">
          {product.library_id ? "라이브러리에 저장된 제품입니다" : "한 번 저장하면 다음 기획안에서 다시 입력할 필요가 없습니다"}
          {dirty && " · 수정한 내용이 있습니다"}
        </span>
        <div className="row">
          {product.library_id ? (
            <>
              <button className="btn" disabled={!!busy} onClick={() => saveToLibrary(true)}>
                라이브러리 업데이트
              </button>
              <button className="btn ghost" disabled={!!busy} onClick={() => saveToLibrary(false)}>
                새 제품으로 저장
              </button>
            </>
          ) : (
            <button className="btn" disabled={!!busy} onClick={() => saveToLibrary(false)}>
              제품 저장
            </button>
          )}
          <button className="btn primary" disabled={!!busy} onClick={next}>
            {busy || "진행 →"}
          </button>
        </div>
      </footer>
    </div>
  );
}
