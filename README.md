# 国会議事録リアルタイムDB

衆議院TV・参議院TVのアーカイブ動画から音声を自動抽出し、Whisper文字起こし + LLM構造化を行い、GitHub Pages上の静的サイトとして公開するシステム。

公式会議録の公開タイムラグ（数週間〜数ヶ月）を解消し、質疑内容を当日中にデータベース化する。

**[→ サイトを見る](https://michitomo.github.io/kokkaidb)**

---

## 主な機能

- **両院横断閲覧**: 衆議院・参議院の質疑をQ&A対比カードで表示
- **全文検索**: Pagefind による CJK 対応クライアントサイド検索
- **多軸フィルタ**: 院・日付・委員会・政党・発言者・トピックで絞り込み
- **動画リンク**: 各発言から衆議院TV・参議院TVの該当タイムスタンプへ直リンク
- **ダッシュボード**: トピックヒートマップ、答弁回避度トラッカー、約束トラッカー等
- **TSVエクスポート**: フィルタ済みQ&AペアをGoogle Sheetsにインポート可能
- **BYOK分析**: OpenRouter APIキーを入力するとオンデマンドLLM分析をアンロック

---

## アーキテクチャ概要

```
GitHub Actions (毎時 cron)
  └─ ShugiinScraper / SangiinScraper
        └─ ffmpeg (HLS → WAV)
              └─ Whisper large-v3-turbo (DeepInfra)
                    └─ DeepSeek V3.2 (話者タグ・Q&A構造化・要約)
                          └─ data/ に JSON を git push
                                └─ GitHub Actions (Astro build + Pagefind)
                                      └─ GitHub Pages (静的サイト)
```

詳細な設計は [ARCH.md](ARCH.md) を参照。

---

## セットアップ

### パイプライン（データ収集）

```bash
cd kokkai-transcriber

python -m venv .venv
source .venv/bin/activate
pip install -e .
# ffmpeg が必要: brew install ffmpeg (macOS) / apt install ffmpeg (Linux)

# .env に DEEPINFRA_API_KEY を設定
cp .env.example .env

# 単体実行（--no-push でローカルのみ）
python -m src.pipeline --chamber shugiin --session-id 56149 --no-push
python -m src.pipeline --chamber sangiin --session-id 1234 --no-push
```

### サイト（フロントエンド）

```bash
cd site
npm ci
npm run dev   # http://localhost:4321
```

---

## 出所・著作権

音声・発言データは [衆議院インターネット審議中継](https://www.shugiintv.go.jp/) および [参議院インターネット審議中継](https://www.webtv.sangiin.go.jp/) から取得。

著作権法第40条1項（公開された政治上の演説・陳述の自由利用）に基づき利用。全ページに出所リンクを表示（著作権法第48条対応）。
