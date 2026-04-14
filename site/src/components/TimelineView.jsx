import { useState, useRef, useEffect } from "react";

const ROLE_COLORS = {
  委員長: "#9ca3af",
  議長: "#9ca3af",
  質疑者: "#3b82f6",
  答弁者: "#ef4444",
  大臣: "#ef4444",
  副大臣: "#f97316",
  政府参考人: "#22c55e",
  参考人: "#a78bfa",
};

const DEFAULT_COLOR = "#6b7280";

function getRoleColor(role) {
  if (!role) return DEFAULT_COLOR;
  for (const [key, color] of Object.entries(ROLE_COLORS)) {
    if (role.includes(key)) return color;
  }
  return DEFAULT_COLOR;
}

function formatTime(seconds) {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}`;
  return `${m}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;
}

const SVG_HEIGHT = 80;
const BAR_Y = 24;
const BAR_H = 36;
const AXIS_Y = 16;
const MIN_PX_WIDTH = 2;

export default function TimelineView({ segments, qaConnections, totalDurationSeconds }) {
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
  const MIN_W = MIN_PX_WIDTH;

  // 話者→色マップ
  const speakerColors = new Map();
  segments.forEach((seg) => {
    if (!speakerColors.has(seg.speaker)) {
      speakerColors.set(seg.speaker, getRoleColor(seg.role));
    }
  });

  // 時間軸ティック（10分ごと）
  const tickInterval = Math.ceil(dur / 10 / 300) * 300; // 5分単位
  const ticks = [];
  for (let t = 0; t <= dur; t += tickInterval) {
    ticks.push(t);
  }

  return (
    <div>
      {/* 凡例 */}
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginBottom: "0.75rem", fontSize: 12 }}>
        {Array.from(new Map(segments.map((s) => [s.role, getRoleColor(s.role)]))).map(([role, color]) => (
          <span key={role} style={{ display: "flex", alignItems: "center", gap: 4 }}>
            <span style={{ width: 12, height: 12, borderRadius: 2, backgroundColor: color, display: "inline-block" }} />
            {role}
          </span>
        ))}
        <label style={{ display: "flex", alignItems: "center", gap: 4, cursor: "pointer", marginLeft: "auto" }}>
          <input type="checkbox" checked={showQA} onChange={(e) => setShowQA(e.target.checked)} />
          <span>Q&Aコネクタ</span>
        </label>
      </div>

      {/* SVGタイムライン */}
      <div ref={containerRef} style={{ overflowX: "auto" }}>
        <svg
          width={Math.max(svgWidth, 600)}
          height={SVG_HEIGHT + (showQA && qaConnections?.length ? 40 : 0)}
          style={{ display: "block" }}
        >
          {/* 時間軸 */}
          {ticks.map((t) => (
            <g key={t}>
              <line
                x1={xScale(t)} y1={AXIS_Y + 2}
                x2={xScale(t)} y2={BAR_Y + BAR_H}
                stroke="#e5e7eb" strokeWidth={1}
              />
              <text
                x={xScale(t)} y={AXIS_Y}
                fontSize={10} fill="#9ca3af" textAnchor="middle"
              >
                {formatTime(t)}
              </text>
            </g>
          ))}

          {/* 発言バー */}
          {segments.map((seg) => {
            const x = xScale(seg.startSeconds);
            const w = Math.max(MIN_W, xScale(seg.endSeconds) - xScale(seg.startSeconds));
            const color = getRoleColor(seg.role);
            const isSelected = selectedSeg?.segmentIndex === seg.segmentIndex;
            return (
              <g key={seg.segmentIndex}>
                <rect
                  x={x} y={BAR_Y}
                  width={w} height={BAR_H}
                  fill={color}
                  opacity={isSelected ? 1 : 0.75}
                  stroke={isSelected ? "#111" : "none"}
                  strokeWidth={isSelected ? 2 : 0}
                  style={{ cursor: "pointer" }}
                  onClick={() => setSelectedSeg(isSelected ? null : seg)}
                  onMouseEnter={() => setTooltip({ seg, x, y: BAR_Y })}
                  onMouseLeave={() => setTooltip(null)}
                />
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
                x={Math.min(tooltip.x, svgWidth - 180)}
                y={BAR_Y + BAR_H + 4}
                width={176}
                height={44}
                rx={4}
                fill="#1f2937"
                opacity={0.9}
              />
              <text
                x={Math.min(tooltip.x + 8, svgWidth - 172)}
                y={BAR_Y + BAR_H + 18}
                fontSize={11}
                fill="#fff"
              >
                {tooltip.seg.speaker}（{tooltip.seg.role}）
              </text>
              <text
                x={Math.min(tooltip.x + 8, svgWidth - 172)}
                y={BAR_Y + BAR_H + 34}
                fontSize={10}
                fill="#d1d5db"
              >
                {formatTime(tooltip.seg.startSeconds)}〜{formatTime(tooltip.seg.endSeconds)}
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
            <span style={{ color: "#6b7280" }}>{selectedSeg.role} • {formatTime(selectedSeg.startSeconds)}〜{formatTime(selectedSeg.endSeconds)}</span>
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
