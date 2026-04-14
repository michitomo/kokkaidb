import { useState } from "react";

const COLORS = ["#ebedf0", "#9be9a8", "#40c463", "#216e39"];
const DAY_LABELS = ["日", "月", "火", "水", "木", "金", "土"];
const MONTH_LABELS = ["1月", "2月", "3月", "4月", "5月", "6月", "7月", "8月", "9月", "10月", "11月", "12月"];

function getColor(count) {
  if (count === 0) return COLORS[0];
  if (count === 1) return COLORS[1];
  if (count <= 3) return COLORS[2];
  return COLORS[3];
}

function buildWeeks(data) {
  // 直近52週 + 現在の週
  const today = new Date();
  // 週の始まり（日曜）を基準に52週前
  const endSunday = new Date(today);
  endSunday.setDate(today.getDate() - today.getDay()); // 今週の日曜
  const startDate = new Date(endSunday);
  startDate.setDate(endSunday.getDate() - 52 * 7);

  const weeks = [];
  let current = new Date(startDate);
  // 日曜始まりになるよう調整（すでに日曜のはず）
  while (current <= today) {
    const week = [];
    for (let d = 0; d < 7; d++) {
      const dateStr = current.toISOString().slice(0, 10);
      const entry = data[dateStr] ?? { count: 0, shugiin: 0, sangiin: 0 };
      week.push({ date: dateStr, ...entry, dayOfWeek: d, isFuture: current > today });
      current.setDate(current.getDate() + 1);
    }
    weeks.push(week);
  }
  return weeks;
}

function getMonthPositions(weeks) {
  const positions = [];
  let lastMonth = null;
  weeks.forEach((week, i) => {
    const month = week[0]?.date?.slice(5, 7);
    if (month && month !== lastMonth) {
      positions.push({ month: parseInt(month) - 1, col: i });
      lastMonth = month;
    }
  });
  return positions;
}

export default function SessionCalendar({ data = {} }) {
  const [tooltip, setTooltip] = useState(null);
  const base = typeof window !== "undefined"
    ? (document.querySelector("base")?.href?.replace(/\/$/, "") || "")
    : "";

  const weeks = buildWeeks(data);
  const monthPositions = getMonthPositions(weeks);
  const CELL = 13;
  const GAP = 2;

  return (
    <div>
      <div style={{ overflowX: "auto", paddingBottom: "0.5rem" }}>
        {/* Month labels */}
        <div style={{ display: "flex", paddingLeft: 28, marginBottom: 2, minWidth: weeks.length * (CELL + GAP) + 28 }}>
          {monthPositions.map(({ month, col }, i) => (
            <span
              key={i}
              style={{
                position: "relative",
                left: col * (CELL + GAP),
                fontSize: 10,
                color: "#6b7280",
                marginRight: 0,
                whiteSpace: "nowrap",
              }}
            >
              {MONTH_LABELS[month]}
            </span>
          ))}
        </div>
        <div style={{ display: "flex", gap: GAP, alignItems: "flex-start" }}>
          {/* Day labels */}
          <div style={{ display: "flex", flexDirection: "column", gap: GAP, marginRight: 4, paddingTop: 0 }}>
            {DAY_LABELS.map((d, i) => (
              <div key={i} style={{ height: CELL, fontSize: 9, color: "#9ca3af", lineHeight: `${CELL}px`, textAlign: "right" }}>
                {i % 2 === 1 ? d : ""}
              </div>
            ))}
          </div>
          {/* Grid */}
          {weeks.map((week, wi) => (
            <div key={wi} style={{ display: "flex", flexDirection: "column", gap: GAP }}>
              {week.map((cell) => (
                <div
                  key={cell.date}
                  style={{
                    width: CELL,
                    height: CELL,
                    borderRadius: 2,
                    backgroundColor: cell.isFuture ? "transparent" : getColor(cell.count),
                    cursor: cell.count > 0 ? "pointer" : "default",
                    position: "relative",
                  }}
                  title={`${cell.date}: ${cell.count}件（衆${cell.shugiin} 参${cell.sangiin}）`}
                  onMouseEnter={() => setTooltip(cell)}
                  onMouseLeave={() => setTooltip(null)}
                  onClick={() => {
                    if (cell.count > 0) {
                      window.location.href = `${base}/browse?date=${cell.date}`;
                    }
                  }}
                />
              ))}
            </div>
          ))}
        </div>
      </div>
      {/* Legend */}
      <div style={{ display: "flex", alignItems: "center", gap: 4, marginTop: 8, fontSize: 11, color: "#6b7280" }}>
        <span>少</span>
        {COLORS.map((c, i) => (
          <div key={i} style={{ width: 12, height: 12, borderRadius: 2, backgroundColor: c }} />
        ))}
        <span>多</span>
      </div>
      {tooltip && (
        <div style={{
          marginTop: 8,
          padding: "4px 8px",
          background: "#1f2937",
          color: "#fff",
          borderRadius: 4,
          fontSize: 12,
          display: "inline-block",
        }}>
          {tooltip.date}: {tooltip.count}件（衆{tooltip.shugiin} 参{tooltip.sangiin}）
        </div>
      )}
    </div>
  );
}
