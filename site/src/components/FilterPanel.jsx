import { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import MultiSelect from './MultiSelect';
import FilteredQAList from './FilteredQAList';

const BASE_URL = import.meta.env.BASE_URL || '';

/**
 * デバウンス用フック
 */
function useDebounce(value, delay) {
  const [debouncedValue, setDebouncedValue] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedValue(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return debouncedValue;
}

/**
 * URLクエリパラメータをパースするヘルパー
 */
function parseUrlParams() {
  if (typeof window === 'undefined') return {};
  const params = new URLSearchParams(window.location.search);
  return {
    chamber: params.get('chamber') || 'all',
    from: params.get('from') || '',
    to: params.get('to') || '',
    committees: params.getAll('committee'),
    parties: params.getAll('party'),
    speaker: params.get('speaker') || '',
    roles: params.getAll('role'),
    topics: params.getAll('topic'),
    laws: params.getAll('law'),
    page: parseInt(params.get('page') || '1', 10),
  };
}

/**
 * フィルタ状態をURLに反映する（historyを汚さない）
 */
function updateUrl(filters) {
  if (typeof window === 'undefined') return;
  const params = new URLSearchParams();
  if (filters.chamber !== 'all') params.set('chamber', filters.chamber);
  if (filters.from) params.set('from', filters.from);
  if (filters.to) params.set('to', filters.to);
  filters.committees.forEach((c) => params.append('committee', c));
  filters.parties.forEach((p) => params.append('party', p));
  if (filters.speaker) params.set('speaker', filters.speaker);
  filters.roles.forEach((r) => params.append('role', r));
  filters.topics.forEach((t) => params.append('topic', t));
  filters.laws.forEach((l) => params.append('law', l));
  if (filters.page > 1) params.set('page', String(filters.page));
  const qs = params.toString();
  const newUrl = qs ? `${window.location.pathname}?${qs}` : window.location.pathname;
  window.history.replaceState(null, '', newUrl);
}

const ALL_ROLES = ['質疑者', '答弁者', '政府参考人', '委員長'];

/**
 * FilterPanel — 7軸フィルタUI + Q&Aリスト統合コンポーネント
 */
export default function FilterPanel() {
  // ローディング状態
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // データ
  const [indexData, setIndexData] = useState([]);
  const [committees, setCommittees] = useState([]);
  const [parties, setParties] = useState([]);
  const [topicOptions, setTopicOptions] = useState([]);
  const [lawOptions, setLawOptions] = useState([]);

  // フィルタ状態（URLから初期化）
  const initialParams = useMemo(() => parseUrlParams(), []);
  const [chamber, setChamber] = useState(initialParams.chamber || 'all');
  const [dateFrom, setDateFrom] = useState(initialParams.from || '');
  const [dateTo, setDateTo] = useState(initialParams.to || '');
  const [selectedCommittees, setSelectedCommittees] = useState(initialParams.committees || []);
  const [selectedParties, setSelectedParties] = useState(initialParams.parties || []);
  const [speakerText, setSpeakerText] = useState(initialParams.speaker || '');
  const [selectedRoles, setSelectedRoles] = useState(
    initialParams.roles && initialParams.roles.length > 0 ? initialParams.roles : ALL_ROLES
  );
  const [selectedTopics, setSelectedTopics] = useState(initialParams.topics || []);
  const [selectedLaws, setSelectedLaws] = useState(initialParams.laws || []);
  const [page, setPage] = useState(initialParams.page || 1);

  // デバウンス済み発言者テキスト
  const debouncedSpeaker = useDebounce(speakerText, 300);

  // モバイル用フィルタ折りたたみ
  const [filterOpen, setFilterOpen] = useState(false);

  // データ取得
  useEffect(() => {
    async function fetchData() {
      try {
        const [indexRes, committeesRes, partiesRes, topicsRes, lawsRes] = await Promise.all([
          fetch(`${BASE_URL}/api/index.json`),
          fetch(`${BASE_URL}/api/committees.json`),
          fetch(`${BASE_URL}/api/parties.json`),
          fetch(`${BASE_URL}/api/topics.json`),
          fetch(`${BASE_URL}/api/laws.json`),
        ]);

        const [indexJson, committeesJson, partiesJson, topicsJson, lawsJson] = await Promise.all([
          indexRes.json(),
          committeesRes.json(),
          partiesRes.json(),
          topicsRes.json(),
          lawsRes.json(),
        ]);

        setIndexData(indexJson);
        setCommittees(committeesJson.map((c) => c.name));
        setParties(partiesJson.map((p) => p.name));
        setTopicOptions(topicsJson.map((t) => t.name));
        setLawOptions(lawsJson);
      } catch (e) {
        setError(`データの読み込みに失敗しました: ${e.message}`);
      } finally {
        setLoading(false);
      }
    }
    fetchData();
  }, []);

  // フィルタ変更時にURLを更新
  const filtersForUrl = useMemo(
    () => ({
      chamber,
      from: dateFrom,
      to: dateTo,
      committees: selectedCommittees,
      parties: selectedParties,
      speaker: debouncedSpeaker,
      roles: selectedRoles.length === ALL_ROLES.length ? [] : selectedRoles,
      topics: selectedTopics,
      laws: selectedLaws,
      page,
    }),
    [chamber, dateFrom, dateTo, selectedCommittees, selectedParties, debouncedSpeaker, selectedRoles, selectedTopics, selectedLaws, page]
  );

  useEffect(() => {
    updateUrl(filtersForUrl);
  }, [filtersForUrl]);

  // フィルタロジック（useMemo でキャッシュ）
  const filteredEntries = useMemo(() => {
    return indexData
      .filter((entry) => {
        // 院フィルタ
        if (chamber !== 'all' && entry.chamber !== chamber) return false;
        // 日付範囲フィルタ
        if (dateFrom && entry.date < dateFrom) return false;
        if (dateTo && entry.date > dateTo) return false;
        // 委員会フィルタ（OR条件）
        if (selectedCommittees.length > 0 && !selectedCommittees.includes(entry.committee)) return false;
        // 政党フィルタ（OR条件）
        if (selectedParties.length > 0) {
          const hasParty = entry.parties.some((p) => selectedParties.includes(p));
          if (!hasParty) return false;
        }
        // 発言者フィルタ（部分一致）
        if (debouncedSpeaker) {
          const lower = debouncedSpeaker.toLowerCase();
          const hasSpeaker = entry.speakers.some((s) =>
            s.toLowerCase().includes(lower)
          );
          if (!hasSpeaker) return false;
        }
        // トピックフィルタ（OR条件）
        if (selectedTopics.length > 0) {
          const hasTopic = entry.topics.some((t) => selectedTopics.includes(t));
          if (!hasTopic) return false;
        }
        // 関連法案フィルタ（OR条件）
        if (selectedLaws.length > 0) {
          const hasLaw = (entry.related_laws || []).some((l) => selectedLaws.includes(l));
          if (!hasLaw) return false;
        }
        return true;
      })
      .map((entry) => {
        // 役割フィルタはQ&Aペアレベルで適用
        const filteredPairs = entry.qa_pairs.filter((qa) => {
          if (selectedRoles.length === ALL_ROLES.length) return true;
          const questionerMatch = selectedRoles.includes('質疑者') &&
            (qa.question_speaker || qa.answer_speaker);
          const answererMatch = selectedRoles.includes('答弁者') &&
            qa.answer_speaker;
          const refMatch = selectedRoles.includes('政府参考人') &&
            qa.answer_role?.includes('政府参考人');
          const chairMatch = selectedRoles.includes('委員長') &&
            (qa.answer_role?.includes('委員長') || qa.question_speaker?.includes('委員長'));
          return questionerMatch || answererMatch || refMatch || chairMatch;
        });

        // 政党フィルタをQ&Aペアレベルでも適用
        const partyFiltered = selectedParties.length > 0
          ? filteredPairs.filter((qa) =>
              selectedParties.includes(qa.question_party)
            )
          : filteredPairs;

        // 発言者フィルタをQ&Aペアレベルでも適用
        const speakerFiltered = debouncedSpeaker
          ? partyFiltered.filter((qa) => {
              const lower = debouncedSpeaker.toLowerCase();
              return (
                qa.question_speaker.toLowerCase().includes(lower) ||
                qa.answer_speaker.toLowerCase().includes(lower)
              );
            })
          : partyFiltered;

        // トピックフィルタをQ&Aペアレベルでも適用
        const topicFiltered = selectedTopics.length > 0
          ? speakerFiltered.filter((qa) => selectedTopics.includes(qa.topic))
          : speakerFiltered;

        return { ...entry, qa_pairs: topicFiltered };
      })
      .filter((entry) => entry.qa_pairs.length > 0);
  }, [indexData, chamber, dateFrom, dateTo, selectedCommittees, selectedParties, debouncedSpeaker, selectedRoles, selectedTopics, selectedLaws]);

  const totalCount = useMemo(
    () => indexData.reduce((sum, e) => sum + e.qa_pairs.length, 0),
    [indexData]
  );

  // フィルタ変更時にページ1に戻す
  const handleFilterChange = useCallback((setter) => (value) => {
    setter(value);
    setPage(1);
  }, []);

  function resetFilters() {
    setChamber('all');
    setDateFrom('');
    setDateTo('');
    setSelectedCommittees([]);
    setSelectedParties([]);
    setSpeakerText('');
    setSelectedRoles(ALL_ROLES);
    setSelectedTopics([]);
    setSelectedLaws([]);
    setPage(1);
  }

  function toggleRole(role) {
    const next = selectedRoles.includes(role)
      ? selectedRoles.filter((r) => r !== role)
      : [...selectedRoles, role];
    setSelectedRoles(next);
    setPage(1);
  }

  const hasActiveFilters =
    chamber !== 'all' ||
    dateFrom !== '' ||
    dateTo !== '' ||
    selectedCommittees.length > 0 ||
    selectedParties.length > 0 ||
    speakerText !== '' ||
    selectedRoles.length !== ALL_ROLES.length ||
    selectedTopics.length > 0 ||
    selectedLaws.length > 0;

  if (loading) {
    return (
      <div className="filter-panel-loading">
        <div className="skeleton skeleton-filters" />
        <div className="skeleton skeleton-card" />
        <div className="skeleton skeleton-card" />
        <div className="skeleton skeleton-card" />
        <style>{`
          .filter-panel-loading { display: flex; flex-direction: column; gap: 1rem; }
          .skeleton {
            background: linear-gradient(90deg, #f0f0f0 25%, #e0e0e0 50%, #f0f0f0 75%);
            background-size: 200% 100%;
            animation: shimmer 1.5s infinite;
            border-radius: 8px;
          }
          .skeleton-filters { height: 180px; }
          .skeleton-card { height: 160px; }
          @keyframes shimmer {
            0% { background-position: 200% 0; }
            100% { background-position: -200% 0; }
          }
        `}</style>
      </div>
    );
  }

  if (error) {
    return (
      <div className="filter-error">
        <p>{error}</p>
      </div>
    );
  }

  return (
    <div className="filter-panel">
      {/* モバイル用トグル */}
      <button
        type="button"
        className="filter-toggle-btn"
        onClick={() => setFilterOpen((o) => !o)}
        aria-expanded={filterOpen}
      >
        🔍 フィルタ {hasActiveFilters ? '（適用中）' : ''} {filterOpen ? '▲' : '▼'}
      </button>

      {/* フィルタUI */}
      <div className={`filter-controls ${filterOpen ? 'open' : ''}`}>
        {/* 院 */}
        <div className="filter-row">
          <fieldset className="filter-fieldset">
            <legend>院</legend>
            <div className="radio-group">
              {[['all', '全て'], ['shugiin', '衆議院'], ['sangiin', '参議院']].map(
                ([val, label]) => (
                  <label key={val} className="radio-label">
                    <input
                      type="radio"
                      name="chamber"
                      value={val}
                      checked={chamber === val}
                      onChange={() => { setChamber(val); setPage(1); }}
                    />
                    {label}
                  </label>
                )
              )}
            </div>
          </fieldset>

          {/* 日付範囲 */}
          <div className="filter-group">
            <label className="filter-label">日付</label>
            <div className="date-range">
              <input
                type="date"
                value={dateFrom}
                onChange={(e) => { setDateFrom(e.target.value); setPage(1); }}
                aria-label="開始日"
              />
              <span className="date-sep">〜</span>
              <input
                type="date"
                value={dateTo}
                onChange={(e) => { setDateTo(e.target.value); setPage(1); }}
                aria-label="終了日"
              />
            </div>
          </div>
        </div>

        {/* 委員会・政党・トピック・関連法案 */}
        <div className="filter-row filter-row-selects">
          <MultiSelect
            label="委員会"
            options={committees}
            value={selectedCommittees}
            onChange={handleFilterChange(setSelectedCommittees)}
          />
          <MultiSelect
            label="政党/会派"
            options={parties}
            value={selectedParties}
            onChange={handleFilterChange(setSelectedParties)}
          />
          <MultiSelect
            label="トピック"
            options={topicOptions}
            value={selectedTopics}
            onChange={handleFilterChange(setSelectedTopics)}
          />
          {lawOptions.length > 0 && (
            <MultiSelect
              label="関連法案"
              options={lawOptions.map((l) => l.short_title)}
              value={selectedLaws.map((id) => {
                const law = lawOptions.find((l) => l.id === id);
                return law ? law.short_title : id;
              })}
              onChange={(titles) => {
                const ids = titles.map((t) => {
                  const law = lawOptions.find((l) => l.short_title === t);
                  return law ? law.id : t;
                });
                handleFilterChange(setSelectedLaws)(ids);
              }}
              placeholder="法案で絞り込み..."
            />
          )}
        </div>

        {/* 発言者・役割 */}
        <div className="filter-row">
          <div className="filter-group filter-group-speaker">
            <label className="filter-label" htmlFor="speaker-input">発言者名</label>
            <input
              id="speaker-input"
              type="text"
              className="speaker-input"
              placeholder="氏名で絞り込み..."
              value={speakerText}
              onChange={(e) => setSpeakerText(e.target.value)}
            />
          </div>

          <fieldset className="filter-fieldset">
            <legend>役割</legend>
            <div className="checkbox-group">
              {ALL_ROLES.map((role) => (
                <label key={role} className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={selectedRoles.includes(role)}
                    onChange={() => toggleRole(role)}
                  />
                  {role}
                </label>
              ))}
            </div>
          </fieldset>
        </div>

        {/* リセットボタン */}
        {hasActiveFilters && (
          <div className="filter-reset-row">
            <button type="button" className="btn-reset" onClick={resetFilters}>
              フィルタをリセット
            </button>
          </div>
        )}
      </div>

      {/* 結果リスト */}
      <FilteredQAList
        filteredEntries={filteredEntries}
        totalCount={totalCount}
        page={page}
        onPageChange={setPage}
      />

      <style>{`
        .filter-panel { width: 100%; }

        .filter-toggle-btn {
          display: none;
          width: 100%;
          padding: 0.6rem 1rem;
          background: #f3f4f6;
          border: 1px solid #d1d5db;
          border-radius: 8px;
          cursor: pointer;
          font-size: 0.9rem;
          text-align: left;
          margin-bottom: 0.75rem;
        }
        @media (max-width: 767px) {
          .filter-toggle-btn { display: block; }
          .filter-controls {
            display: none;
          }
          .filter-controls.open { display: block; }
        }

        .filter-controls {
          background: #f8fafc;
          border: 1px solid #e5e7eb;
          border-radius: 10px;
          padding: 1rem;
          margin-bottom: 1.25rem;
          display: flex;
          flex-direction: column;
          gap: 0.75rem;
        }

        .filter-row {
          display: flex;
          align-items: flex-start;
          gap: 1.25rem;
          flex-wrap: wrap;
        }
        .filter-row-selects {
          gap: 0.75rem;
        }

        .filter-fieldset {
          border: none;
          padding: 0;
          margin: 0;
        }
        .filter-fieldset legend {
          font-size: 0.8rem;
          color: #6b7280;
          margin-bottom: 0.4rem;
          font-weight: 500;
        }

        .radio-group, .checkbox-group {
          display: flex;
          gap: 0.75rem;
          flex-wrap: wrap;
          align-items: center;
        }
        .radio-label, .checkbox-label {
          display: flex;
          align-items: center;
          gap: 0.3rem;
          font-size: 0.875rem;
          cursor: pointer;
          white-space: nowrap;
        }

        .filter-group {
          display: flex;
          flex-direction: column;
          gap: 0.3rem;
        }
        .filter-group-speaker { min-width: 200px; }
        .filter-label {
          font-size: 0.8rem;
          color: #6b7280;
          font-weight: 500;
        }
        .speaker-input {
          padding: 0.4rem 0.75rem;
          border: 1px solid #d1d5db;
          border-radius: 6px;
          font-size: 0.875rem;
          width: 220px;
          outline: none;
          transition: border-color 0.15s;
        }
        .speaker-input:focus { border-color: #2563eb; }

        .date-range {
          display: flex;
          align-items: center;
          gap: 0.4rem;
        }
        .date-range input[type="date"] {
          padding: 0.4rem 0.5rem;
          border: 1px solid #d1d5db;
          border-radius: 6px;
          font-size: 0.875rem;
          outline: none;
          transition: border-color 0.15s;
        }
        .date-range input[type="date"]:focus { border-color: #2563eb; }
        .date-sep { color: #9ca3af; }

        .filter-reset-row {
          display: flex;
          justify-content: flex-end;
        }
        .btn-reset {
          padding: 0.35rem 0.9rem;
          background: none;
          border: 1px solid #d1d5db;
          border-radius: 6px;
          cursor: pointer;
          font-size: 0.85rem;
          color: #6b7280;
          transition: border-color 0.15s, color 0.15s;
        }
        .btn-reset:hover { border-color: #9ca3af; color: #111; }

        .filter-error {
          padding: 1rem;
          background: #fef2f2;
          border: 1px solid #fca5a5;
          border-radius: 8px;
          color: #dc2626;
        }
      `}</style>
    </div>
  );
}
