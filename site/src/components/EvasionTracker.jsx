import { useState, useMemo } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";

export default function EvasionTracker({ data }) {
  const [sortBy, setSortBy] = useState("score"); // "score" | "count"
  const [selectedTopic, setSelectedTopic] = useState("all");
  const [expanded, setExpanded] = useState(null);

  if (!data || data.length === 0) {
    return (
      <div style={{ padding: "2rem", textAlign: "center", color: "#9ca3af", fontSize: "0.875rem" }}>
        答弁データが蓄積されると回避度分析が表示されます
      </div>
    );
  }

  const allTopics = useMemo(() => {
    const set = new Set();
    data.forEach((d) => d.byTopic?.forEach((t) => set.add(t.topic)));
    return Array.from(set).sort();
  }, [data]);

  const filtered = useMemo(() => {
    let items = data.filter((d) => d.totalAnswers > 0);
    if (selectedTopic !== "all") {
      items = items.map((d) => {
        const t = d.byTopic?.find((b) => b.topic === selectedTopic);
        if (!t) return null;
        return { ...d, avgEvasionScore: t.avgScore, totalAnswers: t.count };
      }).filter(Boolean);
    }
    if (sortBy === "score") {
      items = [...items].sort((a, b) => b.avgEvasionScore - a.avgEvasionScore);
    } else {
      items = [...items].sort((a, b) => b.totalAnswers - a.totalAnswers);
    }
    return items.slice(0, 20);
  }, [data, sortBy, selectedTopic]);

  const chartData = filtered.map((d) => ({
    name: d.speaker.length > 6 ? d.speaker.slice(0, 6) + "…" : d.speaker,
    fullName: d.speaker,
    clear: selectedTopic === "all" ? d.clearCount : 0,
    hedging: selectedTopic === "all" ? d.hedgingCount : 0,
    evasive: selectedTopic === "all" ? d.evasiveCount : 0,
    total: d.totalAnswers,
    avg: d.avgEvasionScore,
  }));

  const CustomTooltip = ({ active, payload, label }) => {
    if (!active || !payload?.length) return null;
    const item = filtered.find((d) => {
      const n = d.speaker.length > 6 ? d.speaker.slice(0, 6) + "…" : d.speaker;
      return n === label;
    });
    return (
      <div style={{ background: "#fff", border: "1px solid #e5e7eb", borderRadius: 4, padding: "8px 12px", fontSize: 12 }}>
        <div style={{ fontWeight: 600, marginBottom: 4 }}>{item?.speaker}</div>
        <div style={{ color: "#6b7280" }}>{item?.role}</div>
        {selectedTopic === "all" ? (
          <>
            <div style={{ color: "#16a34a" }}>明確回答: {item?.clearCount}件</div>
            <div style={{ color: "#ca8a04" }}>検討する系: {item?.hedgingCount}件</div>
            <div style={{ color: "#dc2626" }}>回避的: {item?.evasiveCount}件</div>
          </>
        ) : (
          <div>件数: {item?.totalAnswers}</div>
        )}
        <div style={{ marginTop: 4, fontWeight: 600 }}>平均回避度: {(item?.avgEvasionScore * 100).toFixed(0)}%</div>
      </div>
    );
  };

  return (
    <div>
      {/* コントロール */}
      <div style={{ display: "flex", gap: 12, marginBottom: "1rem", flexWrap: "wrap", alignItems: "center" }}>
        <div style={{ display: "flex", gap: 4 }}>
          {[["score", "回避度順"], ["count", "件数順"]].map(([val, label]) => (
            <button
              key={val}
              onClick={() => setSortBy(val)}
              style={{
                padding: "4px 12px",
                borderRadius: 4,
                border: "1px solid",
                borderColor: sortBy === val ? "#2563eb" : "#d1d5db",
                background: sortBy === val ? "#eff6ff" : "#fff",
                color: sortBy === val ? "#2563eb" : "#374151",
                fontWeight: sortBy === val ? 600 : 400,
                cursor: "pointer",
                fontSize: "0.875rem",
              }}
            >
              {label}
            </button>
          ))}
        </div>
        {allTopics.length > 0 && (
          <select
            value={selectedTopic}
            onChange={(e) => setSelectedTopic(e.target.value)}
            style={{ padding: "4px 8px", borderRadius: 4, border: "1px solid #d1d5db", fontSize: "0.875rem" }}
          >
            <option value="all">全テーマ</option>
            {allTopics.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        )}
      </div>

      <ResponsiveContainer width="100%" height={Math.max(200, filtered.length * 36)}>
        <BarChart data={chartData} layout="vertical" margin={{ top: 0, right: 40, left: 8, bottom: 0 }}>
          <XAxis type="number" tick={{ fontSize: 11 }} />
          <YAxis type="category" dataKey="name" tick={{ fontSize: 11 }} width={72} />
          <Tooltip content={<CustomTooltip />} />
          {selectedTopic === "all" ? (
            <>
              <Legend
                formatter={(value) => ({ clear: "明確", hedging: "検討する系", evasive: "回避的" }[value] ?? value)}
              />
              <Bar dataKey="clear" name="clear" stackId="a" fill="#16a34a" />
              <Bar dataKey="hedging" name="hedging" stackId="a" fill="#ca8a04" />
              <Bar dataKey="evasive" name="evasive" stackId="a" fill="#dc2626" />
            </>
          ) : (
            <Bar dataKey="total" name="件数" fill="#6366f1" />
          )}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
