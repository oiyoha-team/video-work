import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { SCENE_DETAIL } from "../labels";
import type { JobState, SceneDetail } from "../types";

/** 내용 길이에 맞춰 높이가 늘어나는 textarea */
export function AutoTextarea({
  value,
  onChange,
  placeholder,
  disabled,
  className,
  minRows = 1,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  disabled?: boolean;
  className?: string;
  minRows?: number;
}) {
  const ref = useRef<HTMLTextAreaElement>(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight + 2}px`;
  }, [value]);
  return (
    <textarea
      ref={ref}
      className={className}
      rows={minRows}
      value={value}
      placeholder={placeholder}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}

/** 장면 상세 7개 항목 편집기 (읽기 전용으로도 사용) */
export function SceneDetailEditor({
  detail,
  onChange,
  disabled,
}: {
  detail: SceneDetail;
  onChange?: (d: SceneDetail) => void;
  disabled?: boolean;
}) {
  return (
    <div className="detail-grid">
      {(Object.keys(SCENE_DETAIL) as (keyof SceneDetail)[]).map((key) => (
        <label key={key} className="detail-field">
          <span>{SCENE_DETAIL[key]}</span>
          {onChange ? (
            <AutoTextarea value={detail[key] ?? ""} disabled={disabled} onChange={(v) => onChange({ ...detail, [key]: v })} placeholder="-" />
          ) : (
            <span className="detail-value">{detail[key] || "-"}</span>
          )}
        </label>
      ))}
    </div>
  );
}

/** 문자열 목록 편집기 (USP, 특징, 금지 표현 등) */
export function ListEditor({
  items,
  onChange,
  placeholder,
}: {
  items: string[];
  onChange: (items: string[]) => void;
  placeholder?: string;
}) {
  const [draft, setDraft] = useState("");
  const add = () => {
    const v = draft.trim();
    if (!v) return;
    onChange([...items, v]);
    setDraft("");
  };
  return (
    <div className="list-editor">
      {items.map((item, i) => (
        <div key={i} className="list-row">
          <span className="list-num">{i + 1}</span>
          <AutoTextarea className="grow" value={item} onChange={(v) => onChange(items.map((x, j) => (j === i ? v : x)))} />
          <button className="icon-btn" title="삭제" onClick={() => onChange(items.filter((_, j) => j !== i))}>
            ×
          </button>
        </div>
      ))}
      <div className="list-row">
        <span className="list-num">+</span>
        <input
          value={draft}
          placeholder={placeholder}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.nativeEvent.isComposing) {
              e.preventDefault();
              add();
            }
          }}
        />
        <button className="btn small" onClick={add} disabled={!draft.trim()}>
          추가
        </button>
      </div>
    </div>
  );
}

export function JobProgress({ job, title }: { job: JobState; title: string }) {
  return (
    <div className="job-card">
      <div className="spinner" />
      <div className="job-body">
        <strong>{title}</strong>
        <div className="muted">{job.message || "처리 중"}</div>
        <div className="progress">
          <div className="progress-bar" style={{ width: `${Math.round(job.progress * 100)}%` }} />
        </div>
      </div>
    </div>
  );
}

export function ErrorBox({ message, onClose }: { message: string; onClose?: () => void }) {
  return (
    <div className="alert error with-close">
      <span>{message}</span>
      {onClose && (
        <button className="icon-btn" onClick={onClose}>
          ×
        </button>
      )}
    </div>
  );
}

/** 값이 바뀐 뒤 delay ms 동안 추가 변경이 없으면 실행 */
export function useDebouncedEffect(fn: () => void, deps: unknown[], delay: number) {
  const first = useRef(true);
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    const t = setTimeout(fn, delay);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
}
