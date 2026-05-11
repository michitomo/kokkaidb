"""Pydanticモデル定義: パイプライン全体で使用するデータ構造

スキーマ規約 (docs/STRUCTURER_REWRITE.md §2.12):

- 「未取得値」と「意図的に空」を None / "" で区別する。
  - None: 値が取得できなかった / 該当しない (例: 衆議院セッションの mediasp_hash)
  - "": 取得を試みたが空文字列だった / 構造上必須だが現時点で値がない (例: 表記なし)
- 数値型・任意のメタデータ: `int | None = None`、`float | None = None`
- 文字列型:
  - 必須フィールド (常に何らかの値を持つべき): `str = ""`
  - 任意フィールド (取得できないことがある): `str | None = None`
- 表記ゆれ (例: `斎藤` vs `斉藤`、`城内` vs `城内大臣`) は metadata.speakers の表記を
  正解として normalizer が utterances 内で統一する (`src/normalizer.py`)。
- JSON シリアライズ時の `null` ↔ `""` 不整合を避けるため、新規フィールド追加時は
  この方針を踏襲し、`scripts/validate_data_schema.py` で検証可能にしておくこと。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# QA品質評価指標 V2.0 (QQ/AS/OC 12軸フレームワーク)
# docs/uiux-review/05-qa-quality-metrics.md 参照
# ---------------------------------------------------------------------------

CitedSourceType = Literal[
    "number", "organization", "law", "date", "past_answer", "field_case", "other"
]
ConcreteItemType = Literal["number", "proper_noun", "deadline", "evidence_citation"]
StakeholderConcreteness = Literal["abstract", "mid", "concrete"]
DirectnessLabel = Literal["directly", "partially", "tangentially", "not_at_all"]
CommitmentLevel = Literal[0, 1, 2, 3, 4]
ScoringConfidence = Literal["low", "medium", "high"]
AnswererSeniority = Literal["minister", "vice_minister", "bureaucrat", "reference", "other"]


class CitedSource(BaseModel):
    type: CitedSourceType
    excerpt: str


class ConcreteItem(BaseModel):
    type: ConcreteItemType
    excerpt: str


class QQ1Clarity(BaseModel):
    """QQ-1 論点明確度 (Clarity)"""
    main_question_one_liner: str
    sub_asks: list[str] = Field(default_factory=list)
    score: float = Field(ge=0.0, le=1.0)


class QQ2Groundedness(BaseModel):
    """QQ-2 具体性・一次ソース密度 (Groundedness)"""
    cited_sources: list[CitedSource] = Field(default_factory=list)
    translates_big_number_to_daily_life: bool = False
    score: float = Field(ge=0.0, le=1.0)


class QQ4Stakeholder(BaseModel):
    """QQ-4 当事者性 (Stakeholder salience)"""
    stakeholder_category: str | None = None
    concreteness: StakeholderConcreteness
    score: float = Field(ge=0.0, le=1.0)


class QQ5Actionability(BaseModel):
    """QQ-5 行動要求度 (Actionability)"""
    is_yes_no_form: bool = False
    has_deadline: bool = False
    presents_options: bool = False
    shifts_burden_of_proof: bool = False
    score: float = Field(ge=0.0, le=1.0)


class AS1Directness(BaseModel):
    """AS-1 直接回答度 (Directness) ← 旧 evasion_score の反転"""
    addresses_main_question: DirectnessLabel
    topic_shift_detected: bool = False
    score: float = Field(ge=0.0, le=1.0)


class AS2InformationDensity(BaseModel):
    """AS-2 具体情報量 (Information density)"""
    concrete_items_in_answer: list[ConcreteItem] = Field(default_factory=list)
    score: float = Field(ge=0.0, le=1.0)


class AS4Commitment(BaseModel):
    """AS-4 コミットメント強度 (Commitment level) Lv0-4"""
    level: CommitmentLevel
    trigger_phrase: str | None = None
    matched_pattern: str | None = None


class OC1RecordValue(BaseModel):
    """OC-1 議事録価値 (Record value)"""
    pins_legal_interpretation: bool = False
    fixes_official_number: bool = False
    goes_beyond_precedent: bool = False
    surfaces_government_uncertainty: bool = False
    answerer_seniority: AnswererSeniority = "other"
    score: float = Field(ge=0.0, le=1.0)


class OC3Quotability(BaseModel):
    """OC-3 引用可能性 (Quotability)"""
    quote_candidate: str | None = None
    score: float = Field(ge=0.0, le=1.0)


class QAMetrics(BaseModel):
    """V4評価プロンプトの出力（QQ/AS/OC 9軸 + 補助フィールド）

    score_schema_version: "2.0", prompt_version: "V4"
    """
    qq1_clarity: QQ1Clarity
    qq2_groundedness: QQ2Groundedness
    qq4_stakeholder: QQ4Stakeholder
    qq5_actionability: QQ5Actionability
    as1_directness: AS1Directness
    as2_information_density: AS2InformationDensity
    as4_commitment: AS4Commitment
    oc1_record_value: OC1RecordValue
    oc3_quotability: OC3Quotability
    scoring_confidence: ScoringConfidence
    evaluation_note: str
    would_be_referenced: ScoringConfidence
    issue_in_design: str | None = None
    prompt_version: str = "V4"
    schema_version: str = "2.0"

SessionKind = Literal[
    "regular_qa",
    "representative_questions",
    "floor_speech",
    "procedural",
    "expert_hearing",
]

SpeakerRole = Literal[
    "委員長",
    "議長",
    "質疑者",
    "答弁者",
    "政府参考人",
    "参考人",
    "その他",
]

SPEAKER_ROLES: frozenset[str] = frozenset(
    ("委員長", "議長", "質疑者", "答弁者", "政府参考人", "参考人", "その他")
)


class SpeakerInfo(BaseModel):
    """発言者情報（セッション詳細ページから抽出）"""

    name: str
    affiliation: str
    role: str = ""  # SpeakerRole 値域に正規化される（scrapers/_role.derive_role）
    start_seconds: float
    start_time: str  # HH:MM 形式
    duration_minutes: int


class SessionDetail(BaseModel):
    """セッション詳細（metadata.json に対応）"""

    chamber: str  # "shugiin" | "sangiin"
    session_id: str
    date: str  # YYYY-MM-DD
    committee: str
    committee_id: int | None = None
    session_number: int | None = None
    session_kind: SessionKind = "regular_qa"
    duration: str = ""
    hls_url: str
    mediasp_hash: str = ""  # 参議院のみ: mediasp.jp の hash 値
    source_url: str
    processed_at: str = ""
    whisper_model: str = "openai/whisper-large-v3-turbo"
    llm_model: str = "google/gemma-4-31B-it"
    speakers: list[SpeakerInfo]


class WhisperSegment(BaseModel):
    """Whisper API の verbose_json セグメント"""

    id: int
    seek: int
    start: float
    end: float
    text: str
    tokens: list[int] = Field(default_factory=list)
    temperature: float = 0.0
    avg_logprob: float = 0.0
    compression_ratio: float = 0.0
    no_speech_prob: float = 0.0


class SegmentTranscript(BaseModel):
    """1発言者セグメントの文字起こし結果"""

    segment_index: int
    speaker_name: str
    start_seconds: float
    text: str
    whisper_segments: list[WhisperSegment] = Field(default_factory=list)


class RawTranscript(BaseModel):
    """raw_transcript.json に対応"""

    session_id: str
    corrected: bool = False
    corrected_at: str = ""
    segments: list[SegmentTranscript]


class Utterance(BaseModel):
    """話者タグ付き発言（utterances.json の utterances 配列要素）"""

    speaker: str
    role: str  # SpeakerRole 値域に正規化される（normalizer.normalize_utterances）
    text: str
    unmatched: bool = False  # speaker が metadata.speakers と一致しない場合 True


class SegmentUtterances(BaseModel):
    """1発言者セグメントの話者タグ付き発言群（utterances.json の segments 要素）"""

    segment_index: int
    segment_speaker: str
    segment_affiliation: str
    start_seconds: float
    video_url: str
    utterances: list[Utterance]


class UtterancesOutput(BaseModel):
    """utterances.json のルート"""

    segments: list[SegmentUtterances]


class QuestionDetail(BaseModel):
    """Q&Aペアの質問側"""

    speaker: str
    party: str
    summary: str
    full_text: str
    intent: str  # fact_check / policy_proposal / accountability / information_request / その他


class AnswerDetail(BaseModel):
    """Q&Aペアの答弁側"""

    speaker: str
    role: str
    summary: str
    full_text: str


class QAPair(BaseModel):
    """Q&Aペアの1エントリ（qa_pairs.json の pairs 要素）"""

    id: str
    segment_index: int
    topic: str
    question: QuestionDetail
    answer: AnswerDetail
    follow_up_ids: list[str] = Field(default_factory=list)
    related_law_ids: list[str] = Field(default_factory=list)
    video_url: str
    metrics: QAMetrics | None = None  # V4評価プロンプト出力（score_schema_version 2.0）


class QAPairsOutput(BaseModel):
    """qa_pairs.json のルート"""

    pairs: list[QAPair]
    score_schema_version: str = "1.0"  # V4評価適用後は "2.0" になる
    prompt_version: str = ""  # "V4" 等


class KeyCommitment(BaseModel):
    speaker: str
    role: str
    text: str
    topic: str
    qa_id: str | None = None


class RelatedLawTag(BaseModel):
    """LLMが判定した関連法案タグ"""

    law_id: str
    qa_ids: list[str] = Field(default_factory=list)


class SummaryOutput(BaseModel):
    """summary.json のルート"""

    session_summary: str
    key_topics: list[str]
    key_commitments: list[KeyCommitment]
    related_laws: list[RelatedLawTag] = Field(default_factory=list)


class Topic(BaseModel):
    name: str
    description: str
    related_qa_ids: list[str] = Field(default_factory=list)
    related_speakers: list[str] = Field(default_factory=list)


class TopicsOutput(BaseModel):
    """topics.json のルート"""

    topics: list[Topic]
