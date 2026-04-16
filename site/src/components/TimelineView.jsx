import { useState, useRef, useEffect } from "react";

// 発言者ごとの色パレット（見分けやすい色を順番に割り当て）
const SPEAKER_PALETTE = [
  "#3b82f6", // blue
  "#ef4444", // red
  "#22c55e", // green
  "#f59e0b", // amber
  "#8b5cf6", // violet
  "#ec4899", // pink
  "#14b8a6", // teal
  "#f97316", // orange
  "#6366f1", // indigo
  "#84cc16", // lime
  "#06b6d4", // cyan
  "#e11d48", // rose
];

// 委員長・議長は常にグレー
const CHAIR_ROLES = ["委員長", "議長", "副議長"];

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

  // 発言者→色マップ（委員長はグレー、それ以外はパレットから順番に割り当て）
  const speakerColorMap = new Map();
  let colorIdx = 0;
  segments.forEach((seg) => {
    if (!speakerColorMap.has(seg.speaker)) {
      const isChair = CHAIR_ROLES.some((r) => (seg.role || "").includes(r));
      if (isChair) {
        speakerColorMap.set(seg.speaker, "#9ca3af");
      } else {
        speakerColorMap.set(seg.speaker, SPEAKER_PALETTE[colorIdx % SPEAKER_PALETTE.length]);
        colorIdx++;
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
      {/* 凡例 */}
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: "0.75rem", fontSize: 12 }}>
        {Array.from(speakerColorMap.entries()).map(([speaker, color]) => (
          <span key={speaker} style={{ display: "flex", alignItems: "center", gap: 4 }}>
            <span style={{ width: 10, height: 10, borderRadius: 2, backgroundColor: color, display: "inline-block" }} />
            {speaker}
          </span>
        ))}
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
                x={Math.min(tooltip.x, svgWidth - 200)}
                y={BAR_Y + BAR_H + 6}
                width={196}
                height={48}
                rx={6}
                fill="#1f2937"
                opacity={0.95}
              />
              <text
                x={Math.min(tooltip.x + 10, svgWidth - 190)}
                y={BAR_Y + BAR_H + 24}
                fontSize={12}
                fontWeight={600}
                fill="#fff"
              >
                {tooltip.seg.speaker}
              </text>
              <text
                x={Math.min(tooltip.x + 10, svgWidth - 190)}
                y={BAR_Y + BAR_H + 40}
                fontSize={10}
                fill="#d1d5db"
              >
                {tooltip.seg.role} • {formatTimeRange(tooltip.seg.startSeconds, tooltip.seg.endSeconds)}
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
