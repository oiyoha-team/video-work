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

// ── 진행 표시 (로딩바 · 경과 시간 · 남은 시간) ─────────────────────────────────────────────

/** 1초마다 다시 그리기 위한 현재 시각 (epoch 초) */
export function useNow(active = true, intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    if (!active) return;
    setNow(Date.now() / 1000);
    const t = setInterval(() => setNow(Date.now() / 1000), intervalMs);
    return () => clearInterval(t);
  }, [active, intervalMs]);
  return now;
}

export function fmtDur(sec: number): string {
  const s = Math.max(0, Math.round(sec));
  if (s < 60) return `${s}초`;
  const m = Math.floor(s / 60);
  const r = s % 60;
  return r && m < 10 ? `${m}분 ${r}초` : `${m}분`;
}

/** "약 1분 ~ 3분" / "약 40초 이내" — 남은 시간 범위 */
export function etaRange(lo: number, hi: number): string {
  if (hi <= 5) return "곧 끝납니다";
  const a = fmtDur(Math.max(lo, 0));
  const b = fmtDur(hi);
  return a === b || lo <= 0 ? `약 ${b} 이내` : `약 ${a} ~ ${b}`;
}

export function jobTiming(job: JobState, now: number) {
  const elapsed = job.started_at ? now - job.started_at : 0;
  if (job.eta_min == null || job.eta_max == null) return { elapsed, eta: "", fraction: job.progress || 0, known: !!job.progress };
  // 서버가 남은 시간을 계산한 뒤 흐른 시간만큼 줄인다
  const since = job.eta_at ? now - job.eta_at : 0;
  const lo = job.eta_min - since;
  const hi = job.eta_max - since;
  const mid = Math.max((lo + hi) / 2, 3);
  // 경과 시간 대비 남은 시간으로 막대를 채운다 (끝날 때까지 97%에서 멈춤)
  const timeFrac = elapsed > 0 ? elapsed / (elapsed + mid) : 0;
  const fraction = Math.min(0.97, Math.max(job.progress || 0, timeFrac));
  return { elapsed, eta: hi <= 0 ? "거의 다 됐습니다 (예상보다 오래 걸리는 중)" : etaRange(lo, hi), fraction, known: true };
}

/** 로딩바 + 진행 문구 + 경과 시간 + 남은 시간 */
export function ProgressLine({ job }: { job: JobState }) {
  const now = useNow(job.status === "running");
  const t = jobTiming(job, now);
  return (
    <div className="progress-line">
      <div className={`progress ${t.known ? "" : "indeterminate"}`}>
        <div className="progress-bar" style={t.known ? { width: `${Math.round(t.fraction * 100)}%` } : undefined} />
      </div>
      <div className="progress-meta small">
        <span className="spinner tiny" />
        <span>{job.message || "처리 중"}</span>
        {job.total ? <span className="muted">· {job.done}/{job.total}</span> : null}
        <span className="push" />
        {t.elapsed > 1 && <span className="muted">경과 {fmtDur(t.elapsed)}</span>}
        {t.eta && <b className="eta">남은 시간 {t.eta}</b>}
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
        <ProgressLine job={job} />
      </div>
    </div>
  );
}

// ── 오류 (원인 · 해결 방법 · 원문) ─────────────────────────────────────────────

const RAW_MARK = "\n[원문] ";

/** 서버 오류 문구 "무엇 실패\n원인: …\n해결: …\n[원문] …"을 나눠 보여 준다 */
export function ErrorText({ message }: { message: string }) {
  const [main, ...rest] = message.split(RAW_MARK);
  const raw = rest.join(RAW_MARK);
  return (
    <div className="error-text">
      {main.split("\n").map((line, i) => {
        const m = line.match(/^(.*?)(원인|해결):\s*(.*)$/);
        if (m && !m[1].trim())
          return (
            <div key={i}>
              <b>{m[2]}</b> {m[3]}
            </div>
          );
        return (
          <div key={i} className={i === 0 ? "error-head" : ""}>
            {line}
          </div>
        );
      })}
      {raw && (
        <details className="error-raw">
          <summary>오류 원문 보기</summary>
          <code>{raw}</code>
        </details>
      )}
    </div>
  );
}

export function ErrorBox({ message, onClose }: { message: string; onClose?: () => void }) {
  return (
    <div className="alert error with-close">
      <ErrorText message={message} />
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
