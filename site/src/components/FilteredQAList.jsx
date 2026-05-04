import { useState, useCallback } from 'react';
import { indexEntriesToTsv } from '../lib/tsv-export';

const PAGE_SIZE = 300;

/**
 * フィルタ済みQ&Aペアのリスト表示コンポーネント。
 * TSVコピーボタン、動画リンク、出典リンク、ページネーションを含む。
 *
 * @param {object} props
 * @param {import('../../scripts/generate-api').IndexEntry[]} props.filteredEntries
 *   フィルタ済みのセッションエントリ（各エントリに qa_pairs が含まれる）
 * @param {number} props.totalCount 全件数（フィルタ前）
 * @param {number} props.page 現在のページ（1始まり）
 * @param {(page: number) => void} props.onPageChange
 */
export default function FilteredQAList({ filteredEntries, totalCount, page, onPageChange, baseUrl = '' }) {
  const [copyState, setCopyState] = useState('idle');
  const [expandedIds, setExpandedIds] = useState(new Set());
  const [metricsModalQa, setMetricsModalQa] = useState(null);

  // 全フィルタ済みQ&Aペアをフラットに展開（セッション情報付き）
  const allPairs = filteredEntries.flatMap((entry) =>
    entry.qa_pairs.map((qa) => ({ qa, entry }))
  );

  const totalFiltered = allPairs.length;
  const totalPages = Math.max(1, Math.ceil(totalFiltered / PAGE_SIZE));
  const safePage = Math.min(Math.max(1, page), totalPages);
  const start = (safePage - 1) * PAGE_SIZE;
  const pagePairs = allPairs.slice(start, start + PAGE_SIZE);

  // TSVコピー処理
  const handleCopyTsv = useCallback(async () => {
    const tsv = indexEntriesToTsv(filteredEntries);
    try {
      await navigator.clipboard.writeText(tsv);
      setCopyState('success');
      setTimeout(() => setCopyState('idle'), 2000);
    } catch {
      // Clipboard API 失敗時のフォールバック
      setCopyState('error');
    }
  }, [filteredEntries]);

  function scoreColor(score) {
    if (score >= 0.7) return '#16a34a';
    if (score >= 0.4) return '#d97706';
    return '#dc2626';
  }

  function scorePercent(score) {
    return `${(score * 100).toFixed(0)}%`;
  }

  function toggleExpand(qaId) {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(qaId)) next.delete(qaId);
      else next.add(qaId);
      return next;
    });
  }

  function renderSummary(text) {
    const lines = text.split('\n').filter(l => l.trim());
    const isList = lines.length > 1 && lines.every(l => l.trim().startsWith('- '));
    if (isList) {
      return (
        <ul className="summary-list">
          {lines.map((l, i) => <li key={i}>{l.trim().replace(/^- /, '')}</li>)}
        </ul>
      );
    }
    return <p className="summary">{text}</p>;
  }

  function chamberLabel(chamber) {
    return chamber === 'shugiin' ? '衆議院TV' : '参議院TV';
  }

  function sessionDetailUrl(entry) {
    const [year, month, day] = entry.date.split('-');
    const slug = `${entry.session_id}_${entry.committee}`;
    const base = baseUrl.replace(/\/$/, '');
    return `${base}/${entry.chamber}/${year}/${month}/${day}/${encodeURIComponent(slug)}`;
  }

  function formatVideoTime(videoUrl) {
    // 衆議院: &time=123 → "2:03〜"
    // 参議院: #123 → "2:03〜"
    let seconds = null;
    const shugiinMatch = videoUrl.match(/[?&]time=(\d+)/);
    if (shugiinMatch) seconds = parseInt(shugiinMatch[1], 10);
    const sangiinMatch = videoUrl.match(/#(\d+)$/);
    if (sangiinMatch) seconds = parseInt(sangiinMatch[1], 10);
    if (seconds === null) return null;
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${m}:${String(s).padStart(2, '0')}〜`;
  }

  const copyLabel =
    copyState === 'success'
      ? 'コピーしました ✓'
      : copyState === 'error'
        ? 'コピー失敗'
        : `TSVをコピー（${totalFiltered}件）`;

  return (
    <div className="filtered-qa-list">
      {/* ツールバー */}
      <div className="qa-toolbar">
        <span className="qa-count">
          <strong>{totalFiltered}</strong>件 / 全{totalCount}件
        </span>
        <div className="qa-actions">
          <button
            type="button"
            className={`btn-copy ${copyState}`}
            onClick={handleCopyTsv}
            disabled={totalFiltered === 0}
          >
            {copyLabel}
          </button>
        </div>
      </div>

      {/* コピー失敗フォールバック */}
      {copyState === 'error' && (
        <div className="copy-fallback">
          <p>クリップボードへのアクセスが拒否されました。以下のテキストを手動でコピーしてください:</p>
          <textarea
            readOnly
            rows={5}
            value={indexEntriesToTsv(filteredEntries)}
          />
        </div>
      )}

      {/* Q&Aカードリスト */}
      {totalFiltered === 0 ? (
        <div className="empty-state">
          <p>該当するQ&Aペアが見つかりません。フィルタを変更してください。</p>
        </div>
      ) : (
        <>
          <div className="qa-cards">
            {pagePairs.map(({ qa, entry }) => {
              const videoTime = formatVideoTime(qa.video_url);
              const hasFullText = qa.question_full_text || qa.answer_full_text;
              const fullTextExpanded = expandedIds.has(`${qa.id}-full`);
              return (
                <div key={qa.id} className="qa-card">
                  {/* ヘッダー */}
                  <div className="qa-header">
                    <div className="qa-meta">
                      <span className={`chamber-badge ${entry.chamber}`}>
                        {entry.chamber === 'shugiin' ? '衆' : '参'}
                      </span>
                      <a href={sessionDetailUrl(entry)} className="session-link">
                        <span className="qa-date">{entry.date}</span>
                        <span className="qa-committee">{entry.committee}</span>
                      </a>
                    </div>
                    <div className="qa-header-right">
                      <span className="qa-topic">{qa.topic}</span>
                      {qa.video_url && (
                        <a
                          href={qa.video_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="video-link"
                          title={videoTime ? `動画を見る（${videoTime}）` : '動画を見る'}
                        >
                          ▶ 動画{videoTime ? `（${videoTime}）` : ''}
                        </a>
                      )}
                    </div>
                  </div>

                  {/* 質問行 */}
                  <div className="qa-row">
                    <div className="qa-label qa-label--question">
                      <span className="qa-label-text">質問</span>
                      {qa.metrics?.qq2_groundedness?.score != null && (
                        <button className="score-chip" onClick={() => setMetricsModalQa(qa)} title="評価詳細">
                          <span className="score-chip-key">QQ</span>
                          <span className="score-chip-val" style={{ color: scoreColor(qa.metrics.qq2_groundedness.score) }}>{scorePercent(qa.metrics.qq2_groundedness.score)}</span>
                        </button>
                      )}
                    </div>
                    <div className="qa-content">
                      <div className="speaker-line">
                        <strong>{qa.question_speaker}</strong>
                        {qa.question_party && <span className="party">（{qa.question_party}）</span>}
                      </div>
                      {renderSummary(qa.question_summary)}
                    </div>
                  </div>

                  {/* 答弁行 */}
                  <div className="qa-row">
                    <div className="qa-label qa-label--answer">
                      <span className="qa-label-text">答弁</span>
                      {qa.metrics?.as1_directness?.score != null && (
                        <button className="score-chip" onClick={() => setMetricsModalQa(qa)} title="評価詳細">
                          <span className="score-chip-row">
                            <span className="score-chip-key">直答</span>
                            <span className="score-chip-val" style={{ color: scoreColor(qa.metrics.as1_directness.score) }}>{scorePercent(qa.metrics.as1_directness.score)}</span>
                          </span>
                          {qa.metrics?.as2_information_density?.score != null && (
                            <span className="score-chip-row">
                              <span className="score-chip-key">情報</span>
                              <span className="score-chip-val" style={{ color: scoreColor(qa.metrics.as2_information_density.score) }}>{scorePercent(qa.metrics.as2_information_density.score)}</span>
                            </span>
                          )}
                        </button>
                      )}
                    </div>
                    <div className="qa-content">
                      <div className="speaker-line">
                        <strong>{qa.answer_speaker}</strong>
                        {qa.answer_role && <span className="role">（{qa.answer_role}）</span>}
                      </div>
                      {renderSummary(qa.answer_summary)}
                    </div>
                  </div>


                  {/* 全文表示（統合） */}
                  {hasFullText && (
                    <div className="qa-row qa-row--fulltext">
                      <div className="qa-label qa-label--fulltext">全文</div>
                      <div className="qa-content">
                        <button
                          type="button"
                          className="expand-toggle"
                          onClick={() => toggleExpand(`${qa.id}-full`)}
                        >
                          {fullTextExpanded ? '全文を閉じる' : '質問・答弁の全文を表示'}
                        </button>
                        {fullTextExpanded && (
                          <div className="full-text-combined">
                            {qa.question_full_text && (
                              <div className="full-text-section">
                                <div className="full-text-section-label full-text-section-label--q">
                                  質問原文 — {qa.question_speaker}
                                  {qa.question_party && <span className="fts-party">（{qa.question_party}）</span>}
                                </div>
                                <div className="full-text">
                                  {qa.question_full_text.split(/(?<=。)/).filter(s => s.trim()).map((para, i) => (
                                    <p key={i}>{para}</p>
                                  ))}
                                </div>
                              </div>
                            )}
                            {qa.answer_full_text && (
                              <div className="full-text-section">
                                <div className="full-text-section-label full-text-section-label--a">
                                  答弁原文 — {qa.answer_speaker}
                                  {qa.answer_role && <span className="fts-party">（{qa.answer_role}）</span>}
                                </div>
                                <div className="full-text">
                                  {qa.answer_full_text.split(/(?<=。)/).filter(s => s.trim()).map((para, i) => (
                                    <p key={i}>{para}</p>
                                  ))}
                                </div>
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    </div>
                  )}

                  {/* 出典 */}
                  <div className="qa-footer">
                    出典:{' '}
                    <a
                      href={entry.source_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="source-link"
                    >
                      {chamberLabel(entry.chamber)}インターネット審議中継
                    </a>
                  </div>
                </div>
              );
            })}
          </div>

          {/* ページネーション */}
          {totalPages > 1 && (
            <nav className="pagination" aria-label="ページネーション">
              <button
                type="button"
                className="page-btn"
                disabled={safePage <= 1}
                onClick={() => onPageChange(safePage - 1)}
              >
                ‹
              </button>
              {buildPageNumbers(safePage, totalPages).map((p, i) =>
                p === '...' ? (
                  <span key={`ellipsis-${i}`} className="page-ellipsis">…</span>
                ) : (
                  <button
                    key={p}
                    type="button"
                    className={`page-btn ${p === safePage ? 'active' : ''}`}
                    onClick={() => onPageChange(p)}
                  >
                    {p}
                  </button>
                )
              )}
              <button
                type="button"
                className="page-btn"
                disabled={safePage >= totalPages}
                onClick={() => onPageChange(safePage + 1)}
              >
                ›
              </button>
            </nav>
          )}
        </>
      )}

      {/* 評価詳細モーダル */}
      {metricsModalQa && (
        <div className="modal-overlay" onClick={() => setMetricsModalQa(null)}>
          <div className="modal-box" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h3 className="modal-title">{metricsModalQa.topic}</h3>
              <button className="modal-close" onClick={() => setMetricsModalQa(null)}>✕</button>
            </div>
            <div className="modal-body">
              <div className="metrics-grid">
                <div className="metric-item"><span className="metric-icon">🎯</span><span className="metric-label-text">直接回答度</span><div className="metric-bar-wrap"><div className="metric-bar" style={{ width: scorePercent(metricsModalQa.metrics.as1_directness.score), background: scoreColor(metricsModalQa.metrics.as1_directness.score) }} /></div><span className="metric-value" style={{ color: scoreColor(metricsModalQa.metrics.as1_directness.score) }}>{scorePercent(metricsModalQa.metrics.as1_directness.score)}</span></div>
                {metricsModalQa.metrics.as2_information_density && <div className="metric-item"><span className="metric-icon">📊</span><span className="metric-label-text">具体情報量</span><div className="metric-bar-wrap"><div className="metric-bar" style={{ width: scorePercent(metricsModalQa.metrics.as2_information_density.score), background: scoreColor(metricsModalQa.metrics.as2_information_density.score) }} /></div><span className="metric-value" style={{ color: scoreColor(metricsModalQa.metrics.as2_information_density.score) }}>{scorePercent(metricsModalQa.metrics.as2_information_density.score)}</span></div>}
                {metricsModalQa.metrics.qq1_clarity && <div className="metric-item"><span className="metric-icon">💡</span><span className="metric-label-text">論点明確度</span><div className="metric-bar-wrap"><div className="metric-bar" style={{ width: scorePercent(metricsModalQa.metrics.qq1_clarity.score), background: scoreColor(metricsModalQa.metrics.qq1_clarity.score) }} /></div><span className="metric-value" style={{ color: scoreColor(metricsModalQa.metrics.qq1_clarity.score) }}>{scorePercent(metricsModalQa.metrics.qq1_clarity.score)}</span></div>}
                {metricsModalQa.metrics.qq5_actionability && <div className="metric-item"><span className="metric-icon">⚡</span><span className="metric-label-text">行動要求度</span><div className="metric-bar-wrap"><div className="metric-bar" style={{ width: scorePercent(metricsModalQa.metrics.qq5_actionability.score), background: scoreColor(metricsModalQa.metrics.qq5_actionability.score) }} /></div><span className="metric-value" style={{ color: scoreColor(metricsModalQa.metrics.qq5_actionability.score) }}>{scorePercent(metricsModalQa.metrics.qq5_actionability.score)}</span></div>}
              </div>
              {metricsModalQa.metrics.as4_commitment?.level >= 1 && (
                <div className="commitment-inline">
                  <span className={`commitment-lv commitment-lv-${metricsModalQa.metrics.as4_commitment.level}`}>🤝 lv{metricsModalQa.metrics.as4_commitment.level}</span>
                  {metricsModalQa.metrics.as4_commitment.trigger_phrase && <span className="commitment-phrase">「{metricsModalQa.metrics.as4_commitment.trigger_phrase}」</span>}
                </div>
              )}
              {metricsModalQa.metrics.oc3_quotability?.quote_candidate && (
                <div className="quote-candidate"><span className="quote-label">💬 引用候補:</span> {metricsModalQa.metrics.oc3_quotability.quote_candidate}</div>
              )}
              <div className="metrics-detail-grid">
                <div className="detail-section">
                  <h4 className="detail-heading">質問の質 (QQ)</h4>
                  {metricsModalQa.metrics.qq2_groundedness && (<div className="detail-row"><div className="detail-meta"><span className="detail-name">一次ソース密度</span><div className="metric-bar-wrap metric-bar-wrap--sm"><div className="metric-bar" style={{ width: scorePercent(metricsModalQa.metrics.qq2_groundedness.score), background: scoreColor(metricsModalQa.metrics.qq2_groundedness.score) }} /></div></div>{metricsModalQa.metrics.qq2_groundedness.cited_sources?.length > 0 && <ul className="detail-list">{metricsModalQa.metrics.qq2_groundedness.cited_sources.map((s, i) => <li key={i}><span className="source-tag">{s.type}</span> {s.excerpt}</li>)}</ul>}</div>)}
                  {metricsModalQa.metrics.qq4_stakeholder && (<div className="detail-row"><div className="detail-meta"><span className="detail-name">当事者・具体性</span><div className="metric-bar-wrap metric-bar-wrap--sm"><div className="metric-bar" style={{ width: scorePercent(metricsModalQa.metrics.qq4_stakeholder.score), background: scoreColor(metricsModalQa.metrics.qq4_stakeholder.score) }} /></div></div><div className="detail-text-info">対象者: <strong>{metricsModalQa.metrics.qq4_stakeholder.stakeholder_category || '未特定'}</strong> / 具体性: {metricsModalQa.metrics.qq4_stakeholder.concreteness === 'concrete' ? '具体的' : metricsModalQa.metrics.qq4_stakeholder.concreteness === 'mid' ? '中程度' : '抽象的'}</div></div>)}
                  {metricsModalQa.metrics.qq5_actionability && (<div className="detail-flags">{metricsModalQa.metrics.qq5_actionability.is_yes_no_form && <span className="detail-badge">Yes/No形式</span>}{metricsModalQa.metrics.qq5_actionability.has_deadline && <span className="detail-badge">期限設定あり</span>}{metricsModalQa.metrics.qq5_actionability.presents_options && <span className="detail-badge">選択肢提示あり</span>}</div>)}
                </div>
                <div className="detail-section">
                  <h4 className="detail-heading">答弁の質・価値 (AS/OC)</h4>
                  {metricsModalQa.metrics.oc1_record_value && (<div className="detail-row"><div className="detail-meta"><span className="detail-name">記録的価値</span><div className="metric-bar-wrap metric-bar-wrap--sm"><div className="metric-bar" style={{ width: scorePercent(metricsModalQa.metrics.oc1_record_value.score), background: scoreColor(metricsModalQa.metrics.oc1_record_value.score) }} /></div></div><div className="detail-flags">{metricsModalQa.metrics.oc1_record_value.pins_legal_interpretation && <span className="detail-badge detail-badge--gold">法解釈の確定</span>}{metricsModalQa.metrics.oc1_record_value.fixes_official_number && <span className="detail-badge detail-badge--gold">公的数値の確定</span>}{metricsModalQa.metrics.oc1_record_value.goes_beyond_precedent && <span className="detail-badge detail-badge--gold">前例超越</span>}</div></div>)}
                  {metricsModalQa.metrics.as2_information_density && (<div className="detail-row"><span className="detail-name">具体情報の内訳</span>{metricsModalQa.metrics.as2_information_density.concrete_items_in_answer?.length > 0 ? <ul className="detail-list">{metricsModalQa.metrics.as2_information_density.concrete_items_in_answer.map((item, i) => <li key={i}><span className="item-tag">{item.type}</span> {item.excerpt}</li>)}</ul> : <span className="detail-hint">具体的な提示なし</span>}</div>)}
                </div>
              </div>
              {metricsModalQa.metrics.evaluation_note && (
                <div className="evaluation-note-section"><h4 className="detail-heading">AI評価メモ</h4><div className="evaluation-note">{metricsModalQa.metrics.evaluation_note}</div></div>
              )}
            </div>
          </div>
        </div>
      )}

      <style>{`
        .filtered-qa-list { width: 100%; }

        .qa-toolbar {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 1rem;
          margin-bottom: 1rem;
          padding: 0.75rem 1rem;
          background: #f8fafc;
          border: 1px solid #e5e7eb;
          border-radius: 8px;
          flex-wrap: wrap;
        }
        .qa-count { font-size: 0.9rem; color: #374151; }
        .qa-count strong { color: #111; }
        .qa-actions { display: flex; gap: 0.5rem; }

        .btn-copy {
          padding: 0.4rem 0.9rem;
          background: #2563eb;
          color: #fff;
          border: none;
          border-radius: 6px;
          cursor: pointer;
          font-size: 0.85rem;
          transition: background 0.15s;
        }
        .btn-copy:hover:not(:disabled) { background: #1d4ed8; }
        .btn-copy:disabled { background: #9ca3af; cursor: default; }
        .btn-copy.success { background: #16a34a; }
        .btn-copy.error { background: #dc2626; }

        .copy-fallback {
          margin-bottom: 1rem;
          padding: 0.75rem;
          background: #fef2f2;
          border: 1px solid #fca5a5;
          border-radius: 6px;
          font-size: 0.85rem;
        }
        .copy-fallback textarea {
          width: 100%;
          margin-top: 0.5rem;
          font-family: monospace;
          font-size: 0.8rem;
          resize: vertical;
        }

        .empty-state {
          padding: 3rem 1rem;
          text-align: center;
          color: #6b7280;
          background: #f9fafb;
          border: 1px dashed #d1d5db;
          border-radius: 8px;
        }

        .qa-cards { display: flex; flex-direction: column; gap: 1rem; }

        .qa-card {
          border: 1px solid #e5e7eb;
          border-radius: 10px;
          background: #fff;
          overflow: hidden;
          box-shadow: 0 1px 3px rgba(0,0,0,0.04);
        }

        /* ── ヘッダー ── */
        .qa-header {
          display: flex;
          justify-content: space-between;
          align-items: flex-start;
          flex-wrap: wrap;
          gap: 0.5rem;
          padding: 0.5rem 1rem;
          background: #f8fafc;
          border-bottom: 1px solid #e5e7eb;
          font-size: 0.85rem;
        }
        .qa-meta { display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; }
        .qa-header-right { display: flex; align-items: center; gap: 0.75rem; flex-wrap: wrap; }
        .qa-topic { font-weight: 600; color: #374151; }

        .chamber-badge {
          display: inline-block;
          width: 1.5rem;
          height: 1.5rem;
          line-height: 1.5rem;
          text-align: center;
          border-radius: 4px;
          font-size: 0.75rem;
          font-weight: 700;
          flex-shrink: 0;
        }
        .chamber-badge.shugiin { background: #dbeafe; color: #1e40af; }
        .chamber-badge.sangiin { background: #fce7f3; color: #9d174d; }
        .session-link {
          display: flex;
          align-items: center;
          gap: 0.5rem;
          text-decoration: none;
          color: inherit;
        }
        .session-link:hover .qa-date,
        .session-link:hover .qa-committee {
          color: #2563eb;
          text-decoration: underline;
        }
        .qa-date { color: #6b7280; font-size: 0.85rem; }
        .qa-committee { font-weight: 500; color: #374151; }

        .video-link {
          color: #2563eb;
          text-decoration: none;
          font-size: 0.8rem;
          white-space: nowrap;
        }
        .video-link:hover { text-decoration: underline; }

        /* ── 行ベース構造 ── */
        .qa-row {
          display: flex;
          border-bottom: 1px solid #f1f5f9;
        }
        .qa-row:last-of-type {
          border-bottom: none;
        }

        .qa-label {
          flex-shrink: 0;
          width: 4.5rem;
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: flex-start;
          gap: 0.3rem;
          padding: 0.6rem 0.35rem;
          border-right: 3px solid transparent;
        }
        .qa-label-text {
          font-size: 0.75rem;
          font-weight: 700;
          letter-spacing: 0.08em;
        }
        .qa-label--question { color: #1e40af; background: #eff6ff; border-right-color: #3b82f6; }
        .qa-label--answer   { color: #065f46; background: #ecfdf5; border-right-color: #10b981; }
        .qa-label--fulltext { color: #92400e; background: #fffbeb; border-right-color: #f59e0b; }

        .score-chip {
          display: flex;
          flex-direction: column;
          align-items: center;
          width: 100%;
          background: rgba(255,255,255,0.55);
          border: 1px solid rgba(0,0,0,0.1);
          border-radius: 5px;
          padding: 0.2rem 0.25rem;
          cursor: pointer;
          gap: 1px;
          transition: background 0.1s;
        }
        .score-chip:hover { background: rgba(255,255,255,0.9); }
        .score-chip-key { font-size: 0.6rem; opacity: 0.55; line-height: 1; }
        .score-chip-val { font-size: 0.68rem; font-weight: 700; line-height: 1.2; }
        .score-chip-row { display: flex; align-items: center; gap: 0.2rem; }

        /* ── モーダル ── */
        .modal-overlay {
          position: fixed; inset: 0; background: rgba(0,0,0,0.4);
          display: flex; align-items: center; justify-content: center;
          z-index: 1000; padding: 1rem;
        }
        .modal-box {
          background: #fff; border-radius: 12px; max-width: 700px; width: 100%;
          max-height: 85vh; overflow-y: auto;
          box-shadow: 0 20px 60px rgba(0,0,0,0.25);
        }
        .modal-header {
          display: flex; justify-content: space-between; align-items: center;
          padding: 0.9rem 1.25rem; border-bottom: 1px solid #e5e7eb;
          position: sticky; top: 0; background: #fff; z-index: 1;
        }
        .modal-title { font-size: 0.95rem; font-weight: 600; color: #111; margin: 0; }
        .modal-close {
          background: none; border: none; font-size: 1.1rem; cursor: pointer;
          color: #9ca3af; padding: 0.2rem 0.4rem; border-radius: 4px;
        }
        .modal-close:hover { background: #f3f4f6; color: #374151; }
        .modal-body { padding: 1.25rem; }

        .qa-content {
          flex: 1;
          padding: 0.75rem 1rem;
          min-width: 0;
        }

        /* ── スピーカー ── */
        .speaker-line {
          font-size: 0.85rem;
          color: #374151;
          margin-bottom: 0.3rem;
        }
        .speaker-line strong { color: #111827; }
        .party, .role { color: #6b7280; font-size: 0.8rem; }

        /* ── 要約 ── */
        .summary { margin: 0; font-size: 0.9rem; line-height: 1.5; }
        .summary-list {
          margin: 0;
          padding-left: 1.2rem;
          font-size: 0.9rem;
          line-height: 1.6;
        }
        .summary-list li { margin-bottom: 0.15rem; }

        /* ── 評価指標 ── */
        .metrics-grid {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 0.4rem 1.5rem;
          margin-top: 0.5rem;
        }
        @media (max-width: 640px) {
          .metrics-grid { grid-template-columns: 1fr; }
        }
        .metric-item {
          display: flex;
          align-items: center;
          gap: 0.35rem;
          font-size: 0.8rem;
        }
        .metric-icon {
          flex-shrink: 0;
          font-size: 0.85rem;
        }
        .metric-label-text {
          flex-shrink: 0;
          color: #6b7280;
          width: 5rem;
          font-size: 0.78rem;
        }
        .metric-bar-wrap {
          flex: 1;
          height: 6px;
          background: #f1f5f9;
          border-radius: 3px;
          overflow: hidden;
          min-width: 3rem;
        }
        .metric-bar {
          height: 100%;
          border-radius: 3px;
          transition: width 0.3s ease;
        }
        .metric-value {
          flex-shrink: 0;
          font-weight: 700;
          font-size: 0.78rem;
          min-width: 2.5rem;
          text-align: right;
        }
        .commitment-inline {
          display: flex;
          align-items: center;
          gap: 0.5rem;
          margin-top: 0.4rem;
          flex-wrap: wrap;
        }
        .commitment-lv {
          font-size: 0.75rem;
          font-weight: 600;
          padding: 0.1rem 0.4rem;
          border-radius: 4px;
          white-space: nowrap;
        }
        .commitment-lv-0 { background: #f3f4f6; color: #6b7280; }
        .commitment-lv-1 { background: #fef3c7; color: #92400e; }
        .commitment-lv-2 { background: #dbeafe; color: #1e40af; }
        .commitment-lv-3 { background: #d1fae5; color: #065f46; }
        .commitment-lv-4 { background: #a7f3d0; color: #064e3b; font-weight: 700; }
        .commitment-phrase {
          font-size: 0.78rem;
          color: #374151;
          font-style: italic;
        }

        /* ── 全文表示（統合） ── */
        .qa-row--fulltext {
          border-bottom: none;
        }
        .expand-toggle {
          background: none;
          border: none;
          padding: 0;
          font-size: 0.8rem;
          color: #2563eb;
          cursor: pointer;
          font-weight: 500;
        }
        .expand-toggle:hover { text-decoration: underline; }
        .full-text-combined {
          margin-top: 0.5rem;
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 0.75rem;
          align-items: start;
        }
        @media (max-width: 768px) {
          .full-text-combined { grid-template-columns: 1fr; }
        }
        .full-text-section {
          border: 1px solid #e5e7eb;
          border-radius: 6px;
          overflow: hidden;
          display: flex;
          flex-direction: column;
        }
        .full-text-section-label {
          font-size: 0.78rem;
          font-weight: 600;
          padding: 0.35rem 0.75rem;
          border-bottom: 1px solid #e5e7eb;
          display: flex;
          align-items: center;
          gap: 0.4rem;
          flex-wrap: wrap;
        }
        .full-text-section-label--q {
          background: #eff6ff;
          color: #1e40af;
        }
        .full-text-section-label--a {
          background: #ecfdf5;
          color: #065f46;
        }
        .fts-party {
          font-weight: 400;
          font-size: 0.72rem;
          opacity: 0.8;
        }
        .full-text {
          flex: 1;
          margin: 0;
          font-size: 0.85rem;
          line-height: 1.7;
          color: #374151;
          background: #f9fafb;
          padding: 0.75rem;
        }
        .full-text p {
          margin: 0 0 0.5rem;
          text-indent: 1em;
        }
        .full-text p:last-child { margin-bottom: 0; }

        .quote-label { font-weight: 600; color: #1d4ed8; }

        .metrics-detail-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 2rem; }
        @media (max-width: 640px) { .metrics-detail-grid { grid-template-columns: 1fr; gap: 1.5rem; } }

        .detail-section { display: flex; flex-direction: column; gap: 1rem; }
        .detail-heading {
          font-size: 0.85rem; font-weight: 600; color: #4b5563;
          border-left: 3px solid #9ca3af; padding-left: 0.5rem; margin: 0;
        }
        .detail-row { display: flex; flex-direction: column; gap: 0.4rem; }
        .detail-meta { display: flex; align-items: center; gap: 0.75rem; }
        .detail-name { font-size: 0.8rem; color: #6b7280; min-width: 80px; }
        .detail-text-info { font-size: 0.8rem; color: #374151; }
        .detail-list {
          margin: 0; padding: 0; list-style: none; font-size: 0.75rem; color: #4b5563;
          display: flex; flex-direction: column; gap: 0.25rem;
        }
        .detail-list li { background: #f9fafb; padding: 0.2rem 0.4rem; border-radius: 4px; line-height: 1.4; }
        .source-tag, .item-tag {
          display: inline-block; font-size: 0.65rem; background: #e5e7eb; color: #4b5563;
          padding: 0 0.3rem; border-radius: 3px; margin-right: 0.3rem; font-weight: 500;
        }
        .detail-flags { display: flex; flex-wrap: wrap; gap: 0.4rem; }
        .detail-badge {
          font-size: 0.7rem; background: #eff6ff; color: #1d4ed8; padding: 0.1rem 0.4rem;
          border-radius: 4px; border: 1px solid #dbeafe;
        }
        .detail-badge--gold { background: #fffbeb; color: #b45309; border-color: #fef3c7; font-weight: 600; }

        .evaluation-note-section { margin-top: 1.5rem; padding-top: 1rem; border-top: 1px solid #f3f4f6; }
        .evaluation-note {
          font-size: 0.8rem; color: #4b5563; line-height: 1.6;
          background: #f9fafb; padding: 0.75rem; border-radius: 6px; margin-top: 0.5rem;
        }

        .qa-row--fulltext { border-bottom: none; }

        /* ── フッター ── */
        .qa-footer {
          padding: 0.4rem 1rem;
          background: #f8fafc;
          border-top: 1px solid #e5e7eb;
          font-size: 0.75rem;
          color: #9ca3af;
        }
        .source-link { color: #9ca3af; text-decoration: none; }
        .source-link:hover { text-decoration: underline; color: #6b7280; }

        /* ── ページネーション ── */
        .pagination {
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 0.25rem;
          margin-top: 1.5rem;
          flex-wrap: wrap;
        }
        .page-btn {
          min-width: 2rem;
          height: 2rem;
          padding: 0 0.5rem;
          border: 1px solid #d1d5db;
          border-radius: 4px;
          background: #fff;
          cursor: pointer;
          font-size: 0.875rem;
          transition: background 0.1s, border-color 0.1s;
        }
        .page-btn:hover:not(:disabled) { background: #f3f4f6; border-color: #9ca3af; }
        .page-btn:disabled { color: #9ca3af; cursor: default; }
        .page-btn.active {
          background: #2563eb;
          color: #fff;
          border-color: #2563eb;
          font-weight: 600;
        }
        .page-ellipsis { padding: 0 0.25rem; color: #9ca3af; }
      `}</style>
    </div>
  );
}

/**
 * ページ番号配列を生成する（前後2ページ + 省略記号）。
 */
function buildPageNumbers(current, total) {
  if (total <= 7) {
    return Array.from({ length: total }, (_, i) => i + 1);
  }
  const pages = [];
  pages.push(1);
  if (current > 4) pages.push('...');
  for (let p = Math.max(2, current - 2); p <= Math.min(total - 1, current + 2); p++) {
    pages.push(p);
  }
  if (current < total - 3) pages.push('...');
  pages.push(total);
  return pages;
}
