import { useState } from "react";

function getHeatmapColor(value, max) {
  if (value === 0 || max === 0) return "#f3f4f6";
  const intensity = Math.min(value / max, 1);
  const r = Math.round(239 - intensity * 180);
  const g = Math.round(246 - intensity * 180);
  const b = 255;
  return `rgb(${r}, ${g}, ${b})`;
}

export default function TopicHeatmap({ data }) {
  const [chamber, setChamber] = useState("all");
  const [tooltip, setTooltip] = useState(null);

  if (!data || data.topics.length === 0) {
    return (
      <div style={{ padding: "2rem", textAlign: "center", color: "#9ca3af", fontSize: "0.875rem" }}>
        データが蓄積されるとトピック×委員会ヒートマップが表示されます
      </div>
    );
  }

  // 院フィルタ
  const filteredCommitteeIndices = data.committees
    .map((c, i) => ({ c, i }))
    .filter(({ c }) => {
      if (chamber === "all") return true;
      const chamberCommittees = data.committees_by_chamber?.[chamber] ?? [];
      return chamberCommittees.includes(c);
    });

  const filteredCommittees = filteredCommitteeIndices.map(({ c }) => c);
  const filteredMatrix = data.topics.map((_, topicIdx) =>
    filteredCommitteeIndices.map(({ i }) => data.matrix[topicIdx]?.[i] ?? 0)
  );

  const max = Math.max(1, ...filteredMatrix.flat());

  const base = typeof window !== "undefined"
    ? (document.querySelector("base")?.href?.replace(/\/$/, "") || "")
    : "";

  const CELL_W = 44;
  const CELL_H = 28;
  const LABEL_W = 120;
  const LABEL_H = 80;

  return (
    <div>
      {/* 院フィルタ */}
      <div style={{ marginBottom: "1rem", display: "flex", gap: 8 }}>
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

      {filteredCommittees.length === 0 ? (
        <div style={{ color: "#9ca3af", fontSize: "0.875rem" }}>
          選択した院のデータがありません
        </div>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <div style={{ minWidth: LABEL_W + filteredCommittees.length * CELL_W + 8, display: "inline-block" }}>
            {/* ヘッダー行 — 委員会名（縦書き気味） */}
            <div style={{ display: "flex", marginLeft: LABEL_W }}>
              {filteredCommittees.map((c, ci) => (
                <div
                  key={ci}
                  style={{
                    width: CELL_W,
                    height: LABEL_H,
                    fontSize: 10,
                    color: "#374151",
                    writingMode: "vertical-rl",
                    textOrientation: "mixed",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "flex-end",
                    padding: "4px 4px 2px",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                  }}
                >
                  {c}
                </div>
              ))}
            </div>

            {/* データ行 */}
            {data.topics.map((topic, ti) => (
              <div key={ti} style={{ display: "flex", alignItems: "center" }}>
                {/* トピックラベル */}
                <div
                  style={{
                    width: LABEL_W,
                    fontSize: 11,
                    color: "#374151",
                    paddingRight: 8,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                    flexShrink: 0,
                  }}
                  title={topic}
                >
                  {topic}
                </div>
                {/* セル */}
                {filteredMatrix[ti].map((value, ci) => (
                  <div
                    key={ci}
                    style={{
                      width: CELL_W,
                      height: CELL_H,
                      backgroundColor: getHeatmapColor(value, max),
                      border: "1px solid #e5e7eb",
                      cursor: value > 0 ? "pointer" : "default",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      fontSize: 10,
                      color: value > max * 0.5 ? "#fff" : "#374151",
                      position: "relative",
                    }}
                    title={`${topic} × ${filteredCommittees[ci]}: ${value}件`}
                    onMouseEnter={() => setTooltip({ topic, committee: filteredCommittees[ci], value })}
                    onMouseLeave={() => setTooltip(null)}
                    onClick={() => {
                      if (value > 0) {
                        window.location.href = `${base}/browse?topic=${encodeURIComponent(topic)}&committee=${encodeURIComponent(filteredCommittees[ci])}`;
                      }
                    }}
                  >
                    {value > 0 ? value : ""}
                  </div>
                ))}
              </div>
            ))}
          </div>
        </div>
      )}

      {tooltip && (
        <div style={{
          marginTop: 8,
          padding: "4px 10px",
          background: "#1f2937",
          color: "#fff",
          borderRadius: 4,
          fontSize: 12,
          display: "inline-block",
        }}>
          {tooltip.topic} × {tooltip.committee}: {tooltip.value}件
        </div>
      )}
    </div>
  );
}
