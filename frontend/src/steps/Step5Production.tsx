import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, dataUrl } from "../api";
import { ErrorBox } from "../components/common";
import { fmtTime, roleLabel } from "../labels";
import type { Estimate, JobState, Production, Project, Script, Status, TTSSettings, TypecastVoice, VoicesMeta } from "../types";

interface Props {
  project: Project;
  status: Status | null;
  onRefresh: () => Promise<Project | null>;
  onNext: (p: Project) => void;
}

const ASPECT_CSS: Record<string, string> = { "9:16": "9 / 16", "16:9": "16 / 9", "1:1": "1 / 1", "4:5": "4 / 5" };
const AGE_LABEL: Record<string, string> = { child: "어린이", teenager: "10대", young_adult: "청년", middle_age: "중년", elder: "노년" };
const usd = (n: number) => `$${n.toFixed(2)}`;

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
  if (job.status === "done" && job.message) return <span className="muted small">{job.message}</span>;
  return null;
}

// ── 전체화면 보기 ─────────────────────────────────────────────

interface ViewItem {
  sceneId: string;
  label: string;
  kind: "image" | "video";
  src: string;
}

function Lightbox({ items, index, onIndex, onClose }: {
  items: ViewItem[];
  index: number;
  onIndex: (i: number) => void;
  onClose: () => void;
}) {
  const item = items[index];
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "ArrowRight" && index < items.length - 1) onIndex(index + 1);
      if (e.key === "ArrowLeft" && index > 0) onIndex(index - 1);
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [index, items.length, onClose, onIndex]);
  if (!item) return null;
  return (
    <div className="lightbox" onClick={onClose} role="dialog" aria-modal>
      <div className="lightbox-bar" onClick={(e) => e.stopPropagation()}>
        <b>{item.label}</b>
        <span className="small">
          {index + 1}/{items.length} · ← → 이동 · Esc 닫기
        </span>
        <span className="push" />
        <button className="btn small" onClick={onClose}>
          닫기 ✕
        </button>
      </div>
      <button
        className="lightbox-nav prev"
        disabled={index === 0}
        onClick={(e) => {
          e.stopPropagation();
          onIndex(index - 1);
        }}
        aria-label="이전"
      >
        ‹
      </button>
      <div className="lightbox-media" onClick={(e) => e.stopPropagation()}>
        {item.kind === "image" ? <img src={item.src} alt={item.label} /> : <video key={item.src} src={item.src} controls autoPlay loop playsInline />}
      </div>
      <button
        className="lightbox-nav next"
        disabled={index === items.length - 1}
        onClick={(e) => {
          e.stopPropagation();
          onIndex(index + 1);
        }}
        aria-label="다음"
      >
        ›
      </button>
    </div>
  );
}

// ── TTS 설정 (목소리·배속·감정) ─────────────────────────────────────────────

type TTSForm = TTSSettings & { voice_id: string };

function TTSPanel({ form, setForm, voices, meta, disabled, onPreview, previewing }: {
  form: TTSForm;
  setForm: (f: TTSForm) => void;
  voices: TypecastVoice[];
  meta: VoicesMeta | null;
  disabled: boolean;
  onPreview: () => void;
  previewing: boolean;
}) {
  const [gender, setGender] = useState("");
  const [age, setAge] = useState("");
  const [trait, setTrait] = useState("");
  const player = useRef<HTMLAudioElement | null>(null);

  const filtered = useMemo(
    () => voices.filter((v) => (!gender || v.gender === gender) && (!age || v.age === age) && (!trait || v.traits.includes(trait))),
    [voices, gender, age, trait],
  );
  const current = voices.find((v) => v.voice_id === form.voice_id);
  const emotions = ["smart", ...(current?.emotions ?? ["normal"])];
  const label = (e: string) => meta?.emotion_labels[e] ?? e;

  const playSample = (url: string | null | undefined) => {
    if (!url) return;
    player.current?.pause();
    player.current = new Audio(url);
    player.current.play().catch(() => {});
  };
  const pickVoice = (id: string) => {
    const v = voices.find((x) => x.voice_id === id);
    // 새 목소리가 지원하지 않는 감정이면 자동(문맥)으로 돌린다
    const emotion = form.emotion === "smart" || v?.emotions.includes(form.emotion) ? form.emotion : "smart";
    setForm({ ...form, voice_id: id, emotion });
  };

  return (
    <div className="tts-panel">
      <div className="tts-filters">
        <select value={gender} onChange={(e) => setGender(e.target.value)} disabled={disabled}>
          <option value="">성별 전체</option>
          <option value="female">여성</option>
          <option value="male">남성</option>
        </select>
        <select value={age} onChange={(e) => setAge(e.target.value)} disabled={disabled}>
          <option value="">연령 전체</option>
          {Object.entries(AGE_LABEL).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
        <select value={trait} onChange={(e) => setTrait(e.target.value)} disabled={disabled}>
          <option value="">성격 전체</option>
          {meta?.traits.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      </div>
      <div className="row">
        <select className="grow" value={form.voice_id} onChange={(e) => pickVoice(e.target.value)} disabled={disabled}>
          {!form.voice_id && <option value="">자동 (화자 페르소나로 선택)</option>}
          {current && !filtered.includes(current) && <option value={current.voice_id}>{current.name} (현재 · 필터 밖)</option>}
          {filtered.map((v) => (
            <option key={v.voice_id} value={v.voice_id}>
              {v.name} · {v.gender === "female" ? "여" : v.gender === "male" ? "남" : "-"} · {AGE_LABEL[v.age ?? ""] ?? "-"}
              {v.traits.length ? ` · ${v.traits.slice(0, 3).join("·")}` : ""}
            </option>
          ))}
        </select>
        <button className="btn small" disabled={!current?.preview_url} onClick={() => playSample(current?.preview_url)} title="목소리 샘플 듣기">
          ▶ 샘플
        </button>
      </div>
      <span className="muted small">
        조건에 맞는 목소리 {filtered.length}개{current ? ` · ${current.name}: ${current.traits.join(", ") || "성격 정보 없음"}` : ""}
      </span>

      <label className="tts-slider">
        <span>배속</span>
        <input
          type="range"
          min={0.5}
          max={2}
          step={0.05}
          value={form.tempo}
          disabled={disabled}
          onChange={(e) => setForm({ ...form, tempo: Number(e.target.value) })}
        />
        <b>{form.tempo.toFixed(2)}x</b>
      </label>
      <label className="tts-slider">
        <span>감정</span>
        <select value={form.emotion} disabled={disabled} onChange={(e) => setForm({ ...form, emotion: e.target.value })}>
          {emotions.map((e) => (
            <option key={e} value={e}>
              {label(e)}
            </option>
          ))}
        </select>
      </label>
      {form.emotion !== "smart" && (
        <label className="tts-slider">
          <span>감정 강도</span>
          <input
            type="range"
            min={0}
            max={2}
            step={0.1}
            value={form.emotion_intensity}
            disabled={disabled}
            onChange={(e) => setForm({ ...form, emotion_intensity: Number(e.target.value) })}
          />
          <b>{form.emotion_intensity.toFixed(1)}</b>
        </label>
      )}
      <label className="tts-slider">
        <span>음높이</span>
        <input
          type="range"
          min={-12}
          max={12}
          step={1}
          value={form.pitch}
          disabled={disabled}
          onChange={(e) => setForm({ ...form, pitch: Number(e.target.value) })}
        />
        <b>{form.pitch > 0 ? `+${form.pitch}` : form.pitch}</b>
      </label>
      <button className="btn small" disabled={disabled || previewing} onClick={onPreview}>
        {previewing ? "만드는 중…" : "🔊 이 설정으로 첫 문장 미리 듣기"}
      </button>
    </div>
  );
}

// ── 5단계 ─────────────────────────────────────────────

export default function Step5Production({ project, status, onRefresh, onNext }: Props) {
  const [script, setScript] = useState<Script | null>(null);
  const [prod, setProd] = useState<Production | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [estimate, setEstimate] = useState<Estimate | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [view, setView] = useState<number | null>(null);
  const [voices, setVoices] = useState<TypecastVoice[]>([]);
  const [meta, setMeta] = useState<VoicesMeta | null>(null);
  const [form, setForm] = useState<TTSForm | null>(null);
  const player = useRef<HTMLAudioElement | null>(null);
  const vJob = project.visual_job;
  const sJob = project.sound_job;
  const vRunning = vJob.status === "running";
  const sRunning = sJob.status === "running";
  const typecast = status?.sound_engine_id === "typecast";

  useEffect(() => {
    api.getScript(project.id).then(setScript);
  }, [project.id]);

  // 작업 진행 중에는 project가 2초마다 갱신되므로 결과물도 함께 다시 읽는다
  useEffect(() => {
    api.getProduction(project.id).then(setProd).catch(() => {});
  }, [project.id, project.updated_at]);

  useEffect(() => {
    api.estimate(project.id).then(setEstimate).catch(() => setEstimate(null));
  }, [project.id, prod?.visual.video_model]);

  useEffect(() => {
    if (!typecast) return;
    api.listVoices().then(setVoices).catch(() => setVoices([]));
    api.voicesMeta().then(setMeta).catch(() => setMeta(null));
  }, [typecast]);

  // 저장된 TTS 설정으로 폼을 한 번 채운다 (이후엔 사용자가 조절한 값을 유지)
  useEffect(() => {
    if (prod && !form) setForm({ ...prod.sound.settings, voice_id: prod.sound.voice_id });
  }, [prod, form]);

  const scenes = useMemo(() => script?.scenes ?? [], [script]);
  const viewItems: ViewItem[] = useMemo(() => {
    if (!prod) return [];
    const out: ViewItem[] = [];
    scenes.forEach((s, i) => {
      const va = prod.visual.scenes[s.id];
      const no = `#${String(i + 1).padStart(2, "0")}`;
      if (va?.image)
        out.push({ sceneId: s.id, kind: "image", label: `${no} 이미지`, src: `${dataUrl(project.id, va.image)}?v=${va.v}` });
      if (va?.video) out.push({ sceneId: s.id, kind: "video", label: `${no} 영상 클립`, src: `${dataUrl(project.id, va.video)}?v=${va.v}` });
    });
    return out;
  }, [prod, scenes, project.id]);
  const closeView = useCallback(() => setView(null), []);

  if (!script || !prod || !form) return <p className="muted">불러오는 중…</p>;

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

  const settingsDirty =
    form.voice_id !== prod.sound.voice_id ||
    (["tempo", "emotion", "emotion_intensity", "pitch"] as const).some((k) => form[k] !== prod.sound.settings[k]);
  /** 문장을 만들기 전에 화면의 TTS 설정을 저장한다 */
  const saveSettings = async () => {
    if (settingsDirty) setProd(await api.setTTSSettings(project.id, form));
  };

  const billable = !!estimate?.billable;
  const confirmCost = (what: string, amount: number) =>
    !billable || confirm(`${what}\n예상 비용: 약 ${usd(amount)} (힉스필드 견적 기준, 실패한 생성은 청구되지 않음)\n\n진행할까요?`);
  const imageCost = (ids: string[]) => ids.length * (estimate?.image_usd_each ?? 0);
  const videoCost = (ids: string[]) => ids.reduce((sum, id) => sum + (estimate?.scene_video_usd[id] ?? 0), 0);

  const vs = prod.visual.scenes;
  const ss = prod.sound.scenes;
  const st = prod.status;
  const ratio = ASPECT_CSS[script.meta.aspect_ratio] ?? "9 / 16";
  const url = (rel: string, v: number) => `${dataUrl(project.id, rel)}?v=${v}`;
  const toAnimate = scenes.filter((s) => vs[s.id]?.image && !vs[s.id]?.video).map((s) => s.id);
  const sel = scenes.map((s) => s.id).filter((id) => selected.has(id));
  const lock = !!busy;
  const openView = (sceneId: string, kind: "image" | "video") => setView(viewItems.findIndex((x) => x.sceneId === sceneId && x.kind === kind));

  const makeImages = (ids?: string[]) => {
    const target = ids ?? scenes.map((s) => s.id);
    const what = ids
      ? `장면 ${target.length}개의 이미지를 다시 만듭니다 (그 장면의 영상은 지워지고, 전체 승인 때 다시 영상화됩니다).`
      : `장면 ${target.length}개의 이미지를 만듭니다.`;
    if (confirmCost(what, imageCost(target))) startJob(() => api.generateImages(project.id, ids));
  };
  /** [이미지 전체 승인 → 영상화]: 영상이 없는 장면(처음엔 전체, 이후엔 이미지를 다시 만든 장면)을 영상화한다 */
  const approveAll = () => {
    if (confirmCost(`이미지를 전체 승인하고 장면 ${toAnimate.length}개를 영상화합니다 (${estimate?.video_model}).`, videoCost(toAnimate)))
      startJob(() => api.approveAllImages(project.id));
  };
  const remakeVideos = (ids: string[]) => {
    if (ids.some((id) => !vs[id]?.image_approved)) {
      setError("이미지를 다시 만든 장면이 있습니다. [이미지 전체 승인 → 영상화]를 먼저 눌러 주세요.");
      return;
    }
    if (confirmCost(`장면 ${ids.length}개의 영상을 다시 만듭니다 (${estimate?.video_model}).`, videoCost(ids)))
      startJob(() => api.generateVideos(project.id, ids));
  };
  const makeSound = (ids?: string[]) =>
    startJob(async () => {
      await saveSettings();
      await api.generateSound(project.id, ids);
    });
  const regenLine = (sceneId: string, n: number) =>
    run(`${sceneId}-${n}`, async () => {
      await saveSettings();
      setProd(await api.regenerateLine(project.id, sceneId, n));
    });
  const preview = () =>
    run("preview", async () => {
      const res = await api.previewTTS(project.id, form);
      player.current?.pause();
      player.current = new Audio(`${res.url}?t=${Date.now()}`);
      await player.current.play().catch(() => {});
    });

  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const allSelected = sel.length === scenes.length && scenes.length > 0;

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
                {st.images}/{st.total}
              </b>
              <span>장면 이미지</span>
            </div>
            <div>
              <b>
                {st.videos}/{st.total}
              </b>
              <span>영상 클립</span>
            </div>
          </div>
          {status?.visual_engine_id === "higgsfield" && (
            <div className="engine-options">
              <label className="field">
                <span>영상 모델</span>
                <select
                  value={prod.visual.video_model}
                  disabled={vRunning || lock}
                  onChange={(e) => run("모델 변경 중", async () => setProd(await api.setVideoModel(project.id, e.target.value)))}
                >
                  {status.video_models.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.label} · 초당 ${m.usd_per_sec} · 최소 {m.min_sec}초
                    </option>
                  ))}
                </select>
              </label>
              {estimate && (
                <div className="estimate">
                  전체 예상 비용 <b>{usd(estimate.total_usd)}</b>
                  <span className="muted small">
                    {" "}
                    = 이미지 {usd(estimate.images_usd)} + 영상 {usd(estimate.videos_usd)} (총 {estimate.video_seconds}초)
                  </span>
                </div>
              )}
            </div>
          )}
          <TrackProgress job={vJob} />
          <ol className="flow-steps small">
            <li className={st.images ? "done" : ""}>이미지 생성</li>
            <li className={st.images_approved ? "done" : ""}>확인 (누르면 크게 보기) · 마음에 안 드는 장면만 ↻ → 전체 승인</li>
            <li className={st.videos ? "done" : ""}>영상화 · 마음에 안 드는 장면만 ↻</li>
          </ol>
          <div className="row wrap">
            <button className={`btn small ${st.images ? "" : "primary"}`} disabled={vRunning || lock} onClick={() => makeImages()}>
              {st.images ? "이미지 전체 재생성" : "이미지 생성 시작"}
            </button>
            <button
              className="btn small primary"
              disabled={vRunning || lock || st.images < st.total || !toAnimate.length}
              title={st.images < st.total ? "모든 장면의 이미지가 있어야 합니다" : ""}
              onClick={approveAll}
            >
              이미지 전체 승인 → 영상화{st.videos && toAnimate.length ? ` (${toAnimate.length}개)` : ""}
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
                {st.audios}/{st.total}
              </b>
              <span>장면 음성 ({st.lines}문장)</span>
            </div>
            <div>
              <b className="voice-name">{prod.sound.voice || "자동 선택"}</b>
              <span>
                저장된 설정 · {prod.sound.settings.tempo.toFixed(2)}x · {meta?.emotion_labels[prod.sound.settings.emotion] ?? prod.sound.settings.emotion}
              </span>
            </div>
          </div>
          {typecast ? (
            <TTSPanel form={form} setForm={setForm} voices={voices} meta={meta} disabled={sRunning || lock} onPreview={preview} previewing={busy === "preview"} />
          ) : (
            <p className="muted small">타입캐스트 키가 없어 임시 음성으로 만듭니다 (목소리·배속 조절은 타입캐스트에서만 됩니다).</p>
          )}
          <TrackProgress job={sJob} />
          {settingsDirty && st.audios > 0 && <span className="small warn-text">설정을 바꿨습니다. 다시 만드는 문장부터 새 설정이 적용됩니다.</span>}
          <div className="row wrap">
            <button className="btn small primary" disabled={sRunning || lock} onClick={() => makeSound()}>
              {st.audios ? "이 설정으로 음성 전체 재생성" : "▶ 음성 생성 시작"}
            </button>
          </div>
        </div>
      </section>

      <div className={`selection-bar ${sel.length ? "active" : ""}`}>
        <label className="row">
          <input type="checkbox" checked={allSelected} onChange={() => setSelected(allSelected ? new Set() : new Set(scenes.map((s) => s.id)))} />
          <span className="small">{sel.length ? `${sel.length}개 장면 선택됨` : "장면을 체크하면 그 구간만 다시 만들 수 있습니다"}</span>
        </label>
        {sel.length > 0 && (
          <div className="row wrap">
            <button className="btn small" disabled={vRunning || lock} onClick={() => makeImages(sel)}>
              이미지 다시 만들기
            </button>
            <button className="btn small" disabled={vRunning || lock} onClick={() => remakeVideos(sel)}>
              영상 다시 만들기
            </button>
            <button className="btn small" disabled={sRunning || lock} onClick={() => makeSound(sel)}>
              음성 다시 만들기
            </button>
            <button className="btn small ghost" onClick={() => setSelected(new Set())}>
              선택 해제
            </button>
          </div>
        )}
      </div>

      <section className="prod-table">
        <div className="prod-row prod-head">
          <div>장면</div>
          <div>대사 · 장면 브리프</div>
          <div>이미지</div>
          <div>영상 클립</div>
          <div>음성 (문장별 다시 만들기)</div>
        </div>
        {scenes.map((s, i) => {
          const va = vs[s.id];
          const sa = ss[s.id];
          const dur = s.end - s.start;
          const over = sa && sa.duration > dur + 0.05;
          return (
            <div key={s.id} className={`prod-row ${selected.has(s.id) ? "selected" : ""}`}>
              <div className="seg-time">
                <label className="row">
                  <input type="checkbox" checked={selected.has(s.id)} onChange={() => toggle(s.id)} />
                  <b>#{String(i + 1).padStart(2, "0")}</b>
                </label>
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
                <div
                  className={`media-box ${va?.image ? "zoomable" : ""}`}
                  style={{ aspectRatio: ratio }}
                  onClick={() => va?.image && openView(s.id, "image")}
                  title={va?.image ? "크게 보기" : ""}
                >
                  {va?.image ? <img src={url(va.image, va.v)} alt="" /> : <span className="muted small">대기</span>}
                </div>
                <button className="icon-btn small-btn" disabled={vRunning || lock} title="이 장면 이미지 다시 만들기" onClick={() => makeImages([s.id])}>
                  ↻
                </button>
              </div>
              <div className="media-cell">
                <div
                  className={`media-box ${va?.video ? "zoomable" : ""}`}
                  style={{ aspectRatio: ratio }}
                  onClick={() => va?.video && openView(s.id, "video")}
                  title={va?.video ? "크게 보기" : ""}
                >
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
                    <span className="muted small">{va?.image ? "전체 승인 후 영상화" : "대기"}</span>
                  )}
                </div>
                <button
                  className="icon-btn small-btn"
                  disabled={vRunning || lock || !va?.video}
                  title={va?.video ? "이 장면 영상만 다시 만들기" : "이미지 전체 승인 후 영상화됩니다"}
                  onClick={() => remakeVideos([s.id])}
                >
                  ↻
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
                        {line.audio && <audio controls preload="none" src={url(line.audio, line.v || sa.v)} />}
                        <div className="row">
                          <button className="btn small ghost" disabled={sRunning || lock} onClick={() => regenLine(s.id, n + 1)}>
                            {busy === `${s.id}-${n + 1}` ? "만드는 중…" : "↻ 이 문장만"}
                          </button>
                        </div>
                        {line.error && <div className="cell-error">{line.error}</div>}
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
                <button className="icon-btn small-btn" disabled={sRunning || lock} title="이 장면 음성 전체 다시 만들기" onClick={() => makeSound([s.id])}>
                  ↻
                </button>
              </div>
            </div>
          );
        })}
      </section>

      <footer className="action-bar">
        <span className="muted">
          {st.ready
            ? "영상 클립과 음성이 모두 준비되었습니다. 마음에 안 드는 장면·문장만 다시 만든 뒤 전체 승인하세요."
            : `영상 클립 ${st.videos}/${st.total} · 장면 음성 ${st.audios}/${st.total}`}
          {" · 이미지·영상을 누르면 전체화면으로 봅니다"}
        </span>
        <button
          className="btn primary"
          disabled={!st.ready || vRunning || sRunning || lock}
          onClick={() => run("확정 중", async () => onNext(await api.confirmProduction(project.id)))}
        >
          {project.completed ? "결과물 다운로드 →" : "전체 승인 · 결과물 받기 →"}
        </button>
      </footer>

      {view !== null && view >= 0 && (
        <Lightbox
          items={viewItems}
          index={view}
          onIndex={setView}
          onClose={closeView}
        />
      )}
    </div>
  );
}
