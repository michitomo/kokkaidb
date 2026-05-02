# TOPICS_SYSTEM_PROMPT ベンチマーク

`SUMMARY_AND_TOPICS_SYSTEM_PROMPT`（`structurer.py`）のプロンプト改善イテレーション用ベンチマーク。

## 背景と課題

140セッション（2026年2〜4月）の実データ分析で判明した主要課題：

| # | 課題 | 影響範囲 | 深刻度 |
|---|------|---------|-------|
| 1 | **QA IDカバレッジ不足**：全QAペアを網羅する指示がない | 22/118セッション（18.6%）で80%未満 | ★★★ 最重要 |
| 2 | **トピック数の固定化**：QA数が増えてもトピックが5〜6個に収束 | 100〜200 QAでも平均9.9トピック | ★★ 重要 |
| 3 | **key_topics vs topics の不整合**：同一LLM呼び出しで乖離が頻発 | 30%のセッションで2件以上差 | ★ 軽微 |
| 4 | **score.py がカバレッジ未測定**：topic_count_diff・name_coverageのみ | ベンチマーク基盤の欠陥 | ★★ 重要 |

## 評価指標

| 指標 | 説明 | 目標値 |
|------|------|-------|
| `qa_coverage` | expected内の全QA IDのうちresultがカバーした割合 | **1.0** |
| `topic_count_diff` | result − expected のトピック数差 | 0に近いほど良い |
| `name_coverage` | expected トピック名がresultに部分一致する割合 | 高いほど良い |

## ベンチマークケース一覧

### 好事例（プロンプト改善後も維持が必要）

| Case ID | セッション | QA数 | 期待トピック数 | パターン |
|---------|-----------|------|-------------|--------|
| P1 | 56091_文部科学委員会 | 17 | 8 | 単一法案・小規模 |
| P2 | 56162_本会議（防災庁設置法） | 32 | 7 | 単一法案・中規模 |
| P3 | 56149_本会議（健康保険法） | 42 | 7 | 単一法案・中規模 |
| P4 | 56089_予算委員会 | 113 | 16 | 多テーマ・大規模 |

### 問題事例（現状プロンプトで低カバレッジ）

| Case ID | セッション | QA数 | 現状カバレッジ | 期待トピック数 | パターン |
|---------|-----------|------|-------------|-------------|--------|
| D1 | 56201_内閣委員会（国家情報法案） | 90 | **44.4%** | 11 | 単一法案・周辺テーマ多数 |
| D2 | 56145_内閣委員会（多テーマ） | 139 | **54.0%** | 17 | 多テーマ・最大規模 |
| D3 | 56196_厚生労働委員会（医療法案） | 117 | **59.0%** | 13 | 単一法案・延長テーマ多数 |

## ファイル構成

```
benchmarks/topics/
├── README.md           このファイル
├── cases.json          全ケースのインデックス（機械可読）
├── run_benchmark.py    ベンチマーク実行スクリプト
├── results/            実行結果（gitignore 推奨）
└── cases/
    ├── P1_文部科学委員会_単一法案_小規模/
    │   ├── meta.json       ケースのメタデータ（パターン・現状カバレッジ等）
    │   ├── input.json      LLM入力（user_prompt・qa_pair_ids）
    │   └── expected.json   理想出力（topics、100%カバレッジ）
    ├── P2_本会議_防災庁設置_中規模/
    ├── P3_本会議_健康保険法_中規模/
    ├── P4_予算委員会_多テーマ_大規模/
    ├── D1_内閣委員会_国家情報法案_低カバレッジ/
    ├── D2_内閣委員会_多テーマ_低カバレッジ/
    └── D3_厚生労働委員会_医療法案_低カバレッジ/
```

## 使い方

```bash
cd kokkai-transcriber

# 全ケースを現行プロンプトで実行
python -m eval.benchmarks.topics.run_benchmark --prompt-label baseline

# 特定ケースのみ
python -m eval.benchmarks.topics.run_benchmark --cases P1,P2,P3 --prompt-label baseline

# 改善プロンプトを試す
python -m eval.benchmarks.topics.run_benchmark \
  --prompt-file my_improved_prompt.txt \
  --prompt-label v2_coverage_hint

# 構造確認のみ（LLM呼び出しなし）
python -m eval.benchmarks.topics.run_benchmark --dry-run
```

## 入力フォーマット（input.json）

```json
{
  "system_prompt_key": "SUMMARY_AND_TOPICS_SYSTEM_PROMPT",
  "user_prompt": "以下の国会質疑のQ&Aペア一覧を分析してください...",
  "qa_pair_ids": ["qa_001", "qa_002", ...],
  "metadata": { "session": "...", "date": "...", "n_qa_pairs": 90 }
}
```

`user_prompt` は `structurer.py: generate_summary_and_topics()` と同一フォーマット。

## 期待出力フォーマット（expected.json）

```json
{
  "topics": [
    {
      "name": "トピック名",
      "description": "説明（1-2文）",
      "related_qa_ids": ["qa_001", "qa_002"],
      "related_speakers": ["発言者名1"]
    }
  ]
}
```

`expected.json` の `topics` は全 QA ID を 100% カバーする手動設計済みの理想分類。

## 理想 expected の設計方針

- **P1〜P4**: 既存 `data/` の `topics.json` を使用（3件の未カバーは手動で最適トピックに追加）
- **D1〜D3**: 現状プロンプトが切り捨てたQAを意味論的に近いグループに手動分類し、新トピックを追加

### D1の問題分析（国家情報法案・44.4%カバレッジ）

現状5トピック: 国家情報体制, 人権保護, 民主的統制, 人材確保, 宇宙防衛  
理想11トピック: 上記5 + 法的定義と権限, スパイ防止法制, AI透明性と有事対応, 防衛装備移転, 市民監視事案, 官房機密費

### D2の問題分析（多テーマ委員会・54.0%カバレッジ）

現状6トピック: 重要物資, 経済成長, 安全保障, 小型モビリティ, 再審制度, AIインフラ  
理想17トピック: 上記6 + 拉致問題啓発, カジノ/外国人土地取得, 食品安全, 女性政策, 公務員改革, 消費者保護, 賃金政策, スタートアップ, コンテンツ産業, 交通安全/燃料, 昭和100年

### D3の問題分析（医療法案・59.0%カバレッジ）

現状6トピック: OTC類似薬, 高額療養費, 出産費用, 医療DX, 後期高齢者医療, 医薬品安定供給  
理想13トピック: 上記6 + 診療報酬評価, 予防医療/薬局機能, リハビリ専門職, 協会けんぽ財政, 少子化/プレコン, 全世代型社会保障, 医療行政DX
