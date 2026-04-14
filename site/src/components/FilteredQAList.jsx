import { useState, useCallback } from 'react';
import { indexEntriesToTsv } from '../lib/tsv-export';

const PAGE_SIZE = 20;

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
export default function FilteredQAList({ filteredEntries, totalCount, page, onPageChange }) {
  const [copyState, setCopyState] = useState('idle'); // idle | success | error

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

  function evasionColor(score) {
    if (score < 0.3) return '#16a34a';
    if (score < 0.7) return '#d97706';
    return '#dc2626';
  }

  function evasionLabel(score) {
    if (score < 0.3) return '低';
    if (score < 0.7) return '中';
    return '高';
  }

  function chamberLabel(chamber) {
    return chamber === 'shugiin' ? '衆議院TV' : '参議院TV';
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
              return (
                <div key={qa.id} className="qa-card">
                  <div className="qa-header">
                    <div className="qa-meta">
                      <span className={`chamber-badge ${entry.chamber}`}>
                        {entry.chamber === 'shugiin' ? '衆' : '参'}
                      </span>
                      <span className="qa-date">{entry.date}</span>
                      <span className="qa-committee">{entry.committee}</span>
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

                  <div className="qa-columns">
                    <div className="question">
                      <div className="speaker-label">
                        質問 — <strong>{qa.question_speaker}</strong>
                        {qa.question_party && (
                          <span className="party">（{qa.question_party}）</span>
                        )}
                      </div>
                      <p className="summary">{qa.question_summary}</p>
                    </div>

                    <div className="answer">
                      <div className="speaker-label">
                        答弁 — <strong>{qa.answer_speaker}</strong>
                        {qa.answer_role && (
                          <span className="role">（{qa.answer_role}）</span>
                        )}
                      </div>
                      <p className="summary">{qa.answer_summary}</p>
                      <div
                        className="evasion"
                        style={{ color: evasionColor(qa.evasion_score) }}
                      >
                        回避度 {evasionLabel(qa.evasion_score)}（{(qa.evasion_score * 100).toFixed(0)}%）
                      </div>
                      {qa.has_commitment && qa.commitment_text && (
                        <div className="commitment">
                          <span className="commitment-label">約束:</span> {qa.commitment_text}
                        </div>
                      )}
                    </div>
                  </div>

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
          border-radius: 8px;
          background: #fff;
          overflow: hidden;
        }
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
        .qa-date { color: #6b7280; font-size: 0.85rem; }
        .qa-committee { font-weight: 500; color: #374151; }

        .video-link {
          color: #2563eb;
          text-decoration: none;
          font-size: 0.8rem;
          white-space: nowrap;
        }
        .video-link:hover { text-decoration: underline; }

        .qa-columns {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 0;
        }
        @media (max-width: 640px) {
          .qa-columns { grid-template-columns: 1fr; }
        }
        .question, .answer { padding: 1rem; }
        .question { border-right: 1px solid #e5e7eb; }
        @media (max-width: 640px) {
          .question { border-right: none; border-bottom: 1px solid #e5e7eb; }
        }
        .speaker-label { font-size: 0.85rem; color: #6b7280; margin-bottom: 0.4rem; }
        .speaker-label strong { color: #111; }
        .party, .role { color: #6b7280; }
        .summary { margin: 0 0 0.5rem; font-size: 0.9rem; line-height: 1.5; }
        .evasion { font-size: 0.8rem; font-weight: 600; margin-bottom: 0.4rem; }
        .commitment {
          font-size: 0.8rem;
          background: #f0fdf4;
          border-left: 3px solid #16a34a;
          padding: 0.4rem 0.6rem;
          margin-top: 0.4rem;
          color: #166534;
          line-height: 1.4;
        }
        .commitment-label { font-weight: 600; }

        .qa-footer {
          padding: 0.4rem 1rem;
          background: #f8fafc;
          border-top: 1px solid #e5e7eb;
          font-size: 0.75rem;
          color: #9ca3af;
        }
        .source-link { color: #9ca3af; text-decoration: none; }
        .source-link:hover { text-decoration: underline; color: #6b7280; }

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
