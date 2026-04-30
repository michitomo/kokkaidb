"""Pydanticモデル定義: パイプライン全体で使用するデータ構造"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SpeakerInfo(BaseModel):
    """発言者情報（セッション詳細ページから抽出）"""

    name: str
    affiliation: str
    role: str = ""  # 質疑者 / 答弁者 / 委員長 / 政府参考人 / 参考人 / その他
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
    role: str  # 委員長 / 質疑者 / 答弁者 / 政府参考人 / 参考人 / その他
    text: str


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
    # 質問の質指標（新設）
    question_sharpness: float = Field(ge=0.0, le=1.0, default=0.5)
    """質問の鋭さ: 問いが一文で言い切れるか、Yes/No・数値・期限で答えられるか (0=漠然, 1=精密)"""
    evidence_grounding: float = Field(ge=0.0, le=1.0, default=0.5)
    """根拠品質: 1次ソース・統計・過去答弁への言及度 (0=主観のみ, 1=1次ソース明示)"""


class AnswerDetail(BaseModel):
    """Q&Aペアの答弁側"""

    speaker: str
    role: str
    summary: str
    full_text: str
    # 答弁の質指標（新設）
    answer_completeness: float = Field(ge=0.0, le=1.0, default=0.5)
    """答弁網羅性: 質問の全論点を具体的に答えたか (0=完全回避, 1=全問に具体的回答)"""
    commitment_strength: float = Field(ge=0.0, le=1.0, default=0.0)
    """コミット強度: 約束の具体性・拘束力 (0=なし, 0.2=曖昧, 0.5=具体的行動, 0.8=期限付, 1.0=即時実施)"""
    commitment_text: str | None = ""
    # 後方互換フィールド（旧データ読み込み用。新規生成では不要）
    evasion_score: float = Field(ge=0.0, le=1.0, default=0.5)
    has_commitment: bool = False


class QAPair(BaseModel):
    """Q&Aペアの1エントリ（qa_pairs.json の pairs 要素）"""

    id: str
    segment_index: int
    topic: str
    question: QuestionDetail
    answer: AnswerDetail
    # ペアレベル指標（新設）
    record_value: float = Field(ge=0.0, le=1.0, default=0.5)
    """議事録価値: この質疑で議事録に残る新事実・解釈・前進があるか (0=既知のみ, 1=先例更新)"""
    follow_up_ids: list[str] = Field(default_factory=list)
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
