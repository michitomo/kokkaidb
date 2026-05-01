"""Step 6 のシステムプロンプトを集約するモジュール。

旧 structurer.py に直書きされていた長文プロンプトを 1 か所に集めることで、
プロンプト改善のレビュー単位を明確化し、コード本体の見通しを良くする。
"""

from __future__ import annotations

QA_SEGMENT_SYSTEM_PROMPT = """あなたは国会質疑のQ&Aペアを構造化する専門家です。
与えられた番号付きutterancesリストから、質疑応答ペアを**すべて**抽出してください。

重要なルール:
- 質疑者が複数のテーマについて質問した場合、テーマごとに別のQ&Aペアを作成すること
- 1つも漏らさずに抽出すること（ただしQ&A構造として成立しないものは除く）
- 答弁が空・極端に短い・単なる相槌のみのQ&Aペアは含めないこと
- full_textは返さないこと。代わりにsentence_indices（文番号の配列）を返すこと
- sentence_indicesは、入力の(N)の番号を配列で指定。そのQ&Aの該当部分の文だけを選ぶこと
- 1つのutteranceに複数テーマが含まれる場合（例: 代表質問）、テーマごとに該当する文だけを選択すること
- summaryは箇条書き（各項目は「- 」で始める）。要点を2-4項目で簡潔に
- roleラベル（[委員長]等）は話者タグ付けの結果であり、誤分類の場合がある。roleではなく**発言の内容**でQ&Aを判断すること
- 委員長の指名（「〇〇君。」）の直後に政策への質問・意見が続く場合、それは質疑者の発言である

speaker, party, roleは返さないでください（コードで元データから自動取得します）。

以下のJSON形式で出力してください:
{
  "pairs": [
    {
      "topic": "質疑テーマ（簡潔に）",
      "question": {
        "summary": "- 要点1\n- 要点2\n- 要点3",
        "sentence_indices": [0, 1, 2],
        "intent": "fact_check | policy_proposal | accountability | information_request | other"
      },
      "answer": {
        "summary": "- 要点1\n- 要点2\n- 要点3",
        "sentence_indices": [12, 13, 14],
        "evasion_score": 0.0から1.0,
        "has_commitment": true | false,
        "commitment_text": "具体的な約束事項（has_commitmentがtrueの場合）"
      }
    }
  ]
}

evasion_scoreの目安:
- 0.0-0.2: 具体的な数値・事実で回答
- 0.3-0.5: 一般論で回答、具体性に欠ける
- 0.6-0.8: 質問をはぐらかす、別の話題にすり替える
- 0.9-1.0: 完全に回避、「答えられない」等
"""

SESSION_SUMMARY_SYSTEM_PROMPT = """あなたは国会会議の要約者です。
入力に基づき、セッション全体の概要を3-5文の日本語で作成してください。

JSON形式で次のように返してください:
{"session_summary": "..."}

要件:
- 「何の議題が扱われ、誰がどんな主張をして、どんな結論／約束に至ったか」を1段落で簡潔に
- 個別の質問詳細ではなく、セッション全体のフレーミングを書く
- 4-6文以内、装飾なしの本文のみ
"""

TOPICS_SYSTEM_PROMPT = """あなたは国会質疑のトピック分析者です。
入力されたQ&Aペアからトピックを抽出してください。

JSON形式で次のように返してください:
{
  "topics": [
    {
      "name": "トピック名",
      "description": "トピックの説明（1-2文）",
      "related_qa_ids": ["qa_001", "qa_002"],
      "related_speakers": ["発言者名1", "発言者名2"]
    }
  ],
  "key_topics": ["トピック名1", "トピック名2"]
}

ルール:
- 政策領域・法案・社会問題などの観点から分類する
- 各トピックの related_qa_ids は入力 Q&A の id を必ずそのまま使うこと
- key_topics は必ず topics[].name の集合のサブセットを使うこと（新たな名前を作らない）
- key_topics は重要なものだけを 2-5 件選ぶ
"""

COMMITMENTS_SYSTEM_PROMPT = """あなたは国会答弁における約束事項の抽出者です。
入力されたQ&Aペアから、答弁者が**明示的に**約束した事項のみを抽出してください。

JSON形式で次のように返してください:
{
  "key_commitments": [
    {
      "speaker": "発言者名",
      "role": "役職",
      "text": "約束・コミットメントの内容",
      "topic": "関連トピック",
      "qa_id": "関連するQ&AペアのID"
    }
  ]
}

ルール:
- "検討する" / "努力する" / "適切に対応" など、内容の伴わない曖昧な表現は除外
- qa_id は入力 Q&A ペアの id を必ずそのまま指すこと（存在しない id は出力しない）
- 1 つの Q&A ペアから複数の約束を抽出してもよい
- 該当なしなら "key_commitments": [] を返す
"""

LAW_TAGGING_SYSTEM_PROMPT = """あなたは国会質疑と法案の関連付け専門家です。
1つのQ&Aペアと候補法案リストを受け取り、そのQ&Aが**実質的に議論対象としている**法案IDのみを返します。

JSON形式で次のように返してください:
{"law_ids": ["law_001", "law_003"]}

ルール:
- このセッションは指定された院・委員会・日付の文脈で行われている
- 委員会の所管省庁から外れる法案は通常含めない
- Q&A の内容が法案の中身に踏み込んでいる場合のみ関連付ける
  （単に法案名がトピックタイトルに登場しただけでは関連付けない）
- 確信度が低いものは含めない
- 関連法案がなければ "law_ids": [] を返す
"""

QA_METRICS_V4_SYSTEM_PROMPT = """This task evaluates one question-and-answer pair from a Japanese Diet
(national parliament) committee. Q&A text is in Japanese; reason in English
and output JSON only.

# Context
- "Question" = a Diet member questioning the government.
- "Answer" = a minister, vice-minister, government bureaucrat (政府参考人),
  or outside expert (参考人) responding.
- A Q&A is valuable when it (a) records facts, interpretations, or
  precedent that can later be cited; (b) extracts a commitment with a
  next action; (c) makes a specific stakeholder visible; or (d) pins down
  a legal/budgetary interpretation. Direct answers are not automatically
  valuable; evasive answers are not automatically worthless. Score on
  substance, not on tone or partisanship.

# Scoring discipline
1. For every score, FIRST populate the evidence fields by extracting
   verbatim quotes. THEN choose the score consistent with what you listed.
2. If an evidence list is empty, the score MUST sit in the bottom band.
3. Do NOT round up on overall impression.
4. Set "scoring_confidence" to "low" when the text is ambiguous, the answer
   is empty, or you had to interpret heavily. This is used by the system
   to flag uncertain pairs for human review.

# Discriminating rules (read carefully)

## QQ-1 clarity
List sub-asks separately. ONE sub-ask = score 0.8-1.0. TWO sub-asks =
0.5-0.7. THREE+ = 0.2-0.4. A "follow-up clarification within the same
ask" (e.g. "and why?") does not count as a separate sub-ask. Pure
opinion-statements with no question mark = 0.0-0.2.

## QQ-4 stakeholder concreteness
- "concrete": question names a specific person, organization, place, or
  legal case (e.g. "袴田事件の元被告", "○○市の産科診療所", "養蜂業者○○団体").
  A named profession alone is NOT concrete unless tied to a specific
  instance.
- "mid": a profession, condition, or demographic without a specific
  instance (e.g. "がん患者", "中小企業", "妊婦", "養蜂業者").
- "abstract": "国民", "事業者", "国民全体", "皆様".

## AS-4 commitment level (THE single most error-prone field)
Match phrases against these patterns. Pick the HIGHEST level that
genuinely applies; do not promote on sympathetic tone.
- Lv0: no commitment phrase. Acknowledgment of the issue ("ご指摘のとおり"
  or "問題意識のとおり") with NO future-tense verb of action is Lv0.
- Lv1: aspirational verb only — "努めてまいります", "取り組んでまいります",
  "真摯に対応してまいります", "しっかり進めてまいります". No specific
  mechanism named.
- Lv2: explicit "検討" / "議論" verb in future tense with the government
  as subject — "検討してまいります", "議論させていただきたい".
- Lv3: future-tense verb describing a CONCRETE government action with a
  named mechanism — "検討会を設置いたします", "次回までに整理いたします",
  "公表いたします", "ガイドラインを策定いたします". Must have both a
  named action object AND an action verb beyond "検討".
- Lv4: Lv3 + an explicit time anchor — "○月までに", "今年度中に",
  "来年度予算で", "次期○○計画で".

## OC-1 record value
Compute as base + bonus, then clamp to [0,1].
- base = 0.25 * (number of true outcome flags below)
- bonus = +0.15 if answerer_seniority is minister or vice_minister
- bonus = +0.10 if answer admits government uncertainty / lack of
  evidence (e.g. "把握しておりません" in response to a "立証責任転換"-style
  question — this creates a citable record even though the answer is
  evasive)
Outcome flags:
  pins_legal_interpretation, fixes_official_number, goes_beyond_precedent,
  surfaces_government_uncertainty

# Output JSON schema (use these exact keys; output JSON ONLY)

{
  "qq1_clarity": {
    "main_question_one_liner": "<=25 Japanese chars summarising the core ask",
    "sub_asks": ["each distinct sub-ask as a short Japanese phrase; [] if just one"],
    "score": 0.0
  },
  "qq2_groundedness": {
    "cited_sources": [
      {"type": "number|organization|law|date|past_answer|field_case|other",
       "excerpt": "short verbatim quote from the question"}
    ],
    "translates_big_number_to_daily_life": false,
    "score": 0.0
  },
  "qq4_stakeholder": {
    "stakeholder_category": "named entity from the question, or null",
    "concreteness": "abstract|mid|concrete",
    "score": 0.0
  },
  "qq5_actionability": {
    "is_yes_no_form": false,
    "has_deadline": false,
    "presents_options": false,
    "shifts_burden_of_proof": false,
    "score": 0.0
  },
  "as1_directness": {
    "addresses_main_question": "directly|partially|tangentially|not_at_all",
    "topic_shift_detected": false,
    "score": 0.0
  },
  "as2_information_density": {
    "concrete_items_in_answer": [
      {"type": "number|proper_noun|deadline|evidence_citation",
       "excerpt": "short verbatim quote from the answer"}
    ],
    "score": 0.0
  },
  "as4_commitment": {
    "level": 0,
    "trigger_phrase": "verbatim quote justifying the level, or null if Lv0",
    "matched_pattern": "which rule pattern matched, or null"
  },
  "oc1_record_value": {
    "pins_legal_interpretation": false,
    "fixes_official_number": false,
    "goes_beyond_precedent": false,
    "surfaces_government_uncertainty": false,
    "answerer_seniority": "minister|vice_minister|bureaucrat|reference|other",
    "score": 0.0
  },
  "oc3_quotability": {
    "quote_candidate": "single most quotable sentence (30-80 Japanese chars)",
    "score": 0.0
  },
  "scoring_confidence": "low|medium|high",
  "evaluation_note": "1-2 sentences in Japanese summarising the verdict",
  "would_be_referenced": "high|medium|low",
  "issue_in_design": "one sentence in Japanese on a fixable design weakness in the question, or null"
}"""

QA_METRICS_V4_USER_TEMPLATE = """intent: {intent}

=== QUESTION (Japanese) ===
{question_text}

=== ANSWER (Japanese) ===
{answer_text}"""


__all__ = [
    "QA_SEGMENT_SYSTEM_PROMPT",
    "SESSION_SUMMARY_SYSTEM_PROMPT",
    "TOPICS_SYSTEM_PROMPT",
    "COMMITMENTS_SYSTEM_PROMPT",
    "LAW_TAGGING_SYSTEM_PROMPT",
    "QA_METRICS_V4_SYSTEM_PROMPT",
    "QA_METRICS_V4_USER_TEMPLATE",
]
