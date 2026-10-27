// backend/planning/labels.py 와 동일하게 유지

export const ROLES: Record<string, string> = {
  hook: "훅",
  problem: "문제제기",
  empathy: "공감",
  solution: "해결책",
  product: "제품소개",
  proof: "증거/후기",
  benefit: "효과",
  offer: "혜택/프로모션",
  cta: "CTA",
  other: "기타",
};

export const SHOT_TYPES: Record<string, string> = {
  "extreme-close-up": "익스트림 클로즈업",
  "close-up": "클로즈업",
  medium: "미디엄",
  full: "풀샷",
  wide: "와이드",
  insert: "인서트",
  graphic: "그래픽/텍스트",
};

// 장면 상세 항목 (backend planning/labels.py SCENE_DETAIL과 동일)
export const SCENE_DETAIL = {
  subject: "피사체·인물",
  action: "행동·표정",
  background: "장소·배경·소품",
  composition: "구도·카메라 앵글",
  lighting: "조명·색감",
  product: "제품 노출",
} as const;

export const ASPECT_RATIOS = ["1:1", "4:5", "16:9", "9:16"] as const;

export const roleLabel = (r: string) => ROLES[r] ?? (r || "-");

export function fmtTime(sec: number): string {
  const s = Math.max(0, sec);
  const m = Math.floor(s / 60);
  const rest = s - m * 60;
  const whole = Math.abs(rest - Math.round(rest)) < 0.05;
  return `${m}:${whole ? String(Math.round(rest)).padStart(2, "0") : rest.toFixed(1).padStart(4, "0")}`;
}

// 대사는 '한 줄 = 한 문장'. 마침표·물음표·느낌표 뒤에서 끊는다 (backend planning/text.py와 동일)
export function splitSentences(text: string): string[] {
  return text
    .split("\n")
    .flatMap((line) => line.split(/(?<=[.!?])\s+/))
    .map((s) => s.trim())
    .filter(Boolean);
}

// 한글 음절 + 영숫자 대략적인 발화 길이
export const syllables = (text: string) => (text.match(/[가-힣A-Za-z0-9]/g) ?? []).length;
export const SYLLABLES_PER_SEC = 5;
