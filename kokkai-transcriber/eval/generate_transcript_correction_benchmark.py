"""transcript_corrector ベンチマークデータ生成スクリプト

現状のSYSTEM_PROMPTの課題点を整理し、プロンプト改善のベンチマークとなる
input/expected ペアを eval/golden/ に生成する。

Usage:
    cd kokkai-transcriber
    python -m eval.generate_transcript_correction_benchmark

生成ファイル（8ケース）:
    transcript_correction_{case_id}.input.json
    transcript_correction_{case_id}.expected.json

各ケースが検証するパターン:
    case01: 句読点補完・改行挿入（基本正解ケース）
    case02: 固有名詞修正 — 議員名・法案名の誤認識修正
    case03: アルファベット大文字化・話者名前書き整形
    case04: 同音異義語修正 — 「懸念」→「祈念」、「目答」→「黙祷」
    case05: 同音異義語修正 — 「一刻の優位」→「一刻の猶予」、委員長指名リスト
    case06: 【バグ確認】雑音混入時の「……」不正挿入（雑音: 話者名が音声内に混入）
    case07: 【バグ確認】雑音混入時の「……」不正挿入（雑音: PA音声反復が混入）
    case08: 【バグ確認】党名誤認識「賛成党」→「参政党」の未修正 + フィラー除去
"""

from __future__ import annotations

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "shugiin" / "2026"
GOLDEN_DIR = Path(__file__).resolve().parent / "golden"

# transcript_corrector.py から流用（プロンプト改善の評価対象）
SYSTEM_PROMPT = """あなたは国会議事録の校正専門家です。
Whisper音声認識が生成したテキストを、以下の観点で修正してください。

## 修正ルール
1. **句読点の補完**: 文末に「。」、疑問文に「？」を補う。読点「、」を適切に挿入する
2. **固有名詞の修正**: 議員名・政党名・会派名・委員会名・法案名の誤認識を修正する。発言者リストと委員会名を参考にすること
3. **同音異義語の修正**: 文脈に合わない漢字変換を修正する（例: 「介護保険」→文脈が皆保険制度の話なら「国民皆保険」）
4. **繰り返し・フィラーの除去**: 「あの」「えー」「まあ」等の不要なフィラーを除去する
5. **改行**: 話者交代の可能性がある箇所で改行（\\n\\n）を入れる。委員長の指名発言（「〇〇君」）の前後は必ず改行する

## 第221回国会（令和8年特別会）固有名詞リファレンス

### 政党・会派の正式名称（Whisperの漢字変換ミスに注意）
- チームみらい（「チーム未来」「チーム三来」等は誤り → チームみらい）
- 自由民主党（自民党）
- 立憲民主党
- 日本維新の会
- 公明党
- 国民民主党
- 日本共産党（共産党）
- 参政党
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

### 頻出する国会用語
- 高額療養費（こうがくりょうようひ）
- OTC類似薬（オーティーシーるいじやく）
- 選定療養（せんていりょうよう）
- 一部保険外療養
- 破滅的医療支出
- 予見可能性
- 国民皆保険（こくみんかいほけん）

## 禁止事項
- テキストの意味を変えない。要約・省略・追加をしない
- 発言の順序を変えない
- 存在しない発言を捏造しない
- 発言者リストに記載された名前の表記を勝手に変えない
- 「……」を出力しない。聞き取れない箇所があっても元のテキストをそのまま残すこと

修正後のテキストのみを返してください。JSON形式ではなく、プレーンテキストで返してください。"""


def _load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  wrote: {path.relative_to(PROJECT_ROOT)}")


def _build_user_prompt(
    committee: str,
    speaker_name: str,
    speaker_affiliation: str,
    all_speakers: list[dict],
    whisper_text: str,
) -> str:
    speaker_list = "\n".join(
        f"- {s['name']}（{s['affiliation']}）" for s in all_speakers
    )
    return (
        f"## セッション情報\n"
        f"委員会: {committee}\n"
        f"主発言者: {speaker_name}（{speaker_affiliation}）\n\n"
        f"## 発言者リスト\n{speaker_list}\n\n"
        f"## 修正対象テキスト（Whisper出力）\n{whisper_text}"
    )


def _whisper_text(segment: dict) -> str:
    ws = segment.get("whisper_segments", [])
    if ws:
        return "".join(w["text"] for w in ws)
    return segment["text"]


def _make_case(
    case_id: str,
    session_path: Path,
    seg_index: int,
    pattern: str,
    has_known_bug: bool,
    description: str,
    expected_text: str | None = None,
) -> None:
    """1ケースのinput/expectedファイルを生成する。

    expected_text が None の場合は corrected テキストをそのまま使用する。
    has_known_bug=True のケースでは expected_text を手動で指定すること。
    """
    transcript = _load_json(session_path / "raw_transcript.json")
    metadata = _load_json(session_path / "metadata.json")

    seg = transcript["segments"][seg_index]
    speakers = metadata["speakers"]

    # 主発言者を特定
    if seg_index < len(speakers):
        main_speaker = speakers[seg_index]
    else:
        matched = next((s for s in speakers if s["name"] == seg["speaker_name"]), None)
        main_speaker = matched or {"name": seg["speaker_name"], "affiliation": ""}

    whisper_text = _whisper_text(seg)
    user_prompt = _build_user_prompt(
        committee=metadata["committee"],
        speaker_name=main_speaker["name"],
        speaker_affiliation=main_speaker["affiliation"],
        all_speakers=speakers,
        whisper_text=whisper_text,
    )

    input_data = {
        "system_prompt": SYSTEM_PROMPT,
        "user_prompt": user_prompt,
        "metadata": {
            "session_id": metadata["session_id"],
            "segment_index": seg_index,
            "speaker": main_speaker["name"],
            "committee": metadata["committee"],
            "pattern": pattern,
            "has_known_bug": has_known_bug,
            "description": description,
            "whisper_char_count": len(whisper_text),
        },
    }

    if expected_text is None:
        expected_text = seg["text"]

    expected_data = {"corrected_text": expected_text}

    prefix = f"transcript_correction_{case_id}"
    _save_json(GOLDEN_DIR / f"{prefix}.input.json", input_data)
    _save_json(GOLDEN_DIR / f"{prefix}.expected.json", expected_data)


def generate_case01() -> None:
    """句読点補完・委員長開会宣言（基本正解ケース）

    Whisperは句読点・改行なし。LLMが適切に補完・挿入できるかを検証する。
    修正されるべき点:
    - 句読点（「。」「、」）の補完
    - 段落区切り（\\n\\n）の挿入
    - 「中間秀彦君。ほか40名」の余分な「。」の除去
    """
    _make_case(
        case_id="case01",
        session_path=DATA_DIR / "03/03/56089_予算委員会",
        seg_index=0,
        pattern="句読点補完・改行挿入",
        has_known_bug=False,
        description="予算委員会開会宣言（坂本哲志委員長）。句読点・改行の基本補完を検証する正解ケース。",
    )


def generate_case02() -> None:
    """固有名詞の誤認識修正（正解ケース）

    Whisperの主な誤認識:
    - 「平正明」→「平将明」（同音の別字）
    - 「全政権」→「前政権」（文脈から明確）
    - 「サイバー対象能力強化法」→「サイバー対処能力強化法」（法律名の誤認識）
    - 「裁判安全保障担当大臣」→「サイバー安全保障担当大臣」
    発言者リストに「平将明」が記載されているため、修正できるはず。

    注: セグメント全体は6873文字と長く「……」バグが含まれるため、
    最初のチャンク（2067文字）のみを対象とする。
    """
    transcript = _load_json(DATA_DIR / "03/03/56089_予算委員会" / "raw_transcript.json")
    metadata = _load_json(DATA_DIR / "03/03/56089_予算委員会" / "metadata.json")

    seg = transcript["segments"][1]
    speakers = metadata["speakers"]
    main_speaker = speakers[1]

    ws = seg.get("whisper_segments", [])

    # 最初のチャンク（2000文字）のみを抽出
    CHUNK_LIMIT = 2000
    chunk0_parts: list[str] = []
    total = 0
    for w in ws:
        chunk0_parts.append(w["text"])
        total += len(w["text"])
        if total >= CHUNK_LIMIT:
            break
    whisper_chunk0 = "".join(chunk0_parts)

    # correctedテキストの対応部分を抽出
    # 「名前をつけていただきたい」がchunk 0の末尾テキストに対応する位置
    corrected = seg["text"]
    boundary_phrase = "名前をつけていただきたい"
    boundary_idx = corrected.find(boundary_phrase)
    expected_text = corrected[:boundary_idx + len(boundary_phrase) + 50]

    user_prompt = _build_user_prompt(
        committee=metadata["committee"],
        speaker_name=main_speaker["name"],
        speaker_affiliation=main_speaker["affiliation"],
        all_speakers=speakers,
        whisper_text=whisper_chunk0,
    )

    input_data = {
        "system_prompt": SYSTEM_PROMPT,
        "user_prompt": user_prompt,
        "metadata": {
            "session_id": metadata["session_id"],
            "segment_index": 1,
            "chunk_index": 0,
            "speaker": main_speaker["name"],
            "committee": metadata["committee"],
            "pattern": "固有名詞誤認識修正（議員名・法案名）",
            "has_known_bug": False,
            "description": (
                "平将明議員の質疑（予算委員会）第1チャンク。"
                "Whisperが「平正明」「サイバー対象能力強化法」「全政権」等と誤認識した固有名詞の修正を検証する。"
                "発言者リストに「平将明（自由民主党・無所属の会）」が記載されている。"
            ),
            "expected_corrections": [
                "「平正明」→「平将明」（発言者リスト参照）",
                "「全政権」→「前政権」（文脈から同音修正）",
                "「サイバー対象能力強化法」→「サイバー対処能力強化法」（法案名誤認識）",
            ],
            "whisper_char_count": len(whisper_chunk0),
        },
    }

    _save_json(GOLDEN_DIR / "transcript_correction_case02.input.json", input_data)
    _save_json(GOLDEN_DIR / "transcript_correction_case02.expected.json", {"corrected_text": expected_text})


def generate_case03() -> None:
    """アルファベット大文字化・話者名前書き整形（正解ケース）

    Whisperの主な問題:
    - 「gdp」→「GDP」（アルファベット大文字化）
    - 句読点・読点の欠落
    - 話者名「片山さつき君」の指名発言前に改行なし
    修正後のcorrectedテキストに「武村展英君。」が冒頭に付加されている点も確認する。
    """
    _make_case(
        case_id="case03",
        session_path=DATA_DIR / "03/03/56092_財務金融委員会",
        seg_index=1,
        pattern="アルファベット大文字化・話者名前書き・句読点補完",
        has_known_bug=False,
        description="財務金融委員会での片山さつき財務大臣の所信聴取。GDP大文字化・委員長指名改行・句読点補完を検証する。",
    )


def generate_case04() -> None:
    """同音異義語の修正（正解ケース）

    Whisperの主な同音異義語誤変換:
    - 「懸念」→「祈念」（東日本大震災追悼文脈）
    - 「目答」→「黙祷」（黙祷の終了宣言）
    - 「一括指定議題」→「一括して議題」
    """
    _make_case(
        case_id="case04",
        session_path=DATA_DIR / "03/11/56116_予算委員会",
        seg_index=0,
        pattern="同音異義語修正（祈念・黙祷）",
        has_known_bug=False,
        description="予算委員会開会（東日本大震災15年追悼）。「懸念」→「祈念」「目答」→「黙祷」などの同音異義語修正を検証する。",
    )


def generate_case05() -> None:
    """同音異義語修正 + 委員長指名リスト整形（正解ケース）

    Whisperの主な問題:
    - 「委員閣議の御推挙」→「委員各位の御推挙」
    - 「一刻の優位も許されない」→「一刻の猶予も許されない」
    - 「党委員会に課せられた使命」→「当委員会に課せられた使命」
    - 理事指名リスト（「深崎ヘス君」「中曽根康隆君」等）の整形
    """
    _make_case(
        case_id="case05",
        session_path=DATA_DIR / "02/20/56079_拉致問題特別委員会",
        seg_index=1,
        pattern="同音異義語修正（一刻の猶予・当委員会）+ 委員長指名リスト整形",
        has_known_bug=False,
        description="拉致問題特別委員会の開会（長島昭久委員長の就任挨拶）。複数の同音異義語誤変換と理事指名リストの改行整形を検証する。",
    )


def generate_case06() -> None:
    """【バグ確認】雑音混入時の「……」不正挿入

    根本原因:
    Whisperが別話者の音声（PA等が流した「岩田和親」という呼びかけ）を
    メイン発言者の発言内に混入させた。LLMは「岩田和親」を雑音と正しく判断し
    削除しようとするが、その結果「成長型経済、すなわち……。」という
    禁止された「……」を自ら挿入してしまっている。

    Whisper原文: 「...成長型経済すなわち岩田和親こうした中...」
    現状(誤): 「...成長型経済、すなわち……。こうした中...」
    期待値: 雑音を除去し「……」を使わずに前後のテキストを自然につなぐ

    評価観点:
    - 「……」が出力に含まれていないこと（MUST）
    - 雑音「岩田和親」が除去されていること（MUST）
    - 前後のテキストが文脈的に自然につながっていること（SHOULD）
    """
    transcript = _load_json(DATA_DIR / "02/26/56086_予算委員会" / "raw_transcript.json")
    metadata = _load_json(DATA_DIR / "02/26/56086_予算委員会" / "metadata.json")
    seg = transcript["segments"][3]
    speakers = metadata["speakers"]
    main_speaker = speakers[3] if len(speakers) > 3 else {"name": seg["speaker_name"], "affiliation": ""}

    whisper_text = _whisper_text(seg)
    user_prompt = _build_user_prompt(
        committee=metadata["committee"],
        speaker_name=main_speaker["name"],
        speaker_affiliation=main_speaker["affiliation"],
        all_speakers=speakers,
        whisper_text=whisper_text,
    )

    # 理想的な期待値:
    # 雑音「岩田和親」を除去し、「すなわち」以降の文を自然に補完する。
    # 「……」は一切使用しない。
    expected_text = (
        "坂本哲志君。\n\n"
        "岩田和親君。\n\n"
        "予算の参考資料としてお手元にお配りした令和8年度の経済見通しと経済財政運営の基本的態度についてご説明いたします。\n"
        "我が国経済は、長く続いたデフレ、コストカット型経済から、その先にある新たな成長型経済へと移行しつつあります。"
        "こうした中、我が国経済は今後も緩やかな回復を続け、令和7年度の実質経済成長率は1.1%程度と見込みます。"
        "また、令和8年度は所得環境の改善が進む中で個人消費が増加するとともに、危機管理投資、成長投資の取り組みの進展等により設備投資も増加し、実質で1.3%程度の成長を見込みます。\n"
        "本経済見通しで示した経済の姿を実現できるよう、経済財政運営に万全を期してまいります。以上で私からの説明を終わります。\n\n"
        "以上をもちまして補足説明は終わりました。\n"
        "この際、参考人出席要求に関する件についてお諮りいたします。"
        "ただいま説明を聴取いたしました令和8年度総予算の審議中、日本銀行及び独立行政法人等の役職員から意見を聴取する必要が生じました場合には、"
        "参考人として出席を求めることとし、その人選等諸般の手続につきましては、委員長にご一任願いたいと存じますが、ご異議ありませんか。\n\n"
        "ご異議なしと認めます。よって、そのように決しました。\n\n"
        "次回は明27日午前9時から委員会を開会し、基本的質疑を行うこととし、本日はこれにて散会いたします。"
    )

    input_data = {
        "system_prompt": SYSTEM_PROMPT,
        "user_prompt": user_prompt,
        "metadata": {
            "session_id": metadata["session_id"],
            "segment_index": 3,
            "speaker": main_speaker["name"],
            "committee": metadata["committee"],
            "pattern": "雑音（呼びかけ音声）混入による「……」不正挿入",
            "has_known_bug": True,
            "bug_description": (
                "Whisperが別の音声チャンネルから「岩田和親」という呼びかけをメイン発言に混入させた。"
                "現状のLLMは雑音を除去するが代わりに禁止されている「……」を挿入してしまう。"
                "期待値では「……」を使わず、前後のテキストを自然につなぐ。"
            ),
            "noise_text": "岩田和親",
            "current_bug_output": "成長型経済、すなわち……。",
            "expected_behavior": "雑音を除去して前後テキストを「……」なしで接続する",
            "description": "予算委員会（岩田和親内閣府副大臣の補足説明）。Whisperが混入させた雑音テキスト「岩田和親」をLLMが除去する際に「……」を不正挿入するバグを確認するケース。",
            "whisper_char_count": len(whisper_text),
        },
    }

    expected_data = {
        "corrected_text": expected_text,
        "evaluation_criteria": {
            "must_not_contain": ["……"],
            "must_not_contain_reason": "SYSTEM_PROMPTで「……」の出力を明示的に禁止している",
            "must_not_contain_noise": ["岩田和親"],
            "must_not_contain_noise_reason": "「岩田和親」は雑音テキストであり除去されるべき",
        },
    }

    prefix = "transcript_correction_case06"
    _save_json(GOLDEN_DIR / f"{prefix}.input.json", input_data)
    _save_json(GOLDEN_DIR / f"{prefix}.expected.json", expected_data)


def generate_case07() -> None:
    """【バグ確認】PA音声反復による「……」不正挿入

    根本原因:
    Whisperがスピーカーシステム（PA）から流れた「石井啓一議長、石井啓一議長、石井啓一議長。」
    という繰り返し音声を、メイン発言者の発言文中に混入させた。
    これにより「所得税の課税最低減を」で文が途切れ、
    LLMが次の文（「以上、財政政策の...」）とつなぐために「……」を挿入してしまっている。

    Whisper原文（該当部分）:
      ws[22]: 「...所得税の課税最低減を」（文が途中で終わる）
      ws[23]: 「石井啓一議長、石井啓一議長、石井啓一議長。」（PA音声の繰り返し）
      ws[24]: 「以上、財政政策の基本的な考え方と、...」（次の段落）

    現状(誤): 「...所得税の課税最低限を……。\n\n以上、財政政策の...」
    期待値: 「……」を使わず、文脈から自然な補完を行うか、そのまま接続する

    評価観点:
    - 「……」が出力に含まれていないこと（MUST）
    - 「石井啓一議長、石井啓一議長」の反復が除去されていること（MUST）
    - 「課税最低限」の誤字（課税最低減→最低限）が修正されていること（SHOULD）
    """
    transcript = _load_json(DATA_DIR / "02/20/56075_本会議" / "raw_transcript.json")
    metadata = _load_json(DATA_DIR / "02/20/56075_本会議" / "metadata.json")
    seg = transcript["segments"][4]
    speakers = metadata["speakers"]
    main_speaker = speakers[4] if len(speakers) > 4 else {"name": seg["speaker_name"], "affiliation": ""}

    whisper_text = _whisper_text(seg)
    user_prompt = _build_user_prompt(
        committee=metadata["committee"],
        speaker_name=main_speaker["name"],
        speaker_affiliation=main_speaker["affiliation"],
        all_speakers=speakers,
        whisper_text=whisper_text,
    )

    # 現在のcorrectedテキストから「……」を除去して理想的な期待値を作成
    corrected = seg["text"]
    # 「課税最低限を……。\n\n以上、」を「課税最低限を引き上げます。\n\n以上、」に修正
    # （文脈から「を」の後は「引き上げます」が強く示唆される）
    expected_text = corrected.replace(
        "所得税の課税最低限を……。\n\n以上、",
        "所得税の課税最低限を引き上げます。\n\n以上、"
    )

    input_data = {
        "system_prompt": SYSTEM_PROMPT,
        "user_prompt": user_prompt,
        "metadata": {
            "session_id": metadata["session_id"],
            "segment_index": 4,
            "speaker": main_speaker["name"],
            "committee": metadata["committee"],
            "pattern": "PA音声反復（石井啓一議長×3）混入による「……」不正挿入",
            "has_known_bug": True,
            "bug_description": (
                "Whisperが本会議場のPA放送「石井啓一議長」（3回繰り返し）をメイン発言文中に混入させた。"
                "LLMは反復雑音を除去するが、その際に文が途切れた箇所に禁止されている「……」を挿入してしまう。"
                "期待値では文脈から「課税最低限を引き上げます。」と補完し、「……」を使用しない。"
            ),
            "noise_text": "石井啓一議長、石井啓一議長、石井啓一議長。",
            "current_bug_output": "所得税の課税最低限を……。",
            "expected_behavior": "雑音除去後、文脈から自然な文末補完を行い「……」を使用しない",
            "whisper_noise_segment": {
                "ws_index": 23,
                "time_range": "631.6-661.1s",
                "text": "石井啓一議長、石井啓一議長、石井啓一議長。",
            },
            "description": "本会議（片山さつき財務大臣の財政演説）。PA音声の繰り返しによる文中断絶でLLMが「……」を不正挿入するバグを確認するケース。",
            "whisper_char_count": len(whisper_text),
        },
    }

    expected_data = {
        "corrected_text": expected_text,
        "evaluation_criteria": {
            "must_not_contain": ["……"],
            "must_not_contain_reason": "SYSTEM_PROMPTで「……」の出力を明示的に禁止している",
            "must_not_contain_noise": ["石井啓一議長、石井啓一議長"],
            "must_not_contain_noise_reason": "PA音声の繰り返し「石井啓一議長×3」は雑音であり除去されるべき",
            "should_fix_typo": "「課税最低減」→「課税最低限」（誤字修正）",
        },
    }

    prefix = "transcript_correction_case07"
    _save_json(GOLDEN_DIR / f"{prefix}.input.json", input_data)
    _save_json(GOLDEN_DIR / f"{prefix}.expected.json", expected_data)


def generate_case08() -> None:
    """【バグ確認】党名「参政党」→「賛成党」誤認識の未修正 + フィラー除去（成功）

    根本原因:
    Whisperが「参政党」（さんせいとう）を「賛成党」（さんせいとう）と誤変換。
    両者は読みが同じだが、「賛成党」は存在しない政党名であり、
    SYSTEM_PROMPTの固有名詞リストに「参政党」が明記されているにもかかわらず
    修正されていない。

    発言者リストにも「吉川里奈（参政党）」と記載されているため、
    文脈から「賛成党」→「参政党」の修正は可能なはず。

    現状: Whisperの「賛成党」x4のうち3件が未修正のまま残っている
    期待値: すべての「賛成党」→「参政党」に修正する

    成功している点:
    - フィラー「あのー」の除去（正常に動作）

    評価観点:
    - 「賛成党」が出力に含まれていないこと（MUST）
    - 「あのー」が除去されていること（GOOD — 現状もできている）
    """
    transcript = _load_json(DATA_DIR / "03/02/56088_予算委員会" / "raw_transcript.json")
    metadata = _load_json(DATA_DIR / "03/02/56088_予算委員会" / "metadata.json")
    seg = transcript["segments"][9]
    speakers = metadata["speakers"]
    main_speaker = speakers[9] if len(speakers) > 9 else {"name": seg["speaker_name"], "affiliation": ""}

    whisper_text = _whisper_text(seg)
    user_prompt = _build_user_prompt(
        committee=metadata["committee"],
        speaker_name=main_speaker["name"],
        speaker_affiliation=main_speaker["affiliation"],
        all_speakers=speakers,
        whisper_text=whisper_text,
    )

    # 期待値: corrected から「賛成党」→「参政党」に全置換し、あのーを除去する
    # （現状のcorrectedには賛成党が3件残っている）
    corrected = seg["text"]
    expected_text = corrected.replace("賛成党", "参政党")
    # あのーはすでに除去済みなので追加の修正不要

    input_data = {
        "system_prompt": SYSTEM_PROMPT,
        "user_prompt": user_prompt,
        "metadata": {
            "session_id": metadata["session_id"],
            "segment_index": 9,
            "speaker": main_speaker["name"],
            "committee": metadata["committee"],
            "pattern": "党名誤認識「賛成党」→「参政党」未修正 + フィラー「あのー」除去",
            "has_known_bug": True,
            "bug_description": (
                "Whisperが「参政党」（さんせいとう）を「賛成党」と誤変換。"
                "SYSTEM_PROMPTの固有名詞リスト・発言者リストに「参政党」が明記されているが、"
                "現状のLLMは4件中1件しか修正できていない（残り3件の「賛成党」が未修正）。"
            ),
            "whisper_sanseitou_count": whisper_text.count("賛成党"),
            "whisper_sansei_correct_count": whisper_text.count("参政党"),
            "current_corrected_sanseitou_count": seg["text"].count("賛成党"),
            "filler_removed_correctly": "あのー" not in seg["text"] and "あのー" in whisper_text,
            "description": "予算委員会（吉川里奈議員、参政党）。「参政党」→「賛成党」誤認識の修正漏れとフィラー除去の組み合わせを検証するケース。",
            "whisper_char_count": len(whisper_text),
        },
    }

    expected_data = {
        "corrected_text": expected_text,
        "evaluation_criteria": {
            "must_not_contain": ["賛成党"],
            "must_not_contain_reason": "「賛成党」は存在しない政党名。発言者リスト・固有名詞リストの「参政党」に修正すべき",
            "must_remove_filler": ["あのー"],
            "must_remove_filler_reason": "フィラーとして除去すべき（現状の実装でも正しく除去できている）",
        },
    }

    prefix = "transcript_correction_case08"
    _save_json(GOLDEN_DIR / f"{prefix}.input.json", input_data)
    _save_json(GOLDEN_DIR / f"{prefix}.expected.json", expected_data)


def main() -> None:
    print("Generating transcript_correction benchmark cases...")
    print()

    print("[case01] 句読点補完・改行挿入")
    generate_case01()

    print("[case02] 固有名詞誤認識修正（議員名・法案名）")
    generate_case02()

    print("[case03] アルファベット大文字化・話者名前書き整形")
    generate_case03()

    print("[case04] 同音異義語修正（祈念・黙祷）")
    generate_case04()

    print("[case05] 同音異義語修正（一刻の猶予・当委員会）+ 委員長指名リスト整形")
    generate_case05()

    print("[case06] 【バグ】雑音（呼びかけ）混入による「……」不正挿入")
    generate_case06()

    print("[case07] 【バグ】PA音声反復混入による「……」不正挿入")
    generate_case07()

    print("[case08] 【バグ】「賛成党」→「参政党」誤認識未修正 + フィラー除去")
    generate_case08()

    print()
    print("Done! Generated 8 benchmark cases in eval/golden/")
    print()
    print("Summary of issue patterns found:")
    print("  ✗ Bug: 「……」不正挿入 — 828/5428セグメント (15.2%) で発生")
    print("    原因: 雑音テキスト除去後にLLMが禁止されている「……」を挿入")
    print("    該当ケース: case06, case07")
    print()
    print("  ✗ Bug: 「賛成党」→「参政党」未修正 — 360セグメントに影響")
    print("    原因: Whisperの同音誤変換をLLMが固有名詞リスト参照で修正できていない")
    print("    該当ケース: case08")
    print()
    print("  ✓ 成功: 句読点補完（全般的に機能）")
    print("  ✓ 成功: 改行挿入・委員長指名パターン（概ね機能）")
    print("  ✓ 成功: 一部の固有名詞修正（平将明・サイバー対処能力等）")
    print("  ✓ 成功: 一部の同音異義語修正（祈念・黙祷・前政権等）")
    print("  ✓ 成功: フィラー除去（あのー等）")


if __name__ == "__main__":
    main()
