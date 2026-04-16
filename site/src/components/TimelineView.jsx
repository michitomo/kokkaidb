import { useState, useRef, useEffect } from "react";

// 政党・会派カラーマップ（NHK選挙報道準拠）
// affiliation文字列にキーワードが含まれていればマッチ
const PARTY_COLORS = [
  { keyword: "自由民主党",   color: "#009933", label: "自民" },
  { keyword: "立憲民主党",   color: "#003399", label: "立憲" },
  { keyword: "チームみらい", color: "#7BDDC9", label: "チームみらい" },
  { keyword: "日本維新の会", color: "#82B52A", label: "維新" },
  { keyword: "公明党",       color: "#E5007F", label: "公明" },
  { keyword: "日本共産党",   color: "#CC0000", label: "共産" },
  { keyword: "国民民主党",   color: "#F39800", label: "国民" },
  { keyword: "れいわ新選組", color: "#ED2885", label: "れいわ" },
  { keyword: "社会民主党",   color: "#2EA9DF", label: "社民" },
  { keyword: "参政党",       color: "#C24E00", label: "参政" },
  { keyword: "教育無償化",   color: "#00A98F", label: "教育" },
  { keyword: "中道改革連合", color: "#7B68A0", label: "中道改革" },
  { keyword: "NHK党",        color: "#FFD700", label: "NHK党" },
  { keyword: "無所属",       color: "#999999", label: "無所属" },
];

// 政府・議長等のロール（グレー系で表示）
const GOV_COLOR = "#b0b8c4";
const CHAIR_COLOR = "#9ca3af";

// affiliationから政党カラーを解決
function resolvePartyColor(affiliation, role) {
  // 政党マッチを最優先（affiliationに政党名があればそれを使う）
  for (const p of PARTY_COLORS) {
    if (affiliation.includes(p.keyword)) {
      return { color: p.color, label: p.label };
    }
  }
  // 委員長・議長
  if (/委員長|議長|副議長/.test(affiliation) || /委員長|議長|副議長/.test(role)) {
    return { color: CHAIR_COLOR, label: null };
  }
  // 大臣・副大臣・政務官・政府参考人・参考人・公述人・事務総長
  if (/大臣|政務官|政府参考人|参考人|公述人|事務総長/.test(affiliation) || /大臣|政務官|政府参考人|参考人|公述人/.test(role)) {
    return { color: GOV_COLOR, label: null };
  }
  // フォールバック
  return { color: "#CCCCCC", label: null };
}

// 未使用のフォールバックパレット（政党情報なしの場合）
const FALLBACK_PALETTE = [
  "#3b82f6", "#ef4444", "#22c55e", "#f59e0b",
  "#8b5cf6", "#ec4899", "#14b8a6", "#f97316",
];

function formatTime(seconds) {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}`;
  return `${m}分`;
}

function formatTimeRange(start, end) {
  const fmt = (s) => {
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = Math.floor(s % 60);
    if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
    return `${m}:${String(sec).padStart(2, "0")}`;
  };
  return `${fmt(start)}〜${fmt(end)}`;
}

const SVG_HEIGHT = 100;
const BAR_Y = 28;
const BAR_H = 40;
const LABEL_Y = BAR_Y + BAR_H + 14;
const MIN_PX_WIDTH = 4;

export default function TimelineView({ segments, qaConnections, totalDurationSeconds, onSpeakerSelect }) {
  const [selectedSeg, setSelectedSeg] = useState(null);
  const [showQA, setShowQA] = useState(false);
  const [tooltip, setTooltip] = useState(null);
  const containerRef = useRef(null);
  const [svgWidth, setSvgWidth] = useState(900);

  useEffect(() => {
    const obs = new ResizeObserver((entries) => {
      setSvgWidth(entries[0].contentRect.width || 900);
    });
    if (containerRef.current) obs.observe(containerRef.current);
    return () => obs.disconnect();
  }, []);

  if (!segments || segments.length === 0 || !totalDurationSeconds) {
    return (
      <div style={{ padding: "1rem", color: "#9ca3af", fontSize: "0.875rem" }}>
        タイムラインデータがありません
      </div>
    );
  }

  const dur = totalDurationSeconds || 1;
  const xScale = (s) => (s / dur) * svgWidth;

  // 発言者→色マップ（政党・会派ベース）
  const speakerColorMap = new Map();
  // 凡例用: 政党ラベル→色（重複排除・順序保持）
  const partyLegend = new Map();
  let fallbackIdx = 0;
  segments.forEach((seg) => {
    if (!speakerColorMap.has(seg.speaker)) {
      const affiliation = seg.affiliation || "";
      const role = seg.role || "";
      const resolved = resolvePartyColor(affiliation, role);
      if (resolved.color === "#CCCCCC" && !affiliation) {
        // affiliationなし: フォールバックパレット
        speakerColorMap.set(seg.speaker, FALLBACK_PALETTE[fallbackIdx % FALLBACK_PALETTE.length]);
        fallbackIdx++;
      } else {
        speakerColorMap.set(seg.speaker, resolved.color);
      }
      // 凡例に政党を追加
      if (resolved.label && !partyLegend.has(resolved.label)) {
        partyLegend.set(resolved.label, resolved.color);
      }
    }
  });

  // 時間軸ティック
  const tickInterval = Math.max(300, Math.ceil(dur / 8 / 300) * 300);
  const ticks = [];
  for (let t = 0; t <= dur; t += tickInterval) {
    ticks.push(t);
  }

  // ラベル表示に必要な高さ
  const hasLabels = true;
  const extraH = hasLabels ? 20 : 0;
  const qaExtraH = showQA && qaConnections?.length ? 40 : 0;
  const totalH = SVG_HEIGHT + extraH + qaExtraH;

  return (
    <div>
      {/* 凡例（政党・会派ベース） */}
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: "0.75rem", fontSize: 12 }}>
        {Array.from(partyLegend.entries()).map(([label, color]) => (
          <span key={label} style={{ display: "flex", alignItems: "center", gap: 4 }}>
            <span style={{ width: 10, height: 10, borderRadius: 2, backgroundColor: color, display: "inline-block" }} />
            {label}
          </span>
        ))}
        <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <span style={{ width: 10, height: 10, borderRadius: 2, backgroundColor: GOV_COLOR, display: "inline-block" }} />
          政府
        </span>
        <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <span style={{ width: 10, height: 10, borderRadius: 2, backgroundColor: CHAIR_COLOR, display: "inline-block" }} />
          委員長・議長
        </span>
        {qaConnections?.length > 0 && (
          <label style={{ display: "flex", alignItems: "center", gap: 4, cursor: "pointer", marginLeft: "auto" }}>
            <input type="checkbox" checked={showQA} onChange={(e) => setShowQA(e.target.checked)} />
            <span>Q&Aコネクタ</span>
          </label>
        )}
      </div>

      {/* SVGタイムライン */}
      <div ref={containerRef} style={{ overflowX: "auto" }}>
        <svg
          width={Math.max(svgWidth, 600)}
          height={totalH}
          style={{ display: "block" }}
        >
          {/* 時間軸 */}
          {ticks.map((t) => (
            <g key={t}>
              <line
                x1={xScale(t)} y1={20}
                x2={xScale(t)} y2={BAR_Y + BAR_H}
                stroke="#e5e7eb" strokeWidth={1}
              />
              <text
                x={xScale(t)} y={14}
                fontSize={10} fill="#9ca3af" textAnchor="middle"
              >
                {formatTime(t)}
              </text>
            </g>
          ))}

          {/* 発言バー */}
          {segments.map((seg) => {
            const x = xScale(seg.startSeconds);
            const rawW = xScale(seg.endSeconds) - x;
            const w = Math.max(MIN_PX_WIDTH, rawW);
            const color = speakerColorMap.get(seg.speaker) || "#6b7280";
            const isSelected = selectedSeg?.segmentIndex === seg.segmentIndex;

            // バー内に名前が入るか
            const labelFits = rawW > 50;
            // 短い名前を生成（姓のみ）
            const shortName = seg.speaker.length > 3 ? seg.speaker.slice(0, 3) : seg.speaker;

            return (
              <g key={seg.segmentIndex}>
                <rect
                  x={x} y={BAR_Y}
                  width={w} height={BAR_H}
                  fill={color}
                  opacity={isSelected ? 1 : 0.8}
                  rx={3}
                  stroke={isSelected ? "#111" : "#fff"}
                  strokeWidth={isSelected ? 2 : 1}
                  style={{ cursor: "pointer" }}
                  onClick={() => {
                    const next = isSelected ? null : seg;
                    setSelectedSeg(next);
                    // Astro側フィルタに通知
                    window.dispatchEvent(new CustomEvent('timeline-speaker-select', {
                      detail: { speaker: next ? next.speaker : null },
                    }));
                  }}
                  onMouseEnter={() => setTooltip({ seg, x, y: BAR_Y })}
                  onMouseLeave={() => setTooltip(null)}
                />
                {/* バー内ラベル */}
                {labelFits && (
                  <text
                    x={x + w / 2}
                    y={BAR_Y + BAR_H / 2 + 4}
                    fontSize={11}
                    fontWeight={600}
                    fill="#fff"
                    textAnchor="middle"
                    pointerEvents="none"
                    style={{ textShadow: "0 1px 2px rgba(0,0,0,0.3)" }}
                  >
                    {shortName}
                  </text>
                )}
              </g>
            );
          })}

          {/* Q&Aコネクタ（アーチ線） */}
          {showQA && qaConnections?.map((qa) => {
            const x1 = xScale(qa.questionStart);
            const x2 = xScale(qa.answerStart);
            const mid = (x1 + x2) / 2;
            const archH = 20;
            return (
              <path
                key={qa.qaId}
                d={`M ${x1} ${BAR_Y} Q ${mid} ${BAR_Y - archH} ${x2} ${BAR_Y}`}
                fill="none"
                stroke="#f59e0b"
                strokeWidth={1.5}
                opacity={0.7}
              />
            );
          })}

          {/* ツールチップ */}
          {tooltip && (
            <g>
              <rect
                x={Math.min(tooltip.x, svgWidth - 260)}
                y={BAR_Y + BAR_H + 6}
                width={250}
                height={48}
                rx={6}
                fill="#1f2937"
                opacity={0.95}
              />
              <text
                x={Math.min(tooltip.x + 10, svgWidth - 250)}
                y={BAR_Y + BAR_H + 24}
                fontSize={12}
                fontWeight={600}
                fill="#fff"
              >
                {tooltip.seg.speaker}
              </text>
              <text
                x={Math.min(tooltip.x + 10, svgWidth - 250)}
                y={BAR_Y + BAR_H + 40}
                fontSize={10}
                fill="#d1d5db"
              >
                {tooltip.seg.affiliation ? `${tooltip.seg.affiliation} • ` : tooltip.seg.role ? `${tooltip.seg.role} • ` : ""}{formatTimeRange(tooltip.seg.startSeconds, tooltip.seg.endSeconds)}
              </text>
            </g>
          )}
        </svg>
      </div>

      {/* 選択された発言の詳細 */}
      {selectedSeg && (
        <div style={{
          marginTop: "0.75rem",
          padding: "0.75rem 1rem",
          background: "#f9fafb",
          border: "1px solid #e5e7eb",
          borderRadius: 6,
          fontSize: "0.875rem",
        }}>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
            <strong>{selectedSeg.speaker}</strong>
            <span style={{ color: "#6b7280" }}>
              {selectedSeg.role} • {formatTimeRange(selectedSeg.startSeconds, selectedSeg.endSeconds)}
              {selectedSeg.utteranceCount > 1 && ` • ${selectedSeg.utteranceCount}発言`}
            </span>
          </div>
          {selectedSeg.videoUrl && (
            <a href={selectedSeg.videoUrl} target="_blank" rel="noopener" style={{ fontSize: 12, color: "#2563eb" }}>
              動画で確認 →
            </a>
          )}
        </div>
      )}
    </div>
  );
}
