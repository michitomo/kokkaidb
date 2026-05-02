"""pipeline._run_step6 の session_kind 分岐テスト"""

from __future__ import annotations

from unittest.mock import patch

from src.models import (
    KeyCommitment,
    QAPair,
    QAPairsOutput,
    QuestionDetail,
    AnswerDetail,
    SegmentUtterances,
    SessionDetail,
    SpeakerInfo,
    SummaryOutput,
    Topic,
    TopicsOutput,
    Utterance,
    UtterancesOutput,
)
from src.pipeline import _run_step6


def _make_session_detail(session_kind: str, committee: str = "厚生労働委員会") -> SessionDetail:
    return SessionDetail(
        chamber="shugiin",
        session_id="56149",
        date="2026-04-09",
        committee=committee,
        session_kind=session_kind,  # type: ignore[arg-type]
        hls_url="https://example.com/x.m3u8",
        source_url="https://example.com/detail",
        speakers=[
            SpeakerInfo(
                name="高市早苗",
                affiliation="内閣総理大臣",
                role="答弁者",
                start_seconds=0.0,
                start_time="13:00",
                duration_minutes=10,
            ),
        ],
    )


def _make_utterances() -> UtterancesOutput:
    return UtterancesOutput(
        segments=[
            SegmentUtterances(
                segment_index=0,
                segment_speaker="高市早苗",
                segment_affiliation="内閣総理大臣",
                start_seconds=0.0,
                video_url="",
                utterances=[Utterance(speaker="高市早苗", role="答弁者", text="お答えします。")],
            )
        ]
    )


def _make_qa(pid: str) -> QAPair:
    return QAPair(
        id=pid,
        segment_index=0,
        topic="t",
        question=QuestionDetail(
            speaker="x", party="y", summary="s", full_text="f", intent="other"
        ),
        answer=AnswerDetail(
            speaker="z",
            role="答弁者",
            summary="s",
            full_text="f" * 50,
            evasion_score=0.1,
            has_commitment=False,
            commitment_text="",
        ),
        video_url="",
    )


class TestFloorLikeKindsSkipQA:
    def test_floor_speech_skips_qa_extraction(self) -> None:
        sd = _make_session_detail("floor_speech", "本会議")
        with (
            patch("src.pipeline.generate_qa_pairs") as gen_qa,
            patch("src.pipeline.generate_session_summary", return_value="要約"),
            patch(
                "src.pipeline.generate_topics_and_key_topics",
                return_value=(TopicsOutput(topics=[]), []),
            ),
            patch("src.pipeline.generate_key_commitments", return_value=[]),
            patch("src.pipeline.tag_related_laws") as tag_laws,
        ):
            qa, summary, topics = _run_step6(sd, _make_utterances(), max_workers=1)

        assert qa.pairs == []
        assert summary.session_summary == "要約"
        assert topics.topics == []
        gen_qa.assert_not_called()
        tag_laws.assert_not_called()

    def test_procedural_skips_qa_extraction(self) -> None:
        sd = _make_session_detail("procedural")
        with (
            patch("src.pipeline.generate_qa_pairs") as gen_qa,
            patch("src.pipeline.generate_session_summary", return_value=""),
            patch(
                "src.pipeline.generate_topics_and_key_topics",
                return_value=(TopicsOutput(topics=[]), []),
            ),
            patch("src.pipeline.generate_key_commitments", return_value=[]),
            patch("src.pipeline.tag_related_laws") as tag_laws,
        ):
            qa, _summary, _topics = _run_step6(sd, _make_utterances(), max_workers=1)

        assert qa.pairs == []
        gen_qa.assert_not_called()
        tag_laws.assert_not_called()


class TestRegularQARunsAllSteps:
    def test_regular_qa_runs_full_step6(self) -> None:
        sd = _make_session_detail("regular_qa")
        qa = QAPairsOutput(pairs=[_make_qa("qa_001")])
        commitments = [
            KeyCommitment(
                speaker="x", role="答弁者", text="commit", topic="t", qa_id="qa_001"
            )
        ]
        topics = TopicsOutput(
            topics=[
                Topic(
                    name="A",
                    description="d",
                    related_qa_ids=["qa_001"],
                    related_speakers=[],
                )
            ]
        )

        def tag(qa_pairs, **_kwargs):
            for p in qa_pairs.pairs:
                p.related_law_ids = ["law_001"]
            return qa_pairs

        with (
            patch("src.pipeline.generate_qa_pairs", return_value=qa) as gen_qa,
            patch("src.pipeline.generate_session_summary", return_value="要約"),
            patch(
                "src.pipeline.generate_topics_and_key_topics", return_value=(topics, ["A"])
            ),
            patch("src.pipeline.generate_key_commitments", return_value=commitments),
            patch("src.pipeline._load_laws_compact", return_value="law_001: [閣法] x | 厚生労働省"),
            patch("src.pipeline.tag_related_laws", side_effect=tag) as tag_laws,
        ):
            qa_out, summary, topics_out = _run_step6(sd, _make_utterances(), max_workers=1)

        gen_qa.assert_called_once()
        tag_laws.assert_called_once()
        assert qa_out.pairs[0].related_law_ids == ["law_001"]
        assert summary.related_laws[0].law_id == "law_001"
        assert summary.related_laws[0].qa_ids == ["qa_001"]
        assert summary.key_topics == ["A"]
        assert topics_out.topics[0].name == "A"

    def test_representative_questions_passes_skip_proposal(self) -> None:
        sd = _make_session_detail("representative_questions", committee="本会議")
        with (
            patch("src.pipeline.generate_qa_pairs", return_value=QAPairsOutput(pairs=[])) as gen_qa,
            patch("src.pipeline.generate_session_summary", return_value=""),
            patch(
                "src.pipeline.generate_topics_and_key_topics",
                return_value=(TopicsOutput(topics=[]), []),
            ),
            patch("src.pipeline.generate_key_commitments", return_value=[]),
        ):
            _run_step6(sd, _make_utterances(), max_workers=1)

        kwargs = gen_qa.call_args.kwargs
        assert kwargs["skip_proposal_segments"] is True
