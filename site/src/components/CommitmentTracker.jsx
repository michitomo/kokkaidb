import { useState, useMemo } from "react";

const CHAMBER_LABEL = { shugiin: "衆議院", sangiin: "参議院" };
const STATUS_LABEL = { unverified: "未確認" };
const STATUS_COLOR = { unverified: "#9ca3af" };

export default function CommitmentTracker({ commitments }) {
  const [chamber, setChamber] = useState("all");
  const [searchText, setSearchText] = useState("");
  const [groupByTopic, setGroupByTopic] = useState(false);

  const base = import.meta.env.BASE_URL?.replace(/\/$/, "") || "";

  const filtered = useMemo(() => {
    let items = commitments ?? [];
    if (chamber !== "all") {
      items = items.filter((c) => c.chamber === chamber);
    }
    if (searchText.trim()) {
      const q = searchText.toLowerCase();
      items = items.filter((c) =>
        c.text.toLowerCase().includes(q) ||
        c.speaker.toLowerCase().includes(q) ||
        c.topic.toLowerCase().includes(q)
      );
    }
    return items;
  }, [commitments, chamber, searchText]);

  if (!commitments || commitments.length === 0) {
    return (
      <div style={{ padding: "2rem", textAlign: "center", color: "#9ca3af", fontSize: "0.875rem" }}>
        データが蓄積されると約束事項が表示されます
      </div>
    );
  }

  function buildSessionUrl(c) {
    const [year, month, day] = (c.date ?? "").split("-");
    if (!year) return `${base}/browse`;
    return `${base}/${c.chamber}/${year}/${month}/${day}/${c.sessionSlug}#${c.qaId}`;
  }

  function renderCard(c) {
    return (
      <div
        key={c.id}
        style={{
          background: "#fff",
          border: "1px solid #e5e7eb",
          borderRadius: 8,
          padding: "1rem",
          marginBottom: "0.75rem",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: 4, marginBottom: 6 }}>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            <span style={{ fontSize: 11, background: "#f3f4f6", color: "#374151", padding: "2px 6px", borderRadius: 4 }}>
              {CHAMBER_LABEL[c.chamber] ?? c.chamber}
            </span>
            <span style={{ fontSize: 11, background: "#eff6ff", color: "#2563eb", padding: "2px 6px", borderRadius: 4 }}>
              {c.committee}
            </span>
            <span style={{ fontSize: 11, background: "#fef3c7", color: "#92400e", padding: "2px 6px", borderRadius: 4 }}>
              {c.topic}
            </span>
            <span style={{ fontSize: 11, color: STATUS_COLOR[c.status] ?? "#9ca3af" }}>
              {STATUS_LABEL[c.status] ?? c.status}
            </span>
          </div>
          <span style={{ fontSize: 12, color: "#6b7280", whiteSpace: "nowrap" }}>{c.date}</span>
        </div>
        <p style={{ margin: "0 0 0.5rem", fontSize: "0.9rem", lineHeight: 1.6 }}>{c.text}</p>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 4 }}>
          <span style={{ fontSize: 12, color: "#374151" }}>
            {c.speaker}
            {c.role && <span style={{ color: "#6b7280" }}>（{c.role}）</span>}
          </span>
          <a
            href={buildSessionUrl(c)}
            style={{ fontSize: 12, color: "#2563eb", textDecoration: "none" }}
          >
            出典→
          </a>
        </div>
      </div>
    );
  }

  return (
    <div>
      {/* コントロール */}
      <div style={{ display: "flex", gap: 12, marginBottom: "1rem", flexWrap: "wrap", alignItems: "center" }}>
        <div style={{ display: "flex", gap: 4 }}>
          {[["all", "全体"], ["shugiin", "衆議院"], ["sangiin", "参議院"]].map(([val, label]) => (
            <button
              key={val}
              onClick={() => setChamber(val)}
              style={{
                padding: "4px 12px",
                borderRadius: 4,
                border: "1px solid",
                borderColor: chamber === val ? "#2563eb" : "#d1d5db",
                background: chamber === val ? "#eff6ff" : "#fff",
                color: chamber === val ? "#2563eb" : "#374151",
                fontWeight: chamber === val ? 600 : 400,
                cursor: "pointer",
                fontSize: "0.875rem",
              }}
            >
              {label}
            </button>
          ))}
        </div>
        <input
          type="text"
          placeholder="テキスト検索..."
          value={searchText}
          onChange={(e) => setSearchText(e.target.value)}
          style={{
            padding: "4px 10px",
            borderRadius: 4,
            border: "1px solid #d1d5db",
            fontSize: "0.875rem",
            minWidth: 160,
          }}
        />
        <label style={{ fontSize: "0.875rem", display: "flex", alignItems: "center", gap: 4, cursor: "pointer" }}>
          <input
            type="checkbox"
            checked={groupByTopic}
            onChange={(e) => setGroupByTopic(e.target.checked)}
          />
          トピック別グループ
        </label>
      </div>

      {filtered.length === 0 ? (
        <div style={{ color: "#9ca3af", fontSize: "0.875rem", padding: "1rem 0" }}>
          該当する約束事項がありません
        </div>
      ) : groupByTopic ? (
        (() => {
          const groups = new Map();
          filtered.forEach((c) => {
            const arr = groups.get(c.topic) ?? [];
            arr.push(c);
            groups.set(c.topic, arr);
          });
          return Array.from(groups.entries()).map(([topic, items]) => (
            <div key={topic} style={{ marginBottom: "1.5rem" }}>
              <h3 style={{ fontSize: "0.95rem", margin: "0 0 0.5rem", color: "#374151", borderBottom: "1px solid #e5e7eb", paddingBottom: 4 }}>
                {topic} ({items.length}件)
              </h3>
              {items.map(renderCard)}
            </div>
          ));
        })()
      ) : (
        filtered.map(renderCard)
      )}
    </div>
  );
}
