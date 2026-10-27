import { useEffect, useState } from "react";
import { api, dataUrl } from "../api";
import { ErrorBox } from "../components/common";
import { fmtTime, roleLabel } from "../labels";
import type { JobState, Production, Project, Script, Status } from "../types";

interface Props {
  project: Project;
  status: Status | null;
  onRefresh: () => Promise<Project | null>;
  onNext: (p: Project) => void;
}

const ASPECT_CSS: Record<string, string> = { "9:16": "9 / 16", "16:9": "16 / 9", "1:1": "1 / 1", "4:5": "4 / 5" };

function TrackProgress({ job }: { job: JobState }) {
  if (job.status === "running") {
    return (
      <div className="track-progress">
        <div className="progress">
          <div className="progress-bar" style={{ width: `${Math.round(job.progress * 100)}%` }} />
        </div>
        <span className="muted small">{job.message}</span>
      </div>
    );
  }
  if (job.status === "error") return <div className="alert error small">{job.message}</div>;
  return null;
}

export default function Step5Production({ project, status, onRefresh, onNext }: Props) {
  const [script, setScript] = useState<Script | null>(null);
  const [prod, setProd] = useState<Production | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const vJob = project.visual_job;
  const sJob = project.sound_job;
  const anyRunning = vJob.status === "running" || sJob.status === "running";

  useEffect(() => {
    api.getScript(project.id).then(setScript);
  }, [project.id]);

  // 작업 진행 중에는 project가 2초마다 갱신되므로 결과물도 함께 다시 읽는다
  useEffect(() => {
    api.getProduction(project.id).then(setProd).catch(() => {});
  }, [project.id, project.updated_at]);

  const run = async (label: string, fn: () => Promise<unknown>) => {
    setBusy(label);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  };

  const startJob = (fn: () => Promise<unknown>) =>
    run("요청 중", async () => {
      await fn();
      await onRefresh();
    });

  const regen = (sceneId: string, what: "image" | "video" | "audio") =>
    run(`${sceneId}-${what}`, async () => {
      setProd(what === "audio" ? await api.regenerateAudio(project.id, sceneId) : await api.regenerateVisual(project.id, sceneId, what));
    });

  if (!script || !prod) return <p className="muted">불러오는 중…</p>;

  const scenes = script.scenes;
  const images = scenes.filter((s) => prod.visual.scenes[s.id]?.image).length;
  const { videos, audios, total, ready } = prod.status;
  const ratio = ASPECT_CSS[script.meta.aspect_ratio] ?? "9 / 16";
  const url = (rel: string, v: number) => `${dataUrl(project.id, rel)}?v=${v}`;

  return (
    <div className="stack">
      {error && <ErrorBox message={error} onClose={() => setError("")} />}

      <section className="tracks">
        <div className="card track">
          <div className="track-head">
            <span className="track-tag visual">2-A</span>
            <h3>비주얼</h3>
            <span className="muted small push">{prod.visual.engine || status?.visual_engine}</span>
          </div>
          <div className="track-stats">
            <div>
              <b>
                {images}/{total}
              </b>
              <span>장면 이미지</span>
            </div>
            <div>
              <b>
                {videos}/{total}
              </b>
              <span>영상 클립</span>
            </div>
          </div>
          <TrackProgress job={vJob} />
          <div className="row wrap">
            <button className="btn small" disabled={vJob.status === "running" || !!busy} onClick={() => startJob(() => api.generateImages(project.id))}>
              {images ? "이미지 전체 재생성" : "이미지 생성"}
            </button>
            <button
              className="btn small primary"
              disabled={vJob.status === "running" || !!busy || images < total}
              title={images < total ? "모든 장면 이미지가 있어야 합니다" : ""}
              onClick={() => startJob(() => api.generateVideos(project.id))}
            >
              {videos ? "영상화 전체 다시" : "영상화 →"}
            </button>
          </div>
        </div>

        <div className="track-parallel" aria-hidden>
          <span>병렬</span>
        </div>

        <div className="card track">
          <div className="track-head">
            <span className="track-tag sound">2-B</span>
            <h3>사운드</h3>
            <span className="muted small push">{prod.sound.engine || status?.sound_engine}</span>
          </div>
          <div className="track-stats">
            <div>
              <b>
                {audios}/{total}
              </b>
              <span>장면 음성 (문장별 파일)</span>
            </div>
            <div>
              <b className="voice-name">{prod.sound.voice || script.voice.persona || "-"}</b>
              <span>목소리 · {script.voice.speech_level || "-"} · {script.voice.pace || "-"}</span>
            </div>
          </div>
          <TrackProgress job={sJob} />
          <div className="row wrap">
            <button className="btn small primary" disabled={sJob.status === "running" || !!busy} onClick={() => startJob(() => api.generateSound(project.id))}>
              {audios ? "음성 전체 재생성" : "음성 생성"}
            </button>
          </div>
        </div>
      </section>

      <section className="prod-table">
        <div className="prod-row prod-head">
          <div>장면</div>
          <div>대사 · 장면 브리프</div>
          <div>이미지</div>
          <div>영상 클립</div>
          <div>음성</div>
        </div>
        {scenes.map((s, i) => {
          const va = prod.visual.scenes[s.id];
          const sa = prod.sound.scenes[s.id];
          const dur = s.end - s.start;
          const over = sa && sa.duration > dur + 0.05;
          return (
            <div key={s.id} className="prod-row">
              <div className="seg-time">
                <b>#{String(i + 1).padStart(2, "0")}</b>
                <span>
                  {fmtTime(s.start)}–{fmtTime(s.end)}
                </span>
                {s.role && <span className="chip">{roleLabel(s.role)}</span>}
              </div>
              <div className="prod-text">
                <div className="pre">{s.dialogue || <span className="muted">(대사 없음)</span>}</div>
                {va?.prompt && (
                  <details className="detail-toggle">
                    <summary>장면 브리프{va.motion ? ` · ${va.motion}` : ""}</summary>
                    <div className="small muted brief">{va.prompt}</div>
                  </details>
                )}
              </div>
              <div className="media-cell">
                <div className="media-box" style={{ aspectRatio: ratio }}>
                  {va?.image ? <img src={url(va.image, va.v)} alt="" /> : <span className="muted small">대기</span>}
                </div>
                <button className="icon-btn small-btn" disabled={anyRunning || !!busy} title="이미지 재생성" onClick={() => regen(s.id, "image")}>
                  {busy === `${s.id}-image` ? "…" : "↻"}
                </button>
              </div>
              <div className="media-cell">
                <div className="media-box" style={{ aspectRatio: ratio }}>
                  {va?.video ? (
                    <video
                      src={url(va.video, va.v)}
                      preload="metadata"
                      muted
                      loop
                      playsInline
                      onMouseEnter={(e) => e.currentTarget.play()}
                      onMouseLeave={(e) => e.currentTarget.pause()}
                    />
                  ) : (
                    <span className="muted small">{va?.image ? "영상화 대기" : "대기"}</span>
                  )}
                </div>
                <button
                  className="icon-btn small-btn"
                  disabled={anyRunning || !!busy || !va?.image}
                  title="이 장면만 영상화"
                  onClick={() => regen(s.id, "video")}
                >
                  {busy === `${s.id}-video` ? "…" : "↻"}
                </button>
                {va?.error && <div className="cell-error">{va.error}</div>}
              </div>
              <div className="audio-cell">
                {sa?.lines.length ? (
                  <>
                    {sa.lines.map((line, n) => (
                      <div key={n} className="sentence-audio">
                        <span className="small">
                          {n + 1}. {line.text}
                        </span>
                        {line.audio && <audio controls preload="none" src={url(line.audio, sa.v)} />}
                      </div>
                    ))}
                    <span className={`small ${over ? "over" : "muted"}`}>
                      합계 {sa.duration.toFixed(1)}s / 장면 {dur.toFixed(1)}s{over && " · 장면보다 김"}
                    </span>
                  </>
                ) : sa ? (
                  <span className="muted small">대사 없음 (무음)</span>
                ) : (
                  <span className="muted small">대기</span>
                )}
                {sa?.error && <div className="cell-error">{sa.error}</div>}
                <button className="icon-btn small-btn" disabled={anyRunning || !!busy} title="음성 재생성" onClick={() => regen(s.id, "audio")}>
                  {busy === `${s.id}-audio` ? "…" : "↻"}
                </button>
              </div>
            </div>
          );
        })}
      </section>

      <footer className="action-bar">
        <span className="muted">
          {ready ? "모든 장면의 영상 클립과 음성이 준비되었습니다." : `영상 클립 ${videos}/${total} · 음성 ${audios}/${total} 준비됨`}
          {" · 마우스를 올리면 클립이 재생됩니다"}
        </span>
        <button
          className="btn primary"
          disabled={!ready || anyRunning || !!busy}
          onClick={() => run("확정 중", async () => onNext(await api.confirmProduction(project.id)))}
        >
          {project.completed ? "결과물 다운로드 →" : "제작 확정 · 결과물 받기 →"}
        </button>
      </footer>
    </div>
  );
}
