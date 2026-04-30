/**
 * 共通型定義: data.ts と generate-api.ts で共有
 */

export interface SpeakerInfo {
  name: string;
  affiliation: string;
  role: string;
  start_seconds: number;
  start_time: string;
  duration_minutes: number;
}

export interface SessionMetadata {
  chamber: string;
  session_id: string;
  date: string;
  committee: string;
  duration: string;
  hls_url: string;
  source_url: string;
  processed_at: string;
  whisper_model: string;
  llm_model: string;
  speakers: SpeakerInfo[];
}

export interface QAQuestion {
  speaker: string;
  party: string;
  summary: string;
  full_text: string;
  intent: string;
  /** 質問の鋭さ: 0=漠然, 1=精密 */
  question_sharpness?: number;
  /** 根拠品質: 0=主観のみ, 1=1次ソース明示 */
  evidence_grounding?: number;
}

export interface QAAnswer {
  speaker: string;
  role: string;
  summary: string;
  full_text: string;
  /** 答弁網羅性: 0=完全回避, 1=全問に具体的回答 */
  answer_completeness?: number;
  /** コミット強度: 0=なし, 0.5=具体的行動, 1=即時実施 */
  commitment_strength?: number;
  commitment_text: string;
  /** @deprecated answer_completeness を使用 */
  evasion_score?: number;
  /** @deprecated commitment_strength を使用 */
  has_commitment?: boolean;
}

export interface QAPair {
  id: string;
  segment_index: number;
  topic: string;
  question: QAQuestion;
  answer: QAAnswer;
  /** 議事録価値: 0=既知のみ, 1=先例更新 */
  record_value?: number;
  follow_up_ids: string[];
  video_url: string;
}

export interface QAPairsOutput {
  pairs: QAPair[];
}

export interface KeyCommitment {
  speaker: string;
  role: string;
  text: string;
  topic: string;
  qa_id: string;
}

export interface RelatedLawTag {
  law_id: string;
  qa_ids: string[];
}

export interface SessionSummary {
  session_summary: string;
  key_topics: string[];
  key_commitments: KeyCommitment[];
  related_laws?: RelatedLawTag[];
}

export interface Topic {
  name: string;
  description: string;
  related_qa_ids: string[];
  related_speakers: string[];
}

export interface TopicsOutput {
  topics: Topic[];
}
