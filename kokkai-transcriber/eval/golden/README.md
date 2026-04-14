# ゴールデンデータ

## ファイル命名規則

- `{task}_{case_id}.input.json` — LLMへの入力（system_prompt + user_prompt）
- `{task}_{case_id}.expected.json` — 期待される出力（人手で作成・修正）

## タスク名

- `speaker_tagging` — 話者タグ付け
- `qa_pairs` — Q&Aペア生成
- `summary` — セッション要約
- `topics` — トピック抽出

## input.json の形式

```json
{
  "system_prompt": "システムプロンプト（各タスクの本番プロンプトと同一）",
  "user_prompt": "ユーザープロンプト（実データから生成）",
  "metadata": {
    "session_id": "56149",
    "segment_index": 3,
    "description": "このテストケースの説明"
  }
}
```

## ゴールデンデータ作成手順

1. Phase 1 PoCで `deli_id=56149` をパイプライン実行
2. 出力JSONを人手で確認・修正
3. 修正済みデータを expected.json として保存
4. パイプライン実行時のプロンプトを input.json として保存
