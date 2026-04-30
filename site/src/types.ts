/**
 * 共通型定義: data.ts と generate-api.ts で共有
 */

export type SessionKind =
  | 'regular_qa'
  | 'representative_questions'
  | 'floor_speech'
  | 'procedural'
  | 'expert_hearing';

export type SpeakerRole = '委員長' | '質疑者' | '答弁者' | '政府参考人' | '参考人' | 'その他';

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
  session_kind?: SessionKind;
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
}

export interface QAAnswer {
  speaker: string;
  role: string;
  summary: string;
  full_text: string;
  evasion_score: number;
  has_commitment: boolean;
  commitment_text: string;
}

export interface QAPair {
  id: string;
  segment_index: number;
  topic: string;
  question: QAQuestion;
  answer: QAAnswer;
  follow_up_ids: string[];
  related_law_ids?: string[];
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
