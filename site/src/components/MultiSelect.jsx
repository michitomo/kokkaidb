import { useState, useRef, useEffect } from 'react';

/**
 * 汎用の複数選択ドロップダウンコンポーネント。
 * 委員会・政党・トピックフィルタで共用する。
 *
 * @param {object} props
 * @param {string} props.label - ラベルテキスト
 * @param {string[]} props.options - 選択肢の配列
 * @param {string[]} props.value - 現在の選択値
 * @param {(value: string[]) => void} props.onChange - 変更時のコールバック
 * @param {string} [props.placeholder] - 未選択時のプレースホルダー
 */
export default function MultiSelect({ label, options, value, onChange, placeholder }) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState('');
  const containerRef = useRef(null);

  // 外側クリックで閉じる
  useEffect(() => {
    function handleClickOutside(e) {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        setOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const filtered = options.filter((opt) =>
    opt.toLowerCase().includes(search.toLowerCase())
  );

  function toggle(opt) {
    if (value.includes(opt)) {
      onChange(value.filter((v) => v !== opt));
    } else {
      onChange([...value, opt]);
    }
  }

  function clearAll() {
    onChange([]);
    setSearch('');
  }

  const displayText =
    value.length === 0
      ? (placeholder || `${label}（全て）`)
      : value.length === 1
        ? value[0]
        : `${value[0]} 他${value.length - 1}件`;

  return (
    <div className="multi-select" ref={containerRef}>
      <button
        type="button"
        className={`multi-select-trigger ${value.length > 0 ? 'has-value' : ''}`}
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-haspopup="listbox"
      >
        <span className="multi-select-label">{label}</span>
        <span className="multi-select-value">{displayText}</span>
        <span className="multi-select-arrow">{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div className="multi-select-dropdown" role="listbox" aria-multiselectable="true">
          <div className="multi-select-search">
            <input
              type="text"
              placeholder="絞り込み..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              autoFocus
              aria-label={`${label}の絞り込み`}
            />
            {value.length > 0 && (
              <button type="button" className="multi-select-clear" onClick={clearAll}>
                クリア
              </button>
            )}
          </div>
          <ul className="multi-select-options">
            {filtered.length === 0 ? (
              <li className="multi-select-empty">候補なし</li>
            ) : (
              filtered.map((opt) => (
                <li
                  key={opt}
                  role="option"
                  aria-selected={value.includes(opt)}
                  className={`multi-select-option ${value.includes(opt) ? 'selected' : ''}`}
                  onClick={() => toggle(opt)}
                >
                  <span className="multi-select-checkbox">
                    {value.includes(opt) ? '☑' : '☐'}
                  </span>
                  {opt}
                </li>
              ))
            )}
          </ul>
        </div>
      )}

      <style>{`
        .multi-select {
          position: relative;
          display: inline-block;
          min-width: 160px;
        }
        .multi-select-trigger {
          width: 100%;
          display: flex;
          align-items: center;
          gap: 0.4rem;
          padding: 0.4rem 0.75rem;
          background: #fff;
          border: 1px solid #d1d5db;
          border-radius: 6px;
          cursor: pointer;
          font-size: 0.875rem;
          text-align: left;
          transition: border-color 0.15s;
          white-space: nowrap;
          overflow: hidden;
        }
        .multi-select-trigger:hover,
        .multi-select-trigger[aria-expanded="true"] {
          border-color: #2563eb;
        }
        .multi-select-trigger.has-value {
          border-color: #2563eb;
          background: #eff6ff;
        }
        .multi-select-label {
          color: #6b7280;
          font-size: 0.8rem;
          flex-shrink: 0;
        }
        .multi-select-value {
          flex: 1;
          overflow: hidden;
          text-overflow: ellipsis;
          color: #111;
        }
        .multi-select-arrow {
          color: #9ca3af;
          font-size: 0.7rem;
          flex-shrink: 0;
        }
        .multi-select-dropdown {
          position: absolute;
          top: calc(100% + 4px);
          left: 0;
          min-width: 100%;
          max-width: 320px;
          background: #fff;
          border: 1px solid #d1d5db;
          border-radius: 8px;
          box-shadow: 0 4px 16px rgba(0,0,0,0.12);
          z-index: 100;
          overflow: hidden;
        }
        .multi-select-search {
          display: flex;
          align-items: center;
          gap: 0.5rem;
          padding: 0.5rem;
          border-bottom: 1px solid #e5e7eb;
        }
        .multi-select-search input {
          flex: 1;
          border: 1px solid #d1d5db;
          border-radius: 4px;
          padding: 0.3rem 0.5rem;
          font-size: 0.85rem;
          outline: none;
        }
        .multi-select-search input:focus {
          border-color: #2563eb;
        }
        .multi-select-clear {
          background: none;
          border: none;
          color: #6b7280;
          cursor: pointer;
          font-size: 0.8rem;
          padding: 0.2rem 0.4rem;
          white-space: nowrap;
        }
        .multi-select-clear:hover { color: #dc2626; }
        .multi-select-options {
          list-style: none;
          margin: 0;
          padding: 0.25rem 0;
          max-height: 240px;
          overflow-y: auto;
        }
        .multi-select-option {
          display: flex;
          align-items: center;
          gap: 0.5rem;
          padding: 0.4rem 0.75rem;
          cursor: pointer;
          font-size: 0.875rem;
          transition: background 0.1s;
        }
        .multi-select-option:hover { background: #f3f4f6; }
        .multi-select-option.selected { background: #eff6ff; color: #1d4ed8; }
        .multi-select-checkbox { font-size: 1rem; }
        .multi-select-empty {
          padding: 0.75rem;
          color: #9ca3af;
          font-size: 0.875rem;
          text-align: center;
        }
      `}</style>
    </div>
  );
}
