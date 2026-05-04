import { useState, useEffect, useCallback, useRef } from 'react';
import MiniSearch from 'minisearch';

const BASE_URL = import.meta.env.BASE_URL || '';

interface ResultItem {
  id: string;
  score: number;
  type: 'qa' | 'utt';
  chamber: string;
  date: string;
  committee: string;
  topic: string;
  q_speaker: string;
  a_speaker: string;
  speaker: string;
  role: string;
  text: string;
  url: string;
  anchor: string;
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function segmentQuery(q: string): string {
  const seg = new Intl.Segmenter('ja', { granularity: 'word' });
  return [...seg.segment(q)]
    .filter(s => s.isWordLike)
    .map(s => s.segment)
    .join(' ');
}

function highlightText(escapedText: string, query: string): string {
  const terms = query.split(/\s+/).filter(Boolean);
  let result = escapedText;
  for (const term of terms) {
    const escaped = escapeHtml(term).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    result = result.replace(new RegExp(`(${escaped})`, 'gi'), '<mark>$1</mark>');
  }
  return result;
}

function excerpt(text: string, query: string, maxLen = 160): string {
  const firstTerm = query.split(/\s+/)[0] || '';
  const idx = text.toLowerCase().indexOf(firstTerm.toLowerCase());
  if (idx < 0 || text.length <= maxLen) return text.slice(0, maxLen);
  const start = Math.max(0, idx - 50);
  const end = Math.min(text.length, start + maxLen);
  return (start > 0 ? '…' : '') + text.slice(start, end) + (end < text.length ? '…' : '');
}

const chamberLabel: Record<string, string> = { shugiin: '衆', sangiin: '参' };
const chamberClass: Record<string, string> = { shugiin: 'shugiin', sangiin: 'sangiin' };
const roleClass: Record<string, string> = {
  '委員長': 'chair',
  '質疑者': 'questioner',
  '答弁者': 'answerer',
};

export default function SearchUI() {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<ResultItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searched, setSearched] = useState(false);
  const [lastSegmented, setLastSegmented] = useState('');
  const indexRef = useRef<MiniSearch | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const res = await fetch(`${BASE_URL}/api/search-index.json`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const jsonText = await res.text();
        if (!jsonText || jsonText === '[]') {
          setError('検索インデックスが空です。ビルドを再実行してください。');
          setLoading(false);
          return;
        }
        const miniSearch = MiniSearch.loadJSON(jsonText, {
          fields: ['tokens', 'speaker', 'q_speaker', 'a_speaker', 'committee'],
          storeFields: ['id', 'type', 'speaker', 'role', 'q_speaker', 'a_speaker', 'topic', 'text', 'date', 'committee', 'chamber', 'url', 'anchor'],
          tokenize: (s) => s.split(/\s+/).filter(Boolean),
        });
        indexRef.current = miniSearch;
        setLoading(false);
      } catch (e) {
        setError(e instanceof Error ? e.message : '読み込みに失敗しました');
        setLoading(false);
      }
    })();
  }, []);

  const handleSearch = useCallback((e: { preventDefault(): void }) => {
    e.preventDefault();
    const q = query.trim();
    if (!q || !indexRef.current) return;
    const segmented = segmentQuery(q) || q;
    setLastSegmented(segmented);
    const rawResults = indexRef.current.search(segmented, {
      combineWith: 'AND',
      prefix: true,
      boost: { q_speaker: 2, a_speaker: 2, speaker: 2, committee: 1.5 },
    });
    setResults(rawResults.map((r) => ({
      id: r.id as string,
      score: r.score as number,
      type: (r as any).type as 'qa' | 'utt',
      chamber: (r as any).chamber,
      date: (r as any).date,
      committee: (r as any).committee,
      topic: (r as any).topic,
      q_speaker: (r as any).q_speaker,
      a_speaker: (r as any).a_speaker,
      speaker: (r as any).speaker,
      role: (r as any).role,
      text: (r as any).text,
      url: (r as any).url,
      anchor: (r as any).anchor,
    })));
    setSearched(true);
  }, [query]);

  return (
    <div className="search-ui">
      <form onSubmit={handleSearch} className="search-form">
        <input
          ref={inputRef}
          type="text"
          className="search-input"
          placeholder="審議内容を検索...（例: 消費税 予算）"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          disabled={loading}
        />
        <button type="submit" className="search-button" disabled={loading || !query.trim()}>
          {loading ? '準備中...' : '検索'}
        </button>
      </form>

      {error && <p className="search-error">{error}</p>}
      {loading && <p className="search-loading">検索インデックスを読み込み中...</p>}

      {searched && !loading && (
        <p className="result-count">
          {results.length === 0
            ? '該当する質疑は見つかりませんでした。'
            : `${results.length.toLocaleString()}件 見つかりました。`}
        </p>
      )}

      {results.length > 0 && (
        <ul className="result-list">
          {results.slice(0, 50).map((item) => {
            const displayText = excerpt(item.text, lastSegmented);
            const highlighted = highlightText(escapeHtml(displayText), lastSegmented);
            return (
              <li key={item.id} className="result-item">
                <a
                  href={`${BASE_URL}${item.url}#${item.anchor}`}
                  className="result-link"
                >
                  <div className="result-meta">
                    <span className={`chamber-badge ${chamberClass[item.chamber] || ''}`}>
                      {chamberLabel[item.chamber] || item.chamber}
                    </span>
                    <span className="result-date">{item.date}</span>
                    <span className="result-committee">{item.committee}</span>
                    {item.type === 'qa' && item.topic && (
                      <span className="result-topic">{item.topic}</span>
                    )}
                    {item.type === 'utt' && item.role && (
                      <span className={`role-badge role-${roleClass[item.role] || 'answerer'}`}>
                        {item.role}
                      </span>
                    )}
                  </div>
                  {item.type === 'qa' ? (
                    <div className="result-speakers">
                      <span className="result-q-speaker">{item.q_speaker}</span>
                      <span className="result-arrow">→</span>
                      <span className="result-a-speaker">{item.a_speaker}</span>
                    </div>
                  ) : (
                    <div className="result-speaker-line">
                      <span className="result-speaker">{item.speaker}</span>
                    </div>
                  )}
                  <div
                    className="result-text"
                    dangerouslySetInnerHTML={{ __html: highlighted }}
                  />
                </a>
              </li>
            );
          })}
          {results.length > 50 && (
            <li className="result-more">
              上位50件のみ表示（全{results.length.toLocaleString()}件）
            </li>
          )}
        </ul>
      )}
    </div>
  );
}
