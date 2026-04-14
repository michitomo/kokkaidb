import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";

export default function MonthlyTrendChart({ data }) {
  if (!data || data.length === 0) {
    return (
      <div style={{ padding: "2rem", textAlign: "center", color: "#9ca3af", fontSize: "0.875rem" }}>
        データが蓄積されると月別トレンドが表示されます
      </div>
    );
  }

  // YYYY-MM → M月 表示
  const formatted = data.map((d) => ({
    ...d,
    label: d.month ? `${parseInt(d.month.slice(5))}月` : d.month,
  }));

  return (
    <ResponsiveContainer width="100%" height={260}>
      <BarChart data={formatted} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
        <XAxis dataKey="label" tick={{ fontSize: 12 }} />
        <YAxis allowDecimals={false} tick={{ fontSize: 12 }} />
        <Tooltip
          formatter={(value, name) => [value, name === "shugiin" ? "衆議院" : "参議院"]}
          labelFormatter={(label) => `${label}`}
        />
        <Legend
          formatter={(value) => (value === "shugiin" ? "衆議院" : "参議院")}
        />
        <Bar dataKey="shugiin" name="shugiin" fill="#3b82f6" stackId="a" />
        <Bar dataKey="sangiin" name="sangiin" fill="#ef4444" stackId="a" />
      </BarChart>
    </ResponsiveContainer>
  );
}
