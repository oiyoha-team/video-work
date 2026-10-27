// backend/schemas 와 1:1로 맞춘 타입. 스키마를 바꾸면 여기도 같이 수정할 것.

export type AspectRatio = "1:1" | "4:5" | "16:9" | "9:16";

export interface JobState {
  status: "idle" | "running" | "done" | "error";
  progress: number;
  message: string;
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
  claude_configured: boolean;
  claude_model: string;
  stt_engine: string;
  whisper_model: string;
  visual_engine: string;
  sound_engine: string;
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
export interface VisualAsset {
  prompt: string; // 장면 브리프 (장면 분석 + 자사 대사 + 제품 이미지 기반)
  motion: string;
  image: string | null;
  video: string | null;
  error: string;
  v: number;
}

export interface SoundLine {
  text: string;
  audio: string | null;
  duration: number;
}

export interface SoundAsset {
  lines: SoundLine[]; // 문장 하나 = 음성 파일 하나
  duration: number;
  error: string;
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

export interface Production {
  visual: { engine: string; scenes: Record<string, VisualAsset> };
  sound: { engine: string; voice: string; scenes: Record<string, SoundAsset> };
  status: { total: number; videos: number; audios: number; ready: boolean };
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
  name: string;
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
