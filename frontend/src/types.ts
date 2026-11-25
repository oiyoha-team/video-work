// backend/schemas 와 1:1로 맞춘 타입. 스키마를 바꾸면 여기도 같이 수정할 것.

export type AspectRatio = "1:1" | "4:5" | "16:9" | "9:16";

export interface JobState {
  status: "idle" | "running" | "done" | "error";
  progress: number;
  message: string;
  // 진행 표시 (없으면 막대만 움직임)
  started_at?: number; // epoch 초
  eta_min?: number | null; // 남은 시간 범위 (초)
  eta_max?: number | null;
  eta_at?: number; // eta 계산 시각
  done?: number;
  total?: number;
}

export interface Project {
  id: string;
  name: string;
  created_at: string;
  updated_at: string;
  step: number;
  completed: boolean;
  aspect_ratio: AspectRatio | null;
  analysis_job: JobState;
  script_job: JobState;
  visual_job: JobState;
  sound_job: JobState;
}

export const JOB_FIELDS = ["analysis_job", "script_job", "visual_job", "sound_job"] as const;

export interface Status {
  platform: "windows" | "mac" | "linux";
  launcher: string;
  app_version: string;
  claude_configured: boolean;
  claude_model: string;
  stt_engine: string;
  whisper_model: string;
  visual_engine: string;
  sound_engine: string;
  visual_engine_id: "higgsfield" | "mock";
  sound_engine_id: "typecast" | "system" | "silent";
  flow_enabled: boolean;
  max_video_sec: number;
  aspect_ratios: AspectRatio[];
}

// ── 승인 게이트 ──
export type GateKind = "analysis" | "script" | "images" | "production";

export const GATE_STEP: Record<GateKind, number> = { analysis: 1, script: 3, images: 5, production: 5 };

export interface Gate {
  id: string;
  project_id: string;
  project_name: string;
  kind: GateKind;
  title: string;
  summary: string;
  status: "pending" | "approved" | "revised" | "superseded";
  comment: string;
  created_at: string;
  resolved_at: string | null;
  resolved_via: string | null;
  notified: string[];
}

// ── Step 5 · 6 ──
export interface VisualVersion {
  image: string | null;
  video: string | null;
  prompt: string;
  motion: string;
  video_prompt: string;
  image_approved: boolean;
  instruction: string;
  v: number;
}

export interface VisualAsset {
  // 컷 하나 (장면 하나에 컷이 여러 개 있을 수 있음 — Production.visual.scene_cuts)
  scene_id: string;
  start: number; // 장면 시작 기준 컷 위치 (초)
  end: number;
  ref_frame: string | null;
  ref_desc: string; // 대응 레퍼런스 컷 묘사
  split: boolean; // 레퍼런스의 긴 샷을 나눈 컷 (다른 샷으로 변주)
  note: string; // 직접 추가한 컷의 내용
  added: boolean;
  link_prev: boolean; // 앞 장면 컷과 같은 샷이 이어짐 → 이미지·영상을 새로 만들지 않고 이어 씀
  prompt: string; // 컷 이미지 프롬프트 (영어)
  motion: string;
  video_prompt: string;
  image: string | null;
  has_person: boolean;
  image_approved: boolean; // [이미지 전체 승인] 후 영상화
  video: string | null;
  error: string; // 무엇 실패 / 원인: … / 해결: … / [원문] … (줄바꿈으로 구분)
  instruction: string; // 마지막으로 반영한 수정 지시
  prev: VisualVersion | null; // 다시 만들기 전 결과 (이전/새 비교)
  busy: "" | "queued" | "image" | "video";
  busy_since: number;
  v: number;
}

export interface SoundLine {
  text: string;
  audio: string | null;
  duration: number;
  error: string;
  v: number;
}

export interface TTSSettings {
  tempo: number; // 0.5 ~ 2
  emotion: string; // smart = 앞뒤 문맥으로 자동
  emotion_intensity: number; // 0 ~ 2
  pitch: number; // -12 ~ 12
}

export interface SoundAsset {
  lines: SoundLine[]; // 문장 하나 = 음성 파일 하나
  duration: number;
  error: string;
  busy: "" | "queued" | "audio";
  busy_since: number;
  v: number;
}

export interface ExportItem {
  key: string;
  group: "clips" | "audio" | "images" | "docs";
  label: string;
  path: string;
  filename: string;
  size: number;
  scene: number | null;
}

export interface ExportList {
  groups: { key: ExportItem["group"]; label: string }[];
  items: ExportItem[];
}

// 힉스필드 모델 목록 (서버가 12시간마다 자동 갱신)
export interface ImageModel {
  id: string;
  label: string;
  recommended?: boolean; // 목록에 '추천' 표시
  usd: number | null; // 한 장 가격 (모르면 null)
  max_images: number; // 참고 이미지 최대 장수
}

export interface VideoModel {
  id: string;
  label: string;
  recommended?: boolean; // 목록에 '추천' 표시
  usd_per_sec: number | null;
  resolution: string | null;
  min_sec: number;
  max_sec: number;
}

export interface VisualModels {
  updated_at: string | null;
  image: ImageModel[];
  video: VideoModel[];
}

export interface Estimate {
  scenes: number;
  video_seconds: number;
  video_model: string;
  images_usd: number;
  videos_usd: number;
  total_usd: number;
  billable: boolean;
  priced: boolean; // 고른 모델 가격을 모두 알면 true
  image_model: string;
  image_usd_each: number;
  scene_video_usd: Record<string, number>;
}

export interface TypecastVoice {
  voice_id: string;
  name: string;
  gender: "male" | "female" | null;
  age: string | null;
  use_cases: string[];
  preview_url: string | null;
}



export interface Production {
  visual: {
    engine: string;
    image_model: string;
    video_model: string;
    style_guide: string; // 레퍼런스에서 빌려 온 그림체 (영어)
    world: string; // 새 배경·공간 (영어)
    concept_note: string; // 레퍼런스에서 가져온 것 / 새로 만든 것 (한국어)
    anchor_scene: string; // 기준 장면 (첫 장면)
    ref_follow: "low" | "medium" | "high"; // 레퍼런스 장면 구도 반영 정도
    scene_cuts: Record<string, string[]>; // 장면별 컷 순서 (없으면 [장면 id] 한 컷)
    character: string; // 새 인물 설정 (레퍼런스 인물과 얼굴·헤어·의상이 다름)
    cast_image: string | null; // 인물 기준 이미지
    cast_v: number;
    product_scale: string; // 제품 실제 크기
    scenes: Record<string, VisualAsset>;
  };
  sound: { engine: string; voice: string; voice_id: string; settings: TTSSettings; scenes: Record<string, SoundAsset> };
  status: {
    total: number; // 컷 수 (이미지·영상 단위)
    scenes: number; // 장면 수 (음성 단위)
    images: number;
    images_approved: number;
    videos: number;
    audios: number;
    lines: number;
    comparing: number; // 이전/새 결과를 아직 고르지 않은 장면
    ready: boolean;
  };
  typical: Record<"image" | "video" | "line" | "revise", [number, number]>; // 한 건당 보통 걸리는 시간 (초)
}

// ── Step 1 ──
// 장면 상세 — 이미지로 다시 만들 수 있을 만큼의 시각 정보 (backend schemas.SceneDetail)
export interface SceneDetail {
  subject: string;
  action: string;
  background: string;
  composition: string;
  lighting: string;
  product: string;
}

export interface Segment {
  index: number;
  start: number;
  end: number;
  frames: string[];
  scene: string;
  detail: SceneDetail;
  dialogue: string;
  shot_type: string;
  role: string;
  merged_from: number[];
  cuts?: RefCut[]; // 구간 안의 컷 (화면 전환 기준, 최대 2초)
}

export interface RefCut {
  start: number;
  end: number;
  frame: string; // 프로젝트 폴더 기준 경로
  split: boolean; // 한 샷이 길어 나눈 컷 (MAX_CUT_SEC를 쓸 때만)
  cont: boolean; // 앞 구간 마지막 컷과 같은 샷이 이어짐
  description: string;
}

export interface Overall {
  tone: { speech_level: string; pace: string; habits: string[]; description: string };
  concept: string;
  visual_style: string;
  persona: { age: string; gender: string; character: string; credibility: string };
  structure: { role: string; start: number; end: number; summary: string }[];
}

export interface ReferenceAnalysis {
  source: { file: string; duration_sec: number; width: number; height: number; detected_aspect_ratio: AspectRatio };
  segments: Segment[];
  overall: Overall;
  mock: boolean;
  confirmed: boolean;
}

// ── Step 2 ──
export interface ProductImage {
  id: string;
  path: string;
  note: string;
}

// 제품 정보 입력서(md) 양식과 같은 순서
export interface Product {
  library_id: string | null;
  template_name: string;
  name: string; // 1. 제품명
  usp: string; // 2. 제품 USP
  features: string[]; // 3. 제품 특징
  evidence: string; // 4. 사회적·수치적 근거 및 권위
  keywords: string[]; // 5. 제품 지칭 키워드
  forbidden_phrases: string[]; // 6. 들어가면 안 되는 표현
  detail_url: string; // 7. 상세페이지 URL
  extra: string; // 기타 메모
  images: { styled: ProductImage[]; cutout: ProductImage[] };
}

export const MAX_IMAGES_PER_KIND = 5;

export interface LibraryItem {
  library_id: string;
  name: string; // 템플릿 이름
  product_name: string;
  updated_at: number;
}

// ── Step 3 ──
export interface Scene {
  id: string;
  start: number;
  end: number;
  role: string;
  dialogue: string; // 한 줄 = 한 문장
  ref_segment: number | null;
}

export interface Script {
  version: number;
  status: "draft" | "final";
  mock: boolean;
  meta: {
    title: string;
    product_name: string;
    product_library_id: string | null;
    reference: string;
    total_duration_sec: number;
    aspect_ratio: AspectRatio;
  };
  voice: { persona: string; speech_level: string; pace: string; emotion: string };
  scenes: Scene[];
}

export interface ChatChange {
  scene_id: string;
  dialogue: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  changes?: ChatChange[];
  status?: "pending" | "applied" | "dismissed" | "none";
}

/** 링크로 받은 레퍼런스 영상 후보 (한 링크에서 여러 개가 나올 수 있음) */
export interface UrlCandidate {
  id: string;
  file: string;
  width: number;
  height: number;
  duration: number;
  aspect_ratio: string;
  has_audio: boolean;
}
