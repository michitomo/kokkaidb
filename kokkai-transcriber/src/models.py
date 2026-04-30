"""Pydanticモデル定義: パイプライン全体で使用するデータ構造"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

SessionKind = Literal[
    "regular_qa",
    "representative_questions",
    "floor_speech",
    "procedural",
    "expert_hearing",
]

SpeakerRole = Literal[
    "委員長",
    "質疑者",
    "答弁者",
    "政府参考人",
    "参考人",
    "その他",
]

SPEAKER_ROLES: frozenset[str] = frozenset(
    ("委員長", "質疑者", "答弁者", "政府参考人", "参考人", "その他")
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
    llm_model: str = "deepseek-ai/DeepSeek-V3.2"
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
    evasion_score: float = Field(ge=0.0, le=1.0)
    has_commitment: bool
    commitment_text: str | None = ""


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


class QAPairsOutput(BaseModel):
    """qa_pairs.json のルート"""

    pairs: list[QAPair]


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
