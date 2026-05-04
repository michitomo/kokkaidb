"""Whisper文字起こしのLLM後処理修正

Whisperが生成したraw_transcriptを、セッションのコンテキスト（発言者・委員会・議題）を
踏まえてLLMに修正させる。句読点補完・固有名詞修正・誤認識修正を行う。

パイプライン内ではStep 4（Whisper）→ Step 4.5（本モジュール）→ Step 5（話者タグ）の順。
既存データの修正には単体で実行可能:
    python -m src.transcript_corrector --dir data/shugiin/2026/04/09/56149_本会議
    python -m src.transcript_corrector --all    # data/ 配下の未修正を全て処理

高速化: whisper_segments を2000文字バンドルしたチャンク単位で並列処理する。
1セグメント(最大2万文字)をそのまま投げるより5〜11倍高速。
"""

from __future__ import annotations

import argparse
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.api_client import get_client, with_retry
from src.models import RawTranscript, SegmentTranscript, SessionDetail, SpeakerInfo

# Step 4.5はDeepSeek-V3.2を使用（prompt cachingで長いsystem promptのコストを削減）
CORRECTOR_MODEL = "google/gemma-4-31B-it"

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))

CHUNK_CHAR_LIMIT = 2000

SYSTEM_PROMPT = """あなたは国会議事録の校正専門家です。
Whisper音声認識が生成したテキストを、以下の観点で修正してください。

## 修正ルール
1. **句読点の補完**: 文末に「。」、疑問文に「？」を補う。読点「、」を適切に挿入する
2. **固有名詞の修正**: 議員名・政党名・会派名・委員会名・法案名の誤認識を修正する。
   - 発言者リストの名前・所属（政党・会派）は**確定情報**として扱う。テキスト内に同音の誤変換があれば必ず発言者リストの表記に修正する
   - 例: 発言者リストに「吉川里奈（参政党）」とある場合、テキスト内の「賛成党」「さんせい党」はすべて「参政党」の誤認識として修正する
   - 例: 発言者リストに「平将明」とある場合、テキスト内の「平正明」「平まさあき」は「平将明」に修正する
3. **同音異義語の修正**: 文脈に合わない漢字変換を修正する
   - 例: 「介護保険」→ 皆保険制度の文脈なら「国民皆保険」
   - 例: 「懸念」→ 哀悼・黙祷・震災追悼の文脈では「祈念」が正しい（「復興を祈念する」「祈念いたします」）
   - 例: 「猶予」→ 支払い猶予・執行猶予などの法的文脈では文脈確認の上修正
4. **繰り返し・フィラーの除去**: 「あの」「えー」「まあ」等の不要なフィラーを除去する。Whisperが拾った音声ノイズも除去する（後述）
5. **改行**: 話者交代の可能性がある箇所で改行（\\n\\n）を入れる。委員長の指名発言（「〇〇君」）の前後は必ず改行する

## Whisper音声認識ノイズの取り扱い
Whisperはメイン発言者以外の音声（PA放送・隣席のマイク・委員長の呼びかけ等）を
発言文中に混入させることがある。以下のパターンを**除去してよい**:

- 話者名の2回以上の繰り返し（例: 「石井啓一議長、石井啓一議長、石井啓一議長。」）
- 文脈に合わない固有名詞の単独出現（例: 「成長型経済すなわち**岩田和親**こうした中」の「岩田和親」は発言者名の呼びかけノイズ）
- 「議長＊○○君」「＊○○君」のような特殊記号付き挿入句

**ノイズ除去後の処理**: 前後のテキストを直接つなぐ。「……」は絶対に挿入しない。
文の末尾が「を」「が」「は」等の助詞で終わる不完全な形になっても、そのまま次の文に続ける。

## 第221回国会（令和8年特別会）固有名詞リファレンス

### 政党・会派の正式名称（Whisperの漢字変換ミスに注意）
- チームみらい（「チーム未来」「チーム三来」等は誤り → チームみらい）
- 自由民主党（自民党）
- 立憲民主党
- 日本維新の会
- 公明党
- 国民民主党
- 日本共産党（共産党）
- 参政党（「賛成党」「さんせい党」は誤り → 参政党）
- れいわ新選組（「令和新選組」は誤り → れいわ新選組）
- 日本保守党
- 社会民主党（社民党）

### 主要閣僚（第2次高市内閣）
- 高市早苗（たかいちさなえ）内閣総理大臣
- 木原稔（きはらみのる）内閣官房長官
- 茂木敏充（もてぎとしみつ）外務大臣
- 片山さつき（かたやまさつき）財務大臣・金融担当
- 林芳正（はやしよしまさ）総務大臣
- 平口洋（ひらぐちひろし）法務大臣
- 松本洋平（まつもとようへい）文部科学大臣
- 上野賢一郎（うえのけんいちろう）厚生労働大臣
- 鈴木憲和（すずきのりかず）農林水産大臣
- 赤澤亮正（あかざわりょうせい）経済産業大臣
- 金子恭之（かねこやすし）国土交通大臣
- 石原宏高（いしはらひろたか）環境大臣
- 小泉進次郎（こいずみしんじろう）防衛大臣
- 松本尚（まつもとたかし）デジタル大臣
- 城内実（きうちみのる）経済財政政策担当
- 小野田紀美（おのだきみ）経済安全保障担当

### 衆議院議長・副議長
- 森英介（もりえいすけ）衆議院議長
- 石井啓一（いしいけいいち）衆議院副議長

### 参議院議長・副議長
- 関口昌一（せきぐちまさかず）参議院議長
- 福山哲郎（ふくやまてつろう）参議院副議長

### 主要法案
- 健康保険法等の一部を改正する法律案（高額療養費制度、OTC類似薬）
- 防災庁設置法案
- 国家情報会議設置法案
- 社会福祉法等の一部を改正する法律案
- 労働者災害補償保険法等の一部を改正する法律案
- ヒトゲノム編集胚等の取扱いの規制に関する法律案

### 頻出する国会用語・近音誤変換に注意すべき語
- 高額療養費（こうがくりょうようひ）
- OTC類似薬（オーティーシーるいじやく）
- 選定療養（せんていりょうよう）
- 一部保険外療養
- 破滅的医療支出
- 予見可能性
- 国民皆保険（こくみんかいほけん）
- 祈念（きねん）: Whisperが「懸念（けねん）」と誤変換することがある。哀悼・黙祷・復興の文脈では「祈念」が正しい

## 禁止事項
- テキストの意味を変えない。要約・省略・追加をしない
- 発言の順序を変えない
- 存在しない発言を捏造しない
- 発言者リストに記載された名前の表記を勝手に変えない
- 「……」を**絶対に**出力しない（例外なし）。元のテキストが不完全であっても、聞き取れない箇所があっても、ノイズを除去した後も、「……」は一切使用しない。前後テキストを直接つなぐこと

修正後のテキストのみを返してください。JSON形式ではなく、プレーンテキストで返してください。"""


# ---------------------------------------------------------------------------
# チャンク分割
# ---------------------------------------------------------------------------

@dataclass
class CorrectionChunk:
    """whisper_segmentsをバンドルした校正単位。"""
    segment_index: int
    chunk_index: int
    text: str
    whisper_segment_ids: list[int]  # 元のwhisper_segment.idリスト


def _chunk_segment(seg: SegmentTranscript, char_limit: int = CHUNK_CHAR_LIMIT) -> list[CorrectionChunk]:
    """1セグメントのwhisper_segmentsをchar_limit文字ごとにバンドルする。

    whisper_segmentsが空の場合は、テキスト全体を1チャンクとして返す。
    """
    ws_list = seg.whisper_segments
    if not ws_list:
        return [CorrectionChunk(
            segment_index=seg.segment_index,
            chunk_index=0,
            text=seg.text,
            whisper_segment_ids=[],
        )]

    chunks: list[CorrectionChunk] = []
    current_texts: list[str] = []
    current_ids: list[int] = []
    current_len = 0
    chunk_idx = 0

    for ws in ws_list:
        ws_text = ws.text
        ws_len = len(ws_text)

        current_texts.append(ws_text)
        current_ids.append(ws.id)
        current_len += ws_len

        # whisper_segment を追加した後で上限チェック → 文の途中で切れない
        if current_len >= char_limit:
            chunks.append(CorrectionChunk(
                segment_index=seg.segment_index,
                chunk_index=chunk_idx,
                text="".join(current_texts),
                whisper_segment_ids=list(current_ids),
            ))
            chunk_idx += 1
            current_texts = []
            current_ids = []
            current_len = 0

    # 残りを最後のチャンクとして追加
    if current_texts:
        chunks.append(CorrectionChunk(
            segment_index=seg.segment_index,
            chunk_index=chunk_idx,
            text="".join(current_texts),
            whisper_segment_ids=list(current_ids),
        ))

    return chunks


# ---------------------------------------------------------------------------
# LLM呼び出し
# ---------------------------------------------------------------------------

def correct_chunk(
    text: str,
    speaker: SpeakerInfo,
    all_speakers: list[SpeakerInfo],
    committee: str,
) -> str:
    """1チャンクのWhisperテキストをLLMで修正する。"""
    client = get_client()

    speaker_list = "\n".join(
        f"- {s.name}（{s.affiliation}）" for s in all_speakers
    )

    user_prompt = f"""## セッション情報
委員会: {committee}
主発言者: {speaker.name}（{speaker.affiliation}）

## 発言者リスト
{speaker_list}

## 修正対象テキスト（Whisper出力）
{text}"""

    response = with_retry(lambda: client.chat.completions.create(
        model=CORRECTOR_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
        max_tokens=8192,
    ))

    content = response.choices[0].message.content
    if not content:
        logger.warning("Empty correction response, using original text")
        return text

    return content.strip()


# ---------------------------------------------------------------------------
# メイン処理
# ---------------------------------------------------------------------------

def correct_transcript(
    raw_transcript: RawTranscript,
    session_detail: SessionDetail,
    max_workers: int = 8,
) -> RawTranscript:
    """全セグメントのWhisperテキストをチャンク分割して並列LLM修正する。

    whisper_segmentsを2000文字バンドルしたチャンク単位で並列処理し、
    結果をセグメントごとに再結合する。

    Args:
        raw_transcript: Whisper生成の文字起こし
        session_detail: セッション詳細（speakers, committee等）
        max_workers: 並列数

    Returns:
        修正済みのRawTranscript（corrected=True）
    """
    if raw_transcript.corrected:
        logger.info("Transcript already corrected, skipping")
        return raw_transcript

    speakers = session_detail.speakers

    def _resolve_speaker(seg: SegmentTranscript) -> SpeakerInfo:
        if seg.segment_index < len(speakers):
            return speakers[seg.segment_index]
        matched = next((s for s in speakers if s.name == seg.speaker_name), None)
        return matched or SpeakerInfo(
            name=seg.speaker_name,
            affiliation="",
            start_seconds=seg.start_seconds,
            start_time="",
            duration_minutes=0,
        )

    # 全セグメントをチャンクに分割
    all_chunks: list[tuple[CorrectionChunk, SpeakerInfo]] = []
    for seg in raw_transcript.segments:
        speaker = _resolve_speaker(seg)
        chunks = _chunk_segment(seg)
        for chunk in chunks:
            all_chunks.append((chunk, speaker))

    total_chunks = len(all_chunks)
    total_segments = len(raw_transcript.segments)
    logger.info(
        "Correcting %d segments → %d chunks (%.1fx parallelism, limit=%d chars)",
        total_segments, total_chunks, total_chunks / max(total_segments, 1),
        CHUNK_CHAR_LIMIT,
    )

    # 全チャンクを並列でLLM修正
    corrected_chunks: dict[tuple[int, int], str] = {}  # (seg_idx, chunk_idx) → corrected_text

    def _correct_one(item: tuple[CorrectionChunk, SpeakerInfo]) -> tuple[int, int, str, int]:
        chunk, speaker = item
        original_len = len(chunk.text)
        corrected_text = correct_chunk(
            chunk.text, speaker, speakers, session_detail.committee,
        )
        return chunk.segment_index, chunk.chunk_index, corrected_text, original_len

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_correct_one, item): item for item in all_chunks}
        done_count = 0
        for future in as_completed(futures):
            seg_idx, chunk_idx, corrected_text, original_len = future.result()
            corrected_len = len(corrected_text)

            chunk_obj, _ = futures[future]

            # 安全チェック1: ……が含まれていたら棄却（LLMが省略した証拠）
            if "……" in corrected_text:
                logger.warning(
                    "Chunk seg=%d chunk=%d: rejected (contains ……, %d→%d chars)",
                    seg_idx, chunk_idx, original_len, corrected_len,
                )
                corrected_text = chunk_obj.text

            # 安全チェック2: 80%未満に縮んだ場合は棄却
            ratio = corrected_len / original_len if original_len > 0 else 1.0
            if ratio < 0.8:
                logger.warning(
                    "Chunk seg=%d chunk=%d: rejected (%.0f%%, %d→%d chars)",
                    seg_idx, chunk_idx, ratio * 100, original_len, corrected_len,
                )
                corrected_text = chunk_obj.text  # 元テキストを使用

            corrected_chunks[(seg_idx, chunk_idx)] = corrected_text
            done_count += 1
            if done_count % 10 == 0 or done_count == total_chunks:
                logger.info("Corrected %d/%d chunks", done_count, total_chunks)

    # チャンクをセグメントごとに再結合
    results: list[SegmentTranscript] = []
    for seg in raw_transcript.segments:
        chunks = _chunk_segment(seg)
        corrected_parts = [
            corrected_chunks[(seg.segment_index, c.chunk_index)]
            for c in chunks
        ]
        corrected_text = "\n".join(corrected_parts)

        original_len = len(seg.text)
        corrected_len = len(corrected_text)
        ratio = corrected_len / original_len if original_len > 0 else 1.0
        logger.info(
            "Segment %d (%s): %d → %d chars (%.0f%%)",
            seg.segment_index, seg.speaker_name,
            original_len, corrected_len, ratio * 100,
        )

        results.append(SegmentTranscript(
            segment_index=seg.segment_index,
            speaker_name=seg.speaker_name,
            start_seconds=seg.start_seconds,
            text=corrected_text,
            whisper_segments=seg.whisper_segments,
        ))

    return RawTranscript(
        session_id=raw_transcript.session_id,
        corrected=True,
        corrected_at=datetime.now(JST).isoformat(),
        segments=results,
    )


def correct_session_dir(session_dir: Path, max_workers: int = 8) -> bool:
    """data/配下の1セッションディレクトリを修正する。

    Returns:
        True if corrected, False if skipped or failed
    """
    transcript_path = session_dir / "raw_transcript.json"
    metadata_path = session_dir / "metadata.json"

    if not transcript_path.exists() or not metadata_path.exists():
        logger.debug("Skipping %s: missing files", session_dir)
        return False

    raw_transcript = RawTranscript.model_validate_json(
        transcript_path.read_text(encoding="utf-8")
    )

    if raw_transcript.corrected:
        logger.debug("Skipping %s: already corrected", session_dir)
        return False

    session_detail = SessionDetail.model_validate_json(
        metadata_path.read_text(encoding="utf-8")
    )

    logger.info("Correcting %s (%d segments)", session_dir.name, len(raw_transcript.segments))

    corrected = correct_transcript(raw_transcript, session_detail, max_workers=max_workers)

    transcript_path.write_text(
        corrected.model_dump_json(indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("Saved corrected transcript: %s", transcript_path)
    return True


def correct_all(data_dir: Path, max_workers: int = 8) -> tuple[int, int]:
    """data/ 配下の未修正セッションを全て修正する。

    Returns:
        (corrected_count, skipped_count)
    """
    corrected = 0
    skipped = 0

    for transcript_path in sorted(data_dir.rglob("raw_transcript.json")):
        session_dir = transcript_path.parent
        if correct_session_dir(session_dir, max_workers=max_workers):
            corrected += 1
        else:
            skipped += 1

    return corrected, skipped


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    parser = argparse.ArgumentParser(
        description="Whisper文字起こしのLLM後処理修正"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--dir",
        type=Path,
        help="修正対象のセッションディレクトリ（例: data/shugiin/2026/04/09/56149_本会議）",
    )
    group.add_argument(
        "--all",
        action="store_true",
        help="data/ 配下の未修正セッションを全て修正",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(__file__).parent.parent.parent / "data",
        help="data/ ディレクトリのパス（--all 使用時）",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="LLM並列数（デフォルト: 8）",
    )

    args = parser.parse_args()

    if args.dir:
        success = correct_session_dir(args.dir, max_workers=args.workers)
        if not success:
            logger.info("No correction needed or failed")
            sys.exit(1)
    else:
        corrected, skipped = correct_all(args.data_dir, max_workers=args.workers)
        logger.info("Done: %d corrected, %d skipped", corrected, skipped)


if __name__ == "__main__":
    main()
