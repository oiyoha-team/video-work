import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, dataUrl } from "../api";
import { AutoTextarea, ErrorBox, ErrorText, ProgressLine, fmtDur, useNow } from "../components/common";
import { fmtTime, roleLabel } from "../labels";
import type { Estimate, JobState, Production, Project, Script, Status, TTSSettings, TypecastVoice, VisualAsset, VisualModels } from "../types";

interface Props {
  project: Project;
  status: Status | null;
  onRefresh: () => Promise<Project | null>;
  onNext: (p: Project) => void;
}

const ASPECT_CSS: Record<string, string> = { "9:16": "9 / 16", "16:9": "16 / 9", "1:1": "1 / 1", "4:5": "4 / 5" };
const AGE_LABEL: Record<string, string> = { child: "어린이", teenager: "10대", young_adult: "청년", middle_age: "중년", elder: "노년" };
const usd = (n: number) => `$${n.toFixed(2)}`;
const FOLLOW_LABEL: Record<string, string> = {
  low: "약하게 — 역할만 참고, 컷 구성은 새로 (레퍼런스와 가장 다름)",
  medium: "보통 (기본) — 컷마다 샷 크기·앵글·구도·동작을 레퍼런스 컷에 맞춤",
  high: "강하게 — 구도·동작에 배경 종류·배치까지 레퍼런스 컷에 가깝게",
};
const range = ([lo, hi]: [number, number]) => `보통 ${fmtDur(lo)} ~ ${fmtDur(hi)}`;

function TrackProgress({ job }: { job: JobState }) {
  if (job.status === "running") return <ProgressLine job={job} />;
  if (job.status === "error")
    return (
      <div className="alert error small">
        <ErrorText message={job.message} />
      </div>
    );
  if (job.status === "done" && job.message) return <span className="muted small">✓ {job.message}</span>;
  return null;
}

// ── 전체화면 보기 ─────────────────────────────────────────────

interface ViewItem {
  key: string;
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

// ── TTS 설정 (목소리·배속) ─────────────────────────────────────────────

type TTSForm = TTSSettings & { voice_id: string };

function TTSPanel({ form, setForm, voices, disabled, onPreview, previewing }: {
  form: TTSForm;
  setForm: (f: TTSForm) => void;
  voices: TypecastVoice[];
  disabled: boolean;
  onPreview: () => void;
  previewing: boolean;
}) {
  const [gender, setGender] = useState("");
  const [age, setAge] = useState("");
  const [playing, setPlaying] = useState("");
  const player = useRef<HTMLAudioElement | null>(null);

  const filtered = useMemo(() => voices.filter((v) => (!gender || v.gender === gender) && (!age || v.age === age)), [voices, gender, age]);
  const current = voices.find((v) => v.voice_id === form.voice_id);

  // 타입캐스트가 주는 샘플 음성을 그대로 들려준다
  const playSample = (v: TypecastVoice) => {
    player.current?.pause();
    if (playing === v.voice_id || !v.preview_url) {
      setPlaying("");
      return;
    }
    player.current = new Audio(v.preview_url);
    player.current.onended = () => setPlaying("");
    player.current.play().catch(() => setPlaying(""));
    setPlaying(v.voice_id);
  };
  useEffect(() => () => player.current?.pause(), []);

  return (
    <div className="tts-panel">
      <div className="tts-filters">
        <select value={gender} onChange={(e) => setGender(e.target.value)}>
          <option value="">성별 전체</option>
          <option value="female">여성</option>
          <option value="male">남성</option>
        </select>
        <select value={age} onChange={(e) => setAge(e.target.value)}>
          <option value="">연령 전체</option>
          {Object.entries(AGE_LABEL).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
      </div>
      <span className="muted small">
        목소리 {filtered.length}개 · ▶로 샘플을 듣고 이름을 눌러 고르세요 · 선택: <b>{current?.name ?? "자동 (화자 설정으로 선택)"}</b>
      </span>
      <ul className="voice-list">
        {filtered.map((v) => (
          <li key={v.voice_id} className={v.voice_id === form.voice_id ? "on" : ""}>
            <button className="voice-play" disabled={!v.preview_url} onClick={() => playSample(v)} title="샘플 듣기">
              {playing === v.voice_id ? "■" : "▶"}
            </button>
            <button className="voice-pick" disabled={disabled} onClick={() => setForm({ ...form, voice_id: v.voice_id })}>
              <b>{v.name}</b>
              <span className="muted small">
                {v.gender === "female" ? "여성" : v.gender === "male" ? "남성" : "-"} · {AGE_LABEL[v.age ?? ""] ?? "-"}
              </span>
            </button>
          </li>
        ))}
        {!filtered.length && <li className="muted small">조건에 맞는 목소리가 없습니다.</li>}
      </ul>

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
      <button className="btn small" disabled={disabled || previewing} onClick={onPreview}>
        {previewing ? (
          <>
            <span className="spinner tiny" /> 만드는 중… (보통 2~8초)
          </>
        ) : (
          "🔊 이 목소리·배속으로 첫 문장 미리 듣기"
        )}
      </button>
    </div>
  );
}

/** 힉스필드 이미지·영상 모델 선택 (목록은 서버가 12시간마다 갱신) */
function ModelPicker({ models, imageModel, videoModel, disabled, onChange, onRefresh, refreshing }: {
  models: VisualModels | null;
  imageModel: string;
  videoModel: string;
  disabled: boolean;
  onChange: (body: { image_model?: string; video_model?: string; ref_follow?: string }) => void;
  onRefresh: () => void;
  refreshing: boolean;
}) {
  if (!models) return <span className="muted small">모델 목록을 불러오는 중…</span>;
  const updated = models.updated_at ? new Date(models.updated_at).toLocaleString("ko-KR", { dateStyle: "short", timeStyle: "short" }) : "-";
  return (
    <>
      <label className="field">
        <span>이미지 모델</span>
        <select value={imageModel} disabled={disabled} onChange={(e) => onChange({ image_model: e.target.value })}>
          {models.image.map((m) => (
            <option key={m.id} value={m.id}>
              {m.recommended ? "★ 추천 · " : ""}
              {m.label} · {m.usd != null ? `장당 $${m.usd}` : "사용량 기준 과금"} · 참고 이미지 {m.max_images}장
            </option>
          ))}
        </select>
      </label>
      <label className="field">
        <span>영상 모델</span>
        <select value={videoModel} disabled={disabled} onChange={(e) => onChange({ video_model: e.target.value })}>
          {models.video.map((m) => (
            <option key={m.id} value={m.id}>
              {m.recommended ? "★ 추천 · " : ""}
              {m.label} · {m.usd_per_sec != null ? `초당 $${m.usd_per_sec}` : "가격 미확인"}
              {m.resolution ? ` · ${m.resolution}` : ""} · {m.min_sec}~{m.max_sec}초
            </option>
          ))}
        </select>
      </label>
      <span className="muted small">
        힉스필드 모델 {models.image.length + models.video.length}개 · 12시간마다 자동 갱신 (마지막 {updated}){" "}
        <button className="link-btn" disabled={refreshing} onClick={onRefresh}>
          {refreshing ? "갱신 중…" : "지금 갱신"}
        </button>
      </span>
    </>
  );
}

// ── 수정 지시 입력 ─────────────────────────────────────────────

const IMAGE_HINT = "예: 제품을 두 손으로 들고 카메라 쪽으로 내밀기 / 배경을 밝은 욕실로 / 표정을 더 놀란 얼굴로";
const VIDEO_HINT = "예: 카메라가 천천히 제품 쪽으로 다가가기 / 인물이 웃으며 고개 끄덕이기 / 움직임을 더 작게";

function RegenForm({ kind, scene, count, eta, cost, onSubmit, onCancel, disabled, note }: {
  kind: "image" | "video";
  scene?: string;
  count: number;
  eta: string;
  cost: string;
  onSubmit: (instruction: string) => void;
  onCancel: () => void;
  disabled: boolean;
  note?: string;
}) {
  const [text, setText] = useState("");
  const what = kind === "image" ? "이미지" : "영상";
  return (
    <div className="regen-form" onClick={(e) => e.stopPropagation()}>
      <b className="small">
        {scene ? `${scene} 장면 ` : ""}
        {count > 1 ? `선택한 ${count}개 장면 ` : ""}
        {what} 다시 만들기
      </b>
      <AutoTextarea
        value={text}
        onChange={setText}
        minRows={3}
        placeholder={`수정 지시 (선택) — 비워 두면 같은 설계로 다시 만듭니다.\n${kind === "image" ? IMAGE_HINT : VIDEO_HINT}`}
      />
      {note && <span className="small warn-text">{note}</span>}
      <span className="muted small">
        {eta}
        {cost && ` · 예상 비용 ${cost}`} · 만든 뒤 이전 결과와 비교해 고를 수 있습니다
      </span>
      <div className="row wrap">
        <button className="btn small primary" disabled={disabled} onClick={() => onSubmit(text.trim())}>
          {text.trim() ? "지시대로 다시 만들기" : "그대로 다시 만들기"}
        </button>
        <button className="btn small ghost" onClick={onCancel}>
          취소
        </button>
      </div>
    </div>
  );
}

/** 다시 만든 장면의 이전 / 새 결과를 크게 나란히 보여 주고 고르게 한다 (장면 줄 아래 전체 폭) */
function ComparePanel({ kind, scene, ratio, prevSrc, newSrc, prevNote, newNote, disabled, onChoose, onZoom }: {
  kind: "image" | "video";
  scene: string;
  ratio: string;
  prevSrc: string;
  newSrc: string;
  prevNote: string;
  newNote: string;
  disabled: boolean;
  onChoose: (keep: "new" | "prev") => void;
  onZoom: (items: ViewItem[], index: number) => void;
}) {
  const what = kind === "image" ? "이미지" : "영상";
  const items: ViewItem[] = [
    { key: "p", kind, label: `${scene} 이전 ${what}`, src: prevSrc },
    { key: "n", kind, label: `${scene} 새 ${what}`, src: newSrc },
  ];
  const sides = [
    { tag: "이전", src: prevSrc, keep: "prev" as const, note: prevNote, index: 0 },
    { tag: "새", src: newSrc, keep: "new" as const, note: newNote, index: 1 },
  ];
  return (
    <div className="row-panel compare-panel">
      <div className="row wrap">
        <b>
          {scene} 이전 / 새 {what} 비교
        </b>
        <span className="muted small">쓸 것을 고르세요 · 누르면 크게 보고 ← →로 번갈아 볼 수 있습니다 · 고르지 않고 전체 승인하면 새 것으로 확정됩니다</span>
      </div>
      <div className="compare-pair">
        {sides.map((c) => (
          <div key={c.tag} className={`compare-item ${c.keep}`}>
            <div className="media-box zoomable" style={{ aspectRatio: ratio }} onClick={() => onZoom(items, c.index)} title="크게 보기">
              {kind === "image" ? (
                <img src={c.src} alt="" />
              ) : (
                <video src={c.src} preload="metadata" muted loop playsInline autoPlay />
              )}
              <span className="compare-tag">{c.tag}</span>
            </div>
            {c.note ? <span className="small muted compare-note">수정 지시: {c.note}</span> : <span className="small muted compare-note">-</span>}
            <button className={`btn small ${c.keep === "new" ? "primary" : ""}`} disabled={disabled} onClick={() => onChoose(c.keep)}>
              {c.tag} 것 사용
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

/** 장면을 만드는 중일 때 미디어 칸 위에 표시 */
function BusyOverlay({ asset, kind, typical, now }: { asset?: VisualAsset; kind: "image" | "video"; typical: [number, number]; now: number }) {
  if (!asset?.busy) return null;
  if (asset.busy === "queued")
    return (
      <div className="busy-overlay queued">
        <span className="small">순서 대기 중</span>
      </div>
    );
  if (asset.busy !== kind) return null;
  return (
    <div className="busy-overlay">
      <span className="spinner" />
      <b className="small">{kind === "image" ? "이미지" : "영상"} 만드는 중</b>
      <span className="small">{fmtDur(now - asset.busy_since)} 경과</span>
      <span className="tiny-text">{range(typical)}</span>
    </div>
  );
}

// ── 5단계 ─────────────────────────────────────────────

type Editing = { kind: "image" | "video"; sceneId: string } | null;

export default function Step5Production({ project, status, onRefresh, onNext }: Props) {
  const [script, setScript] = useState<Script | null>(null);
  const [prod, setProd] = useState<Production | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [estimate, setEstimate] = useState<Estimate | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [view, setView] = useState<{ items: ViewItem[]; index: number } | null>(null);
  const [voices, setVoices] = useState<TypecastVoice[]>([]);
  const [models, setModels] = useState<VisualModels | null>(null);
  const [form, setForm] = useState<TTSForm | null>(null);
  const [editing, setEditing] = useState<Editing>(null);
  const [selInstruction, setSelInstruction] = useState("");
  const player = useRef<HTMLAudioElement | null>(null);
  const vJob = project.visual_job;
  const sJob = project.sound_job;
  const vRunning = vJob.status === "running";
  const sRunning = sJob.status === "running";
  const typecast = status?.sound_engine_id === "typecast";
  const anyBusy = !!prod && (Object.values(prod.visual.scenes).some((a) => a.busy) || Object.values(prod.sound.scenes).some((a) => a.busy));
  const now = useNow(anyBusy || vRunning || sRunning);

  useEffect(() => {
    api.getScript(project.id).then(setScript);
  }, [project.id]);

  // 작업 진행 중에는 project가 2초마다 갱신되므로 결과물도 함께 다시 읽는다
  useEffect(() => {
    api.getProduction(project.id).then(setProd).catch(() => {});
  }, [project.id, project.updated_at]);

  useEffect(() => {
    api.estimate(project.id).then(setEstimate).catch(() => setEstimate(null));
  }, [project.id, prod?.visual.image_model, prod?.visual.video_model]);

  useEffect(() => {
    if (!typecast) return;
    api.listVoices().then(setVoices).catch(() => setVoices([]));
  }, [typecast]);

  const higgsfield = status?.visual_engine_id === "higgsfield";
  useEffect(() => {
    if (higgsfield) api.visualModels().then(setModels).catch(() => setModels(null));
  }, [higgsfield]);

  // 저장된 TTS 설정으로 폼을 한 번 채운다 (이후엔 사용자가 조절한 값을 유지)
  useEffect(() => {
    if (prod && !form) setForm({ ...prod.sound.settings, voice_id: prod.sound.voice_id });
  }, [prod, form]);

  const scenes = useMemo(() => script?.scenes ?? [], [script]);
  const allItems: ViewItem[] = useMemo(() => {
    if (!prod) return [];
    const out: ViewItem[] = [];
    if (prod.visual.cast_image)
      out.push({ key: "cast:image", kind: "image", label: "인물 기준", src: `${dataUrl(project.id, prod.visual.cast_image)}?v=${prod.visual.cast_v}` });
    scenes.forEach((s, i) => {
      const va = prod.visual.scenes[s.id];
      const no = `#${String(i + 1).padStart(2, "0")}`;
      if (va?.image) out.push({ key: `${s.id}:image`, kind: "image", label: `${no} 이미지`, src: `${dataUrl(project.id, va.image)}?v=${va.v}` });
      if (va?.video) out.push({ key: `${s.id}:video`, kind: "video", label: `${no} 영상 클립`, src: `${dataUrl(project.id, va.video)}?v=${va.v}` });
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
  /** 백그라운드 작업 시작 → 바로 상태를 다시 읽어 진행 표시가 뜨게 한다 */
  const startJob = (label: string, fn: () => Promise<unknown>) =>
    run(label, async () => {
      await fn();
      await onRefresh();
      setProd(await api.getProduction(project.id));
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
  const parallelEta = (kind: "image" | "video", n: number, revise: boolean) => {
    const [lo, hi] = prod.typical[kind];
    const rounds = Math.ceil(n / 3);
    const [rlo, rhi] = revise ? prod.typical.revise : [0, 0];
    return `예상 소요 ${fmtDur(lo * rounds + rlo)} ~ ${fmtDur(hi * rounds + rhi)}`;
  };

  const vs = prod.visual.scenes;
  const ss = prod.sound.scenes;
  const st = prod.status;
  const anchor = prod.visual.anchor_scene;
  const ratio = ASPECT_CSS[script.meta.aspect_ratio] ?? "9 / 16";
  const url = (rel: string, v: number) => `${dataUrl(project.id, rel)}?v=${v}`;
  const toAnimate = scenes.filter((s) => vs[s.id]?.image && !vs[s.id]?.video).map((s) => s.id);
  const sel = scenes.map((s) => s.id).filter((id) => selected.has(id));
  const lock = !!busy;
  const openItem = (key: string) => {
    const i = allItems.findIndex((x) => x.key === key);
    if (i >= 0) setView({ items: allItems, index: i });
  };
  const sceneNo = (id: string) => `#${String(scenes.findIndex((s) => s.id === id) + 1).padStart(2, "0")}`;

  const makeImages = (ids: string[] | undefined, instruction = "") => {
    const target = ids ?? scenes.map((s) => s.id);
    const what = ids
      ? `장면 ${target.length}개의 이미지를 다시 만듭니다${instruction ? ` (수정 지시: ${instruction})` : ""}.\n그 장면의 영상은 새 이미지를 승인한 뒤 다시 만들어집니다.`
      : `장면 ${target.length}개의 이미지를 새로 만듭니다.\n레퍼런스의 그림체·후킹·구성을 빌려 첫 장면(기준)을 만들고, 나머지 장면은 그 기준을 따릅니다.`;
    if (!confirmCost(what, imageCost(target))) return false;
    setEditing(null);
    startJob("images", () => api.generateImages(project.id, ids, instruction));
    return true;
  };
  /** [이미지 전체 승인 → 영상화]: 영상이 없는 장면(처음엔 전체, 이후엔 이미지를 다시 만든 장면)을 영상화한다 */
  const approveAll = () => {
    const pending = st.comparing ? `\n이전/새 결과를 고르지 않은 장면 ${st.comparing}개는 새 결과로 확정됩니다.` : "";
    if (confirmCost(`이미지를 전체 승인하고 장면 ${toAnimate.length}개를 영상화합니다 (${estimate?.video_model}).${pending}`, videoCost(toAnimate)))
      startJob("approve", () => api.approveAllImages(project.id));
  };
  const remakeVideos = (ids: string[], instruction = "") => {
    if (ids.some((id) => !vs[id]?.image_approved)) {
      setError("이미지를 다시 만든 장면이 있습니다. [이미지 전체 승인 → 영상화]를 먼저 눌러 주세요.");
      return;
    }
    if (!confirmCost(`장면 ${ids.length}개의 영상을 다시 만듭니다 (${estimate?.video_model})${instruction ? `\n수정 지시: ${instruction}` : ""}.`, videoCost(ids)))
      return;
    setEditing(null);
    startJob("videos", () => api.generateVideos(project.id, ids, instruction));
  };
  const makeSound = (ids?: string[]) =>
    startJob("sound", async () => {
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
  const choose = (sceneId: string, keep: "new" | "prev") => run(`choose-${sceneId}`, async () => setProd(await api.chooseVersion(project.id, sceneId, keep)));
  const reset = (what: "visual" | "sound" | "all") => {
    const label = { visual: "만든 이미지·영상·인물 기준 이미지", sound: "만든 음성", all: "만든 이미지·영상·음성 전부" }[what];
    if (!confirm(`${label}를 모두 지우고 처음부터 다시 시작합니다.\n고른 모델·목소리·배속은 그대로 남습니다.\n\n되돌릴 수 없습니다. 초기화할까요?`)) return;
    run("reset", async () => {
      await api.resetProduction(project.id, what);
      setSelected(new Set());
      setEditing(null);
      await onRefresh();
      setProd(await api.getProduction(project.id));
    });
  };

  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const allSelected = sel.length === scenes.length && scenes.length > 0;
  const anchorNote = (ids: string[]) =>
    anchor && ids.includes(anchor) && ids.length < scenes.length
      ? "기준 장면(첫 장면)을 바꾸면, 나머지 장면은 다시 만들 때부터 새 기준의 그림체·인물을 따릅니다."
      : undefined;

  return (
    <div className="stack">
      {error && <ErrorBox message={error} onClose={() => setError("")} />}
      {status && (status.visual_engine_id === "mock" || status.sound_engine_id !== "typecast") && (
        <div className="alert warn small">
          {status.visual_engine_id === "mock" && "힉스필드 API 키가 없어 이미지·영상을 임시 엔진(레퍼런스 화면 + 줌 효과)으로 만듭니다. "}
          {status.sound_engine_id !== "typecast" && "타입캐스트 API 키가 없어 음성을 컴퓨터 기본 음성으로 만듭니다. "}
          프로그램 폴더의 .env 파일에 키를 넣거나, 프로그램을 다시 실행해 키를 입력한 뒤 사용하세요.
          (이 상태에서는 모델 선택 칸이 보이지 않고, 이미지 품질 개선도 적용되지 않습니다.)
        </div>
      )}

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
          {higgsfield && (
            <div className="engine-options">
              <ModelPicker
                models={models}
                imageModel={prod.visual.image_model}
                videoModel={prod.visual.video_model}
                disabled={vRunning || lock}
                onChange={(body) => run("모델 변경 중", async () => setProd(await api.setModels(project.id, body)))}
                onRefresh={() => run("models", async () => setModels(await api.visualModels(true)))}
                refreshing={busy === "models"}
              />
              <label className="field">
                <span>레퍼런스 장면 구도 반영</span>
                <select
                  value={prod.visual.ref_follow || "medium"}
                  disabled={vRunning || lock}
                  onChange={(e) => run("모델 변경 중", async () => setProd(await api.setModels(project.id, { ref_follow: e.target.value })))}
                >
                  {Object.entries(FOLLOW_LABEL).map(([k, v]) => (
                    <option key={k} value={k}>
                      {v}
                    </option>
                  ))}
                </select>
              </label>
              <span className="muted small">
                그림체·인물·색감은 어느 단계든 레퍼런스를 복사하지 않습니다. 바꾼 뒤 [이미지 전체 새로 만들기]를 하면 장면 설계부터 반영됩니다.
              </span>
              {estimate && (
                <div className="estimate">
                  전체 예상 비용 <b>{usd(estimate.total_usd)}</b>
                  <span className="muted small">
                    {" "}
                    = 이미지 {usd(estimate.images_usd)} + 영상 {usd(estimate.videos_usd)} (총 {estimate.video_seconds}초)
                    {!estimate.priced && " · 가격을 확인할 수 없는 모델이 있어 실제 비용은 더 나올 수 있습니다"}
                  </span>
                </div>
              )}
            </div>
          )}
          {prod.visual.concept_note && (
            <details className="concept-box" open={!st.videos}>
              <summary>
                <b className="small">레퍼런스에서 빌려 온 것 · 새로 만든 것</b>
              </summary>
              <div className="pre small">{prod.visual.concept_note}</div>
              <details className="detail-toggle">
                <summary>이미지 AI에 넘기는 설정 (영어)</summary>
                <div className="small muted brief">
                  <b>그림체</b> {prod.visual.style_guide || "-"}
                  <br />
                  <b>배경·공간</b> {prod.visual.world || "-"}
                  <br />
                  <b>인물</b> {prod.visual.character || "(인물 없음)"}
                  {prod.visual.product_scale && (
                    <>
                      <br />
                      <b>제품 크기</b> {prod.visual.product_scale}
                    </>
                  )}
                </div>
              </details>
            </details>
          )}
          {prod.visual.cast_image && (
            <div className="cast-box">
              <img src={url(prod.visual.cast_image, prod.visual.cast_v)} alt="인물 기준" onClick={() => openItem("cast:image")} title="크게 보기" />
              <div className="stack-tight">
                <b className="small">인물 기준</b>
                {anchor && vs[anchor]?.has_person ? (
                  <span className="muted small">첫 장면(기준 장면)의 인물입니다. 모든 장면에 이 인물이 나옵니다. 인물을 바꾸려면 첫 장면 이미지를 다시 만드세요.</span>
                ) : (
                  <>
                    <span className="muted small">첫 장면의 그림체로 만든 새 인물입니다. 인물이 나오는 장면에 이 인물이 나옵니다.</span>
                    <button
                      className="btn small"
                      disabled={vRunning || lock}
                      onClick={() => {
                        if (confirmCost("인물 기준 이미지를 다시 만듭니다. 장면에 반영하려면 이후 그 장면 이미지를 다시 만들어야 합니다.", estimate?.image_usd_each ?? 0))
                          startJob("cast", () => api.regenerateCast(project.id));
                      }}
                    >
                      ↻ 인물 다시 만들기
                    </button>
                  </>
                )}
              </div>
            </div>
          )}
          <TrackProgress job={vJob} />
          <ol className="flow-steps small">
            <li className={st.images ? "done" : ""}>장면 설계 → 첫 장면(기준) → 나머지 장면 이미지</li>
            <li className={st.images_approved ? "done" : ""}>확인 · 마음에 안 드는 장면만 지시를 넣어 다시 만들기 → 전체 승인</li>
            <li className={st.videos ? "done" : ""}>영상화 · 마음에 안 드는 장면만 다시 만들기</li>
          </ol>
          <div className="row wrap">
            <button className={`btn small ${st.images ? "" : "primary"}`} disabled={vRunning || lock} onClick={() => makeImages(undefined)}>
              {busy === "images" ? <span className="spinner tiny" /> : null}
              {st.images ? "이미지 전체 새로 만들기" : "이미지 생성 시작"}
            </button>
            <button
              className="btn small primary"
              disabled={vRunning || lock || st.images < st.total || !toAnimate.length}
              title={st.images < st.total ? "모든 장면의 이미지가 있어야 합니다" : ""}
              onClick={approveAll}
            >
              {busy === "approve" ? <span className="spinner tiny" /> : null}
              이미지 전체 승인 → 영상화{st.videos && toAnimate.length ? ` (${toAnimate.length}개)` : ""}
            </button>
          </div>
          {!st.images && !vRunning && (
            <span className="muted small">
              예상 소요: 장면 설계 약 1~2분 + 이미지 {parallelEta("image", Math.max(st.total, 1), false).replace("예상 소요 ", "")}
            </span>
          )}
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
              <span>저장된 목소리 · {prod.sound.settings.tempo.toFixed(2)}x</span>
            </div>
          </div>
          {typecast ? (
            <TTSPanel form={form} setForm={setForm} voices={voices} disabled={sRunning || lock} onPreview={preview} previewing={busy === "preview"} />
          ) : (
            <p className="muted small">타입캐스트 키가 없어 임시 음성으로 만듭니다 (목소리·배속 조절은 타입캐스트에서만 됩니다).</p>
          )}
          <TrackProgress job={sJob} />
          {settingsDirty && st.audios > 0 && <span className="small warn-text">설정을 바꿨습니다. 다시 만드는 문장부터 새 설정이 적용됩니다.</span>}
          <div className="row wrap">
            <button className="btn small primary" disabled={sRunning || lock} onClick={() => makeSound()}>
              {busy === "sound" ? <span className="spinner tiny" /> : null}
              {st.audios ? "이 설정으로 음성 전체 재생성" : "▶ 음성 생성 시작"}
            </button>
          </div>
        </div>
      </section>

      <div className={`selection-bar ${sel.length ? "active" : ""}`}>
        <label className="row">
          <input type="checkbox" checked={allSelected} onChange={() => setSelected(allSelected ? new Set() : new Set(scenes.map((s) => s.id)))} />
          <span className="small">
            {sel.length ? (
              <>
                <b>{sel.length}개 장면 선택됨</b> ({sel.map(sceneNo).join(", ")})
              </>
            ) : (
              "☑ 장면 왼쪽 체크박스로 여러 장면을 골라 한 번에 다시 만들 수 있습니다 (맨 앞 체크박스 = 전체 선택)"
            )}
          </span>
        </label>
        {sel.length > 0 && (
          <div className="stack-tight grow">
            <AutoTextarea
              value={selInstruction}
              onChange={setSelInstruction}
              placeholder={`선택한 장면 모두에 줄 수정 지시 (선택) — ${IMAGE_HINT}`}
            />
            {anchorNote(sel) && <span className="small warn-text">{anchorNote(sel)}</span>}
            <div className="row wrap">
              <button className="btn small" disabled={vRunning || lock} onClick={() => makeImages(sel, selInstruction.trim()) && setSelInstruction("")}>
                이미지 다시 만들기
              </button>
              <button className="btn small" disabled={vRunning || lock} onClick={() => remakeVideos(sel, selInstruction.trim())}>
                영상 다시 만들기
              </button>
              <button className="btn small" disabled={sRunning || lock} onClick={() => makeSound(sel)}>
                음성 다시 만들기
              </button>
              <button className="btn small ghost" onClick={() => setSelected(new Set())}>
                선택 해제
              </button>
              <span className="muted small">{parallelEta("image", sel.length, !!selInstruction.trim())} (이미지 기준)</span>
            </div>
          </div>
        )}
      </div>

      <section className="prod-table">
        <div className="prod-row prod-head">
          <div>장면</div>
          <div>대사 · 장면 설계</div>
          <div>이미지</div>
          <div>영상 클립</div>
          <div>음성 (문장별 다시 만들기)</div>
        </div>
        {scenes.map((s, i) => {
          const va = vs[s.id];
          const sa = ss[s.id];
          const dur = s.end - s.start;
          const over = sa && sa.lines.length > 0 && sa.duration > dur + 0.05;
          const prev = va?.prev;
          // 다시 만드는 중에는 비교 대신 진행 표시를 보여 준다
          const comparingImage = !!prev && !va?.busy && prev.image !== va?.image;
          const comparingVideo = !!prev && !va?.busy && !comparingImage && !!prev.video && prev.video !== va?.video;
          const isAnchor = s.id === anchor;
          const editImage = editing?.sceneId === s.id && editing.kind === "image";
          const editVideo = editing?.sceneId === s.id && editing.kind === "video";
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
                {isAnchor && (
                  <span className="chip anchor-chip" title="나머지 장면이 이 장면의 그림체·인물·분위기를 따릅니다">
                    기준 장면
                  </span>
                )}
              </div>
              <div className="prod-text">
                <div className="pre">{s.dialogue || <span className="muted">(대사 없음)</span>}</div>
                {va?.instruction && <div className="small instruction-note">✎ 반영한 수정 지시: {va.instruction}</div>}
                {va?.prompt && (
                  <details className="detail-toggle">
                    <summary>장면 설계 (이미지 AI 프롬프트){va.motion ? ` · ${va.motion}` : ""}</summary>
                    <div className="small muted brief">{va.prompt}</div>
                    {va.video_prompt && <div className="small muted brief">영상: {va.video_prompt}</div>}
                  </details>
                )}
              </div>

              <div className="media-cell">
                <div
                  className={`media-box ${va?.image ? "zoomable" : ""} ${comparingImage ? "comparing" : ""}`}
                  style={{ aspectRatio: ratio }}
                  onClick={() => va?.image && openItem(`${s.id}:image`)}
                  title={va?.image ? "크게 보기" : ""}
                >
                  {va?.image ? <img src={url(va.image, va.v)} alt="" /> : <span className="muted small">대기</span>}
                  {comparingImage && <span className="compare-tag">비교 중 ↓</span>}
                  <BusyOverlay asset={va} kind="image" typical={prod.typical.image} now={now} />
                </div>
                <button
                  className={`btn small regen-btn ${editImage ? "on" : ""}`}
                  disabled={vRunning || lock || !!va?.busy}
                  title="수정 지시를 넣어 이 장면 이미지만 다시 만들기"
                  onClick={() => setEditing(editImage ? null : { kind: "image", sceneId: s.id })}
                >
                  ↻ 이미지 수정
                </button>
                {va?.error && !va.busy && (
                  <div className="cell-error">
                    <ErrorText message={va.error} />
                  </div>
                )}
              </div>

              <div className="media-cell">
                <div
                  className={`media-box ${va?.video ? "zoomable" : ""} ${comparingVideo ? "comparing" : ""}`}
                  style={{ aspectRatio: ratio }}
                  onClick={() => va?.video && openItem(`${s.id}:video`)}
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
                  {comparingVideo && <span className="compare-tag">비교 중 ↓</span>}
                  <BusyOverlay asset={va} kind="video" typical={prod.typical.video} now={now} />
                </div>
                <button
                  className={`btn small regen-btn ${editVideo ? "on" : ""}`}
                  disabled={vRunning || lock || !va?.video || !!va?.busy}
                  title={va?.video ? "수정 지시를 넣어 이 장면 영상만 다시 만들기" : "이미지 전체 승인 후 영상화됩니다"}
                  onClick={() => setEditing(editVideo ? null : { kind: "video", sceneId: s.id })}
                >
                  ↻ 영상 수정
                </button>
              </div>

              <div className="audio-cell">
                {sa?.busy && (
                  <div className="audio-busy small">
                    <span className="spinner tiny" />
                    {sa.busy === "queued" ? "순서 대기 중" : `음성 만드는 중 · ${fmtDur(now - sa.busy_since)} 경과`}
                  </div>
                )}
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
                            {busy === `${s.id}-${n + 1}` ? (
                              <>
                                <span className="spinner tiny" /> 만드는 중… ({range(prod.typical.line)})
                              </>
                            ) : (
                              "↻ 이 문장만"
                            )}
                          </button>
                        </div>
                        {line.error && (
                          <div className="cell-error">
                            <ErrorText message={line.error} />
                          </div>
                        )}
                      </div>
                    ))}
                    <span className={`small ${over ? "over" : "muted"}`}>
                      합계 {sa.duration.toFixed(1)}s / 장면 {dur.toFixed(1)}s{over && " · 장면보다 김"}
                    </span>
                  </>
                ) : sa?.v ? (
                  <span className="muted small">대사 없음 (무음)</span>
                ) : !sa?.busy ? (
                  <span className="muted small">대기</span>
                ) : null}
                <button className="icon-btn small-btn" disabled={sRunning || lock} title="이 장면 음성 전체 다시 만들기" onClick={() => makeSound([s.id])}>
                  ↻
                </button>
              </div>

              {/* 이전/새 비교와 수정 지시는 장면 줄 아래 전체 폭으로 (좁은 칸에 넣으면 옆 칸과 겹친다) */}
              {(comparingImage || comparingVideo) && prev && va && (
                <ComparePanel
                  kind={comparingImage ? "image" : "video"}
                  scene={sceneNo(s.id)}
                  ratio={ratio}
                  prevSrc={url((comparingImage ? prev.image : prev.video) ?? "", prev.v)}
                  newSrc={url((comparingImage ? va.image : va.video) ?? "", va.v)}
                  prevNote={prev.instruction}
                  newNote={va.instruction}
                  disabled={lock || !!va.busy}
                  onChoose={(keep) => choose(s.id, keep)}
                  onZoom={(items, index) => setView({ items, index })}
                />
              )}
              {editImage && (
                <div className="row-panel">
                  <RegenForm
                    kind="image"
                    scene={sceneNo(s.id)}
                    count={1}
                    eta={parallelEta("image", 1, true)}
                    cost={billable ? usd(imageCost([s.id])) : ""}
                    disabled={vRunning || lock}
                    note={anchorNote([s.id])}
                    onCancel={() => setEditing(null)}
                    onSubmit={(text) => makeImages([s.id], text)}
                  />
                </div>
              )}
              {editVideo && (
                <div className="row-panel">
                  <RegenForm
                    kind="video"
                    scene={sceneNo(s.id)}
                    count={1}
                    eta={parallelEta("video", 1, true)}
                    cost={billable ? usd(videoCost([s.id])) : ""}
                    disabled={vRunning || lock}
                    onCancel={() => setEditing(null)}
                    onSubmit={(text) => remakeVideos([s.id], text)}
                  />
                </div>
              )}
            </div>
          );
        })}
      </section>

      <section className="card reset-card">
        <div className="row wrap">
          <b className="small">초기화</b>
          <span className="muted small">만든 결과를 지우고 처음부터 다시 시작합니다. 고른 모델·목소리·배속은 남습니다.</span>
          <span className="push" />
          <button className="btn small ghost danger" disabled={vRunning || lock} onClick={() => reset("visual")}>
            이미지·영상 초기화
          </button>
          <button className="btn small ghost danger" disabled={sRunning || lock} onClick={() => reset("sound")}>
            음성 초기화
          </button>
          <button className="btn small danger" disabled={vRunning || sRunning || lock} onClick={() => reset("all")}>
            영상 제작 단계 전체 초기화
          </button>
        </div>
      </section>

      <footer className="action-bar">
        <span className="muted">
          {st.ready
            ? "영상 클립과 음성이 모두 준비되었습니다. 마음에 안 드는 장면·문장만 다시 만든 뒤 전체 승인하세요."
            : `이미지 ${st.images}/${st.total} · 영상 클립 ${st.videos}/${st.total} · 장면 음성 ${st.audios}/${st.total} · 다 만들지 않아도 지금까지 만든 것만 받을 수 있습니다`}
          {st.comparing ? ` · 이전/새 결과를 고를 장면 ${st.comparing}개` : ""}
          {" · 이미지·영상을 누르면 전체화면으로 봅니다"}
        </span>
        <button
          className="btn primary"
          disabled={vRunning || sRunning || lock}
          title={vRunning || sRunning ? "진행 중인 작업이 끝난 뒤 넘어갈 수 있습니다" : ""}
          onClick={() => {
            if (!st.ready) {
              const missing = [
                st.images < st.total && `이미지 ${st.total - st.images}개`,
                st.videos < st.total && `영상 클립 ${st.total - st.videos}개`,
                st.audios < st.total && `장면 음성 ${st.total - st.audios}개`,
              ].filter(Boolean);
              if (
                !confirm(
                  `아직 만들지 않은 결과물이 있습니다: ${missing.join(", ")}.\n\n지금까지 만든 것만 다운로드 목록에 나옵니다. 나중에 5단계로 돌아와 이어서 만들 수 있습니다.\n\n다음 단계로 넘어갈까요?`,
                )
              )
                return;
            }
            run("확정 중", async () => onNext(await api.confirmProduction(project.id)));
          }}
        >
          {project.completed ? "결과물 다운로드 →" : st.ready ? "전체 승인 · 결과물 받기 →" : "지금까지 만든 것으로 결과물 받기 →"}
        </button>
      </footer>

      {view && <Lightbox items={view.items} index={view.index} onIndex={(i) => setView({ ...view, index: i })} onClose={closeView} />}
    </div>
  );
}
