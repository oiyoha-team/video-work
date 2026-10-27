import { useEffect, useRef, useState } from "react";
import type { Gate } from "../types";

function timeAgo(iso: string): string {
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return "방금";
  if (diff < 3600) return `${Math.floor(diff / 60)}분 전`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}시간 전`;
  return iso.slice(0, 10);
}

/** 진행 / 수정 버튼 + 수정 코멘트 입력 */
function GateActions({ gate, onResolve, compact }: { gate: Gate; onResolve: (g: Gate, action: "approve" | "revise", comment: string) => Promise<void>; compact?: boolean }) {
  const [mode, setMode] = useState<"idle" | "revise" | "busy">("idle");
  const [comment, setComment] = useState("");

  const act = async (action: "approve" | "revise") => {
    setMode("busy");
    try {
      await onResolve(gate, action, comment.trim());
    } finally {
      setMode("idle");
      setComment("");
    }
  };

  if (mode === "revise") {
    return (
      <div className="gate-revise">
        <textarea
          rows={2}
          autoFocus
          placeholder={gate.kind === "script" ? "수정할 내용 (Claude가 반영해 수정본을 다시 보냅니다)" : "수정할 내용 메모"}
          value={comment}
          onChange={(e) => setComment(e.target.value)}
        />
        <div className="row end">
          <button className="btn small ghost" onClick={() => setMode("idle")}>
            취소
          </button>
          <button className="btn small" onClick={() => act("revise")}>
            수정 요청
          </button>
        </div>
      </div>
    );
  }
  return (
    <div className={`row ${compact ? "" : "end"}`}>
      <button className="btn small ghost" disabled={mode === "busy"} onClick={() => setMode("revise")}>
        ✎ 수정
      </button>
      <button className="btn small primary" disabled={mode === "busy"} onClick={() => act("approve")}>
        {mode === "busy" ? "처리 중…" : "▶ 진행"}
      </button>
    </div>
  );
}

interface CenterProps {
  gates: Gate[];
  flowEnabled: boolean;
  onResolve: (g: Gate, action: "approve" | "revise", comment: string) => Promise<void>;
  onOpen: (g: Gate) => void;
}

/** 상단바 알림 센터 — Flow 메신저로 나갈 승인 요청과 같은 내용 */
export function NotificationCenter({ gates, flowEnabled, onResolve, onOpen }: CenterProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  return (
    <div className="notif" ref={ref}>
      <button className={`bell ${gates.length ? "has" : ""}`} onClick={() => setOpen(!open)} title="승인 대기 알림">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" />
          <path d="M13.7 21a2 2 0 0 1-3.4 0" />
        </svg>
        {gates.length > 0 && <span className="bell-count">{gates.length}</span>}
      </button>
      {open && (
        <div className="notif-panel">
          <header className="notif-head">
            <strong>승인 대기</strong>
            <span className={`badge ${flowEnabled ? "ok" : "muted-badge"}`}>{flowEnabled ? "Flow 연동됨" : "Flow 미연동 · 앱 알림만"}</span>
          </header>
          {gates.length === 0 ? (
            <p className="muted notif-empty">대기 중인 승인 요청이 없습니다.</p>
          ) : (
            <ul className="notif-list">
              {gates.map((g) => (
                <li key={g.id} className="notif-item">
                  <button className="notif-link" onClick={() => { onOpen(g); setOpen(false); }}>
                    <span className="muted small">
                      {g.project_name} · {timeAgo(g.created_at)} · 코드 {g.id}
                    </span>
                    <strong>{g.title}</strong>
                    <span className="notif-summary">{g.summary}</span>
                  </button>
                  <GateActions gate={g} onResolve={onResolve} />
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

/** 현재 단계에 걸린 승인 요청 / 수정 요청 표시 */
export function GateBanner({ gates, onResolve }: { gates: Gate[]; onResolve: CenterProps["onResolve"] }) {
  const pending = gates.find((g) => g.status === "pending");
  const lastRevised = gates
    .filter((g) => g.status !== "superseded")
    .sort((a, b) => b.created_at.localeCompare(a.created_at))[0];

  if (pending) {
    return (
      <div className="gate-banner pending">
        <div className="gate-banner-body">
          <span className="gate-dot" />
          <div>
            <strong>{pending.title}</strong>
            <div className="muted small pre">{pending.summary}</div>
          </div>
        </div>
        <GateActions gate={pending} onResolve={onResolve} compact />
      </div>
    );
  }
  if (lastRevised && lastRevised.status === "revised") {
    return (
      <div className="gate-banner revised">
        <div className="gate-banner-body">
          <span>✎</span>
          <div>
            <strong>수정 요청{lastRevised.resolved_via === "flow" ? " (Flow)" : ""}</strong>
            <div className="small pre">{lastRevised.comment || "(코멘트 없음)"}</div>
          </div>
        </div>
      </div>
    );
  }
  return null;
}
