import { dateShort, num } from '@/lib/format';
import type { Session } from '@/lib/types';

/**
 * График оценки отклонения по проверкам (B2). selected — проверка, которая сейчас в чате.
 * width и height задают размер в пикселях: подписи остаются своего размера на любой ширине.
 */
export function ScoreChart({
  sessions,
  selected,
  width = 340,
  height = 132,
}: {
  sessions: Session[];
  selected: string | null;
  width?: number;
  height?: number;
}) {
  const W = width;
  const H = height;
  const left = 34;
  const right = 14;
  const top = 12;
  const bottom = 30;
  const plotW = W - left - right;
  const plotH = H - top - bottom;
  const n = sessions.length;
  const x = (i: number) => (n <= 1 ? left + plotW / 2 : left + (plotW * i) / (n - 1));
  const y = (v: number) => top + plotH * (1 - Math.max(0, Math.min(1, v)));
  const scored = sessions.map((s, i) => ({ s, i })).filter((p) => p.s.anomaly_score !== null);
  const line = scored.map((p) => `${x(p.i).toFixed(1)},${y(p.s.anomaly_score as number).toFixed(1)}`).join(' ');

  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Оценка отклонения по проверкам">
      {[0, 0.5, 1].map((g) => (
        <g key={g}>
          <line
            x1={left}
            x2={W - right}
            y1={y(g)}
            y2={y(g)}
            style={{ stroke: g === 0.5 ? 'var(--tx3)' : 'var(--line)' }}
            strokeDasharray={g === 0.5 ? '4 4' : undefined}
          />
          <text x={left - 8} y={y(g) + 4} textAnchor="end" style={{ fill: 'var(--tx3)', font: '11px var(--mono)' }}>
            {num(g, 1)}
          </text>
        </g>
      ))}
      {scored.length > 1 ? <polyline points={line} fill="none" style={{ stroke: 'var(--tx2)' }} strokeWidth={2} /> : null}
      {sessions.map((s, i) => {
        const cx = x(i);
        const isSel = s.session_id === selected;
        const color = s.status === 'anomaly' ? 'var(--warn)' : 'var(--tx3)';
        return (
          <g key={s.session_id}>
            {isSel ? <line x1={cx} x2={cx} y1={top} y2={top + plotH} style={{ stroke: 'var(--acc)' }} strokeWidth={1} /> : null}
            {s.anomaly_score !== null ? (
              <circle cx={cx} cy={y(s.anomaly_score)} r={isSel ? 6 : 4.5} style={{ fill: color, stroke: 'var(--panel)' }} strokeWidth={2} />
            ) : (
              <g style={{ stroke: 'var(--tx3)' }} strokeWidth={2}>
                <line x1={cx - 4} x2={cx + 4} y1={top + plotH - 9} y2={top + plotH - 1} />
                <line x1={cx - 4} x2={cx + 4} y1={top + plotH - 1} y2={top + plotH - 9} />
              </g>
            )}
            <text
              x={cx}
              y={H - 10}
              textAnchor={n > 1 && i === 0 ? 'start' : n > 1 && i === n - 1 ? 'end' : 'middle'}
              dx={n > 1 && i === 0 ? -8 : n > 1 && i === n - 1 ? 8 : 0}
              style={{ fill: isSel ? 'var(--acc)' : 'var(--tx3)', font: `${isSel ? 600 : 400} 11px var(--mono)` }}
            >
              {dateShort(s.checked_at)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
