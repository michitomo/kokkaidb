/**
 * 共通型定義: data.ts と generate-api.ts で共有
 */

// ---------------------------------------------------------------------------
// QA品質評価指標 V2.0 (QQ/AS/OC 12軸フレームワーク)
// docs/uiux-review/05-qa-quality-metrics.md 参照
// ---------------------------------------------------------------------------

export type CitedSourceType = 'number' | 'organization' | 'law' | 'date' | 'past_answer' | 'field_case' | 'other';
export type ConcreteItemType = 'number' | 'proper_noun' | 'deadline' | 'evidence_citation';
export type StakeholderConcreteness = 'abstract' | 'mid' | 'concrete';
export type DirectnessLabel = 'directly' | 'partially' | 'tangentially' | 'not_at_all';
export type CommitmentLevel = 0 | 1 | 2 | 3 | 4;
export type ScoringConfidence = 'low' | 'medium' | 'high';
export type AnswererSeniority = 'minister' | 'vice_minister' | 'bureaucrat' | 'reference' | 'other';

export interface CitedSource {
  type: CitedSourceType;
  excerpt: string;
}

export interface ConcreteItem {
  type: ConcreteItemType;
  excerpt: string;
}

export interface QQ1Clarity {
  main_question_one_liner: string;
  sub_asks: string[];
  score: number;
}

export interface QQ2Groundedness {
  cited_sources: CitedSource[];
  translates_big_number_to_daily_life: boolean;
  score: number;
}

export interface QQ4Stakeholder {
  stakeholder_category: string | null;
  concreteness: StakeholderConcreteness;
  score: number;
}

export interface QQ5Actionability {
  is_yes_no_form: boolean;
  has_deadline: boolean;
  presents_options: boolean;
  shifts_burden_of_proof: boolean;
  score: number;
}

export interface AS1Directness {
  addresses_main_question: DirectnessLabel;
  topic_shift_detected: boolean;
  score: number;
}

export interface AS2InformationDensity {
  concrete_items_in_answer: ConcreteItem[];
  score: number;
}

export interface AS4Commitment {
  level: CommitmentLevel;
  trigger_phrase: string | null;
  matched_pattern: string | null;
}

export interface OC1RecordValue {
  pins_legal_interpretation: boolean;
  fixes_official_number: boolean;
  goes_beyond_precedent: boolean;
  surfaces_government_uncertainty: boolean;
  answerer_seniority: AnswererSeniority;
  score: number;
}

export interface OC3Quotability {
  quote_candidate: string | null;
  score: number;
}

export interface QAMetrics {
  qq1_clarity: QQ1Clarity;
  qq2_groundedness: QQ2Groundedness;
  qq4_stakeholder: QQ4Stakeholder;
  qq5_actionability: QQ5Actionability;
  as1_directness: AS1Directness;
  as2_information_density: AS2InformationDensity;
  as4_commitment: AS4Commitment;
  oc1_record_value: OC1RecordValue;
  oc3_quotability: OC3Quotability;
  scoring_confidence: ScoringConfidence;
  evaluation_note: string;
  would_be_referenced: ScoringConfidence;
  issue_in_design: string | null;
  prompt_version: string;
  schema_version: string;
}

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
  metrics?: QAMetrics;
}

export interface QAPairsOutput {
  pairs: QAPair[];
  score_schema_version?: string;
  prompt_version?: string;
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
