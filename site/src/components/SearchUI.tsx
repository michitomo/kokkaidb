import { useState, useEffect, useCallback, useRef } from 'react';
import MiniSearch from 'minisearch';

const BASE_URL = import.meta.env.BASE_URL || '';

interface SearchDoc {
  id: string;
  chamber: string;
  date: string;
  committee: string;
  speaker: string;
  role: string;
  text: string;
  tokens: string;
  url: string;
  segIdx: number;
  uttIdx: number;
}

interface ResultItem {
  id: string;
  score: number;
  speaker: string;
  role: string;
  text: string;
  date: string;
  committee: string;
  chamber: string;
  url: string;
  segIdx: number;
  uttIdx: number;
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

function highlightText(text: string, query: string): string {
  const terms = query.split(/\s+/).filter(Boolean);
  let result = text;
  for (const term of terms) {
    const escaped = term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    result = result.replace(new RegExp(`(${escaped})`, 'gi'), '<mark>$1</mark>');
  }
  return result;
}

function excerpt(text: string, query: string, maxLen = 150): string {
  const firstTerm = query.split(/\s+/)[0] || '';
  const idx = text.toLowerCase().indexOf(firstTerm.toLowerCase());
  if (idx < 0 || text.length <= maxLen) return text;
  const start = Math.max(0, idx - 60);
  const end = Math.min(text.length, start + maxLen);
  return (start > 0 ? '…' : '') + text.slice(start, end) + (end < text.length ? '…' : '');
}

const chamberLabel: Record<string, string> = { shugiin: '衆', sangiin: '参' };
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
  const [lastSearchQuery, setLastSearchQuery] = useState('');
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
          setError('検索インデックスが空です');
          setLoading(false);
          return;
        }
        const miniSearch = MiniSearch.loadJSON(jsonText, {
          fields: ['tokens', 'speaker', 'committee'],
          storeFields: ['id', 'speaker', 'role', 'text', 'date', 'committee', 'chamber', 'url', 'segIdx', 'uttIdx'],
          tokenize: (string) => string.split(/\s+/).filter(Boolean),
        });
        indexRef.current = miniSearch;
        setLoading(false);
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Failed to load search index');
        setLoading(false);
      }
    })();
  }, []);

  const handleSearch: React.FormEventHandler = useCallback((e) => {
    e.preventDefault();
    const q = query.trim();
    if (!q || !indexRef.current) return;
    const miniSearch = indexRef.current;
    const segmented = segmentQuery(q) || q;
    setLastSearchQuery(segmented);
    const rawResults = miniSearch.search(segmented, {
      combineWith: 'AND',
      prefix: true,
      boost: { speaker: 2, committee: 1.5 },
    });
    setResults(rawResults.map((r) => ({
      id: r.id as string,
      score: r.score as number,
      speaker: (r as any).speaker,
      role: (r as any).role,
      text: (r as any).text,
      date: (r as any).date,
      committee: (r as any).committee,
      chamber: (r as any).chamber,
      url: (r as any).url,
      segIdx: (r as any).segIdx,
      uttIdx: (r as any).uttIdx,
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
          placeholder="審議内容を検索...（例: 予算 委員会）"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          disabled={loading}
        />
        <button type="submit" className="search-button" disabled={loading || !query.trim()}>
          {loading ? '読み込み中...' : '検索'}
        </button>
      </form>

      {error && <p className="search-error">検索インデックスの読み込みに失敗しました: {error}</p>}

      {loading && <p className="search-info">検索インデックスを読み込み中...</p>}

      {searched && !loading && (
        <p className="result-count">
          {results.length === 0
            ? '該当する発言は見つかりませんでした。'
            : `${results.length}件の発言が見つかりました。`}
        </p>
      )}

      {results.length > 0 && (
        <ul className="result-list">
          {results.slice(0, 50).map((item) => (
            <li key={item.id} className="result-item">
              <a
                href={`${BASE_URL}${item.url}#utt-${item.id}`}
                className="result-link"
              >
                <div className="result-meta">
                  <span className={`chamber-badge ${item.chamber}`}>
                    {chamberLabel[item.chamber] || item.chamber}
                  </span>
                  <span className="result-date">{item.date}</span>
                  <span className="result-committee">{item.committee}</span>
                  <span className={`role-badge role-${roleClass[item.role] || 'answerer'}`}>
                    {item.role}
                  </span>
                  <span className="result-speaker">{item.speaker}</span>
                </div>
                <div
                  className="result-text"
                  dangerouslySetInnerHTML={{
                    __html: lastSearchQuery
                      ? highlightText(escapeHtml(excerpt(item.text, lastSearchQuery)), lastSearchQuery)
                      : escapeHtml(excerpt(item.text, query)),
                  }}
                />
              </a>
            </li>
          ))}
          {results.length > 50 && (
            <li className="result-more">
              上位50件のみ表示（全{results.length}件）
            </li>
          )}
        </ul>
      )}
    </div>
  );
}
