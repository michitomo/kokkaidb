# 08. モバイル／アクセシビリティ／i18n

[← 戻る](README.md)

スクリーンショット:
- `screenshots/22-browse-mobile-aboveFold.png`（モバイル `/browse`）
- `screenshots/30-home-mobile-aboveFold.png`（モバイル ホーム）
- `screenshots/12-session-detail-mobile.png`

---

## 8.1【P0】モバイルでフィルタが折りたたまれない

### 現状
`FilterPanel.jsx`:
```css
@media (max-width: 767px) {
  .filter-toggle-btn { display: block; }
  .filter-controls { display: none; }
  .filter-controls.open { display: block; }
}
```
- 「🔍 フィルタ ▼」ボタンは表示されている
- しかし、フィルタ本体も**同時に**展開されたまま

### 推測される原因
- 観察時の挙動を見ると、ボタンが出ているのにコントロール部もずっと表示されている
- React 島が `client:load` で読み込まれる前後の SSR/hydration ズレが疑わしい
- もしくは CSS specificity の問題で `.filter-controls` 直下の `display: flex` が `display: none` を上書きしている

### 改善案
1. ロード直後の hydration を待たずに、SSR 時から「mobile == false（デスクトップ前提）」で出力 → CSS で切替
2. CSS を確実に効かせるため、外側 div に `data-filter-open={open}` を付け、属性セレクタで切替:
   ```css
   @media (max-width: 767px) {
     [data-filter-open="false"] .filter-controls { display: none; }
   }
   ```
3. デフォルトの開閉状態をデバイス幅で初期化（`useEffect` 初回で `window.matchMedia('(max-width: 767px)')`）

---

## 8.2【P1】モバイルで縦に長すぎる

### 現状
- ホーム: 140 セッションが日付グルーピングで縦並び → スマホで延々スクロール
- セッション詳細: タイムライン → 発言者 → 53 Q&A → 発言全文 → 1 ページ A4 で 10 ページ超

### 改善案
1. ホーム: 「最新 7 日」をデフォルト、過去はページネーション
2. セッション詳細: スティッキーな「目次タブ」を上部に置き、4 セクションをタブ切り替え（概要 / Q&A / 発言全文 / タイムライン）
3. 「上に戻る」ボタン（フローティング）

---

## 8.3【P1】タイムラインのモバイル対応

### 現状
- SVG が 600px 以上の幅前提（`Math.max(svgWidth, 600)`）
- モバイルだと横スクロール強制

### 改善案
- モバイルでは「縦タイムライン」モードに切替（時間軸を縦、棒を発言ごと）
- もしくは「コンパクトモード」: 各発言者の合計発言時間バーを 1 行ずつ並べる

---

## 8.4【P1】タップターゲットサイズ

### 現状
- 「政党/会派」MultiSelect の trigger: 高さ約 32px（`padding: 0.4rem 0.75rem`）
- iOS HIG 推奨は 44×44px、Material は 48×48px

### 改善案
- mobile breakpoint で MultiSelect / radio / checkbox の min-height を 44px に
- ラジオ / チェックボックス自体は小さくて良いが、`label` のクリック領域を広げる

---

## 8.5【P0】アクセシビリティ: SVG ヒートマップ・タイムラインに ARIA がない

### 現状
- `TopicHeatmap` 各セルは `<div>` + `title` 属性（読み上げは title が拾われるが、構造化されていない）
- `TimelineView` は SVG。`<text>` も含むがテキストとして読み上げ困難
- スクリーンリーダーでヒートマップ → 委員会 → トピック → 件数の関連付けができない

### 改善案
1. ヒートマップを `<table>` に変更:
   ```html
   <table role="grid">
     <thead><tr><th></th><th>本会議</th><th>予算委員会</th>...</tr></thead>
     <tbody>
       <tr><th scope="row">防災庁の組織機能と権限</th><td>0</td><td>2</td>...</tr>
     </tbody>
   </table>
   ```
   セルの色は `<td>` 背景。a11y ツリーが正しく構造化される。
2. タイムライン SVG にテキストの代替を表示（visually-hidden な `<details>` で「09:00 関芳弘（委員長）1 分」のリスト）

---

## 8.6【P1】配色のコントラスト・色覚

### 現状
- 回避度: 緑 #16a34a / 橙 #d97706 / 赤 #dc2626 — 3 色とも彩度が高く色覚バリアのリスク（特に赤緑）
- 政党色は NHK 準拠なので自民緑・立憲青…色弱の方には判別しづらい組合せが残る
- グレーテキスト #9ca3af on #fafafa はコントラスト比約 2.85:1（WCAG AA NG）

### 改善案
- 回避度: パターン（縞・斜線）or アイコン（✓ / ⚠ / ✕）を併用
- グレーテキスト #6b7280 まで濃くする（4.7:1 → AA）
- 政党色は形（●▲◆）と組み合わせる

---

## 8.7【P1】キーボード操作

### 現状
- グローバルナビ・ボタンは `<a>` `<button>` で OK
- `.topic-tag` は `<button>` で OK
- ヒートマップセルは `<div onClick>` ⇒ Tab 移動できない、Enter で発火しない
- タイムライン SVG の `<rect onClick>` も同様

### 改善案
- ヒートマップセル: `<td role="button" tabIndex="0" onKeyDown={enterToClick}>`
- タイムラインバー: SVG の代わりに HTML / CSS で実装し、`<button>` ベースに

---

## 8.8【P1】スキップリンク

- `Tab` キー初回押下時のスキップリンク（"メインコンテンツへ" "ナビゲーションをスキップ"）が無い
- 視覚障害者・キーボード利用者は毎ページでナビ 4 リンクを通過

### 改善案
- BaseLayout に `<a href="#main" class="skip-link">メインコンテンツへ</a>` を追加（focus 時のみ可視）

---

## 8.9【P2】言語属性とフォント

- `<html lang="ja">` あり ✓
- フォントは `-apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans JP', sans-serif`
- iOS で意図せず明朝になるケースは少ないが、Windows 上で MS ゴシック fallback 経路が古臭い

### 改善案
- 「Hiragino Kaku Gothic ProN」「Meiryo」「Yu Gothic UI」を間に入れる
- 数字は `font-variant-numeric: tabular-nums` で揃える（dashboard の数値カードに有効）

---

## 8.10【P1】英語対応の最低限

P5（海外記者ペルソナ）の救済として、以下を**完全 i18n しなくても**実装可能:

1. `<html>` の `lang` を選べる UI（jp/en）
2. ナビ・委員会名・主要要約を英訳キャッシュ（LLM で前処理）
3. URL は `/en/browse` のような prefix でも良いが、subdomain `en.kokkaidb.example` の方が静的サイト向き
4. 全件英訳は工数とコストが大きいので、**「サマリ・委員会名・議員名のみ英訳」**で開始するのが現実的

---

## 8.11【P2】PWA / オフライン

- 通勤電車内で読みたいユーザー（P1, P2）に対応
- Astro PWA プラグインで Service Worker を入れて、過去 N 日のセッション JSON をキャッシュ

---

## 8.12【P2】読み上げ最適化

`utt-text` の段落単位読み上げを意識して、`<p>` の `aria-label` で「質問者・○○議員の発言」のようなプリフィックスを付けると音声で議事の流れが追いやすい。

---

[← 戻る](README.md) ｜ [次の章: 09-trust-transparency.md →](09-trust-transparency.md)
