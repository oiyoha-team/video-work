import { useEffect, useMemo, useState } from "react";
import { api, dataUrl, zipUrl } from "../api";
import { ErrorBox } from "../components/common";
import type { ExportItem, ExportList, Project } from "../types";

interface Props {
  project: Project;
}

function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

const basename = (f: string) => f.split("/").pop() ?? f;

export default function Step6Download({ project }: Props) {
  const [data, setData] = useState<ExportList | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [error, setError] = useState("");

  useEffect(() => {
    api.exportList(project.id).then(setData).catch((e) => setError((e as Error).message));
  }, [project.id]);

  const byGroup = useMemo(() => {
    const m: Record<string, ExportItem[]> = {};
    data?.items.forEach((it) => (m[it.group] ??= []).push(it));
    return m;
  }, [data]);

  if (error) return <ErrorBox message={error} />;
  if (!data) return <p className="muted">불러오는 중…</p>;

  const all = data.items;
  const totalSize = all.reduce((n, it) => n + it.size, 0);
  const picked = all.filter((it) => selected.has(it.key));
  const pickedSize = picked.reduce((n, it) => n + it.size, 0);

  const toggle = (keys: string[], on: boolean) =>
    setSelected((cur) => {
      const next = new Set(cur);
      keys.forEach((k) => (on ? next.add(k) : next.delete(k)));
      return next;
    });

  return (
    <div className="stack">
      {!project.completed && (
        <div className="alert warn">영상 제작이 아직 확정되지 않았습니다. 지금 받는 파일은 작업 중인 결과물입니다.</div>
      )}

      <section className="card export-head">
        <div>
          <h2>편집용 결과물</h2>
          <p className="muted">
            장면별 영상 클립과 음성, 타임라인·자막 초안을 받아 편집 툴에서 직접 완성하세요. 전체 {all.length}개 · {fmtSize(totalSize)}
          </p>
        </div>
        <div className="row wrap">
          <a className={`btn ${picked.length ? "" : "disabled"}`} href={picked.length ? zipUrl(project.id, picked.map((p) => p.key)) : undefined}>
            선택 항목 ZIP ({picked.length}개{picked.length ? ` · ${fmtSize(pickedSize)}` : ""})
          </a>
          <a className="btn primary" href={zipUrl(project.id, null)}>
            전체 ZIP 다운로드
          </a>
        </div>
      </section>

      <div className="alert ok tip">
        <b>timeline.csv</b>에 장면 순서, 시작·끝 시간, 대사, 파일 이름이 정리되어 있습니다. ZIP 안의 파일은 <code>scene01</code>, <code>scene02</code> … 처럼
        장면 순서대로 이름이 붙어 있어 편집 툴 타임라인에 그대로 배치하면 됩니다.
      </div>

      <div className="export-grid">
        {data.groups.map((g) => {
          const items = byGroup[g.key] ?? [];
          if (!items.length) return null;
          const keys = items.map((it) => it.key);
          const allOn = keys.every((k) => selected.has(k));
          const someOn = !allOn && keys.some((k) => selected.has(k));
          return (
            <section key={g.key} className="card export-group">
              <header className="export-group-head">
                <label className="check">
                  <input
                    type="checkbox"
                    checked={allOn}
                    ref={(el) => {
                      if (el) el.indeterminate = someOn;
                    }}
                    onChange={(e) => toggle(keys, e.target.checked)}
                  />
                  <strong>{g.label}</strong>
                </label>
                <span className="muted small">
                  {items.length}개 · {fmtSize(items.reduce((n, it) => n + it.size, 0))}
                </span>
                <a className="btn small ghost push" href={zipUrl(project.id, keys)}>
                  이 묶음만 ZIP
                </a>
              </header>
              <ul className="export-list">
                {items.map((it) => (
                  <li key={it.key} className={selected.has(it.key) ? "on" : ""}>
                    <label className="check grow">
                      <input type="checkbox" checked={selected.has(it.key)} onChange={(e) => toggle([it.key], e.target.checked)} />
                      {it.group === "images" && <img className="export-thumb" src={dataUrl(project.id, it.path)} alt="" loading="lazy" />}
                      {it.group === "clips" && <video className="export-thumb" src={dataUrl(project.id, it.path)} preload="metadata" muted />}
                      <span className="export-name">
                        <span>{basename(it.filename)}</span>
                        <span className="muted small">{it.label}</span>
                      </span>
                    </label>
                    {it.group === "audio" && <audio controls preload="none" src={dataUrl(project.id, it.path)} />}
                    <span className="muted small size">{fmtSize(it.size)}</span>
                    <a className="btn small" href={dataUrl(project.id, it.path)} download={basename(it.filename)}>
                      받기
                    </a>
                  </li>
                ))}
              </ul>
            </section>
          );
        })}
      </div>
    </div>
  );
}
