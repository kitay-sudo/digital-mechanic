'use client';

import Link from 'next/link';
import { PRIORITY_LABEL, dateShort, dateTime, num, timeShort, vehicleIcon } from '@/lib/format';
import type { ManualTarget, Session, VehicleDetail } from '@/lib/types';
import { PriorityBadge, StatusBadge } from './Badges';
import { Icon } from './Icon';

const TREND_ICON = { rising: 'trending-up', falling: 'trending-down', stable: 'arrows-right', none: 'minus' } as const;

/** График оценки отклонения по проверкам (B2). */
function ScoreChart({ sessions, selected }: { sessions: Session[]; selected: string | null }) {
  const W = 340;
  const H = 132;
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

export function VehiclePanel({
  vehicle,
  sessionId,
  onSelect,
  onOpenManual,
  open,
  onClose,
  busy,
}: {
  vehicle: VehicleDetail;
  sessionId: string | null;
  onSelect: (id: string) => void;
  onOpenManual: (t: ManualTarget) => void;
  open: boolean;
  onClose: () => void;
  busy: boolean;
}) {
  // Новые проверки сверху: механику нужна последняя
  const sessions = [...vehicle.sessions].reverse();

  return (
    <aside className={`col side${open ? ' open' : ''}`}>
      <div className="handle">
        <i />
      </div>
      <div className="hdr">
        <Link href="/" className="hb only-d" aria-label="Назад к парку" title="К парку">
          <Icon name="arrow-left" />
        </Link>
        <div className="grow">
          <div className="h1">
            {vehicle.title} <span className="m">{vehicle.vehicle_id}</span>
          </div>
          <div className="sub m">
            {vehicle.garage_no} · {vehicle.engine_model}
          </div>
        </div>
        <div className="rt only-m">
          <button type="button" className="hb" onClick={onClose} aria-label="Закрыть">
            <Icon name="x" />
          </button>
        </div>
      </div>

      <div className="body">
        <div className="blk">
          <div className="sec">
            <b>
              <Icon name={vehicleIcon(vehicle.make)} size="s" />
              Машина
            </b>
            {vehicle.priority ? <PriorityBadge priority={vehicle.priority} long /> : null}
          </div>
          <div className="info">
            <div>Модель</div>
            <div>
              {vehicle.title}, {vehicle.vehicle_type}
            </div>
            <div>Двигатель</div>
            <div className="m">
              {vehicle.engine_model}, {vehicle.fuel}
            </div>
            <div>Руководства</div>
            <div>
              <div className="mlist">
                {vehicle.manuals.length ? (
                  vehicle.manuals.map((m) => (
                    <button
                      key={m.manual_id}
                      type="button"
                      className="src"
                      onClick={() => onOpenManual({ manual_id: m.manual_id, page: 1, short: m.short })}
                      title={`${m.designation}. ${m.title}. Страниц: ${m.pages}`}
                    >
                      <Icon name="book-2" size="s" />
                      {m.short}
                    </button>
                  ))
                ) : (
                  <span className="mut">не подключены</span>
                )}
              </div>
            </div>
          </div>
        </div>

        <div className="blk">
          <div className="sec">
            <b>
              <Icon name="history" size="s" />
              Проверки
            </b>
            <span>выберите для разбора</span>
          </div>
          <div className="slist" role="radiogroup" aria-label="Проверки машины">
            {sessions.map((s) => (
              <button
                key={s.session_id}
                type="button"
                role="radio"
                aria-checked={s.session_id === sessionId}
                className={`srow${s.session_id === sessionId ? ' cur' : ''}`}
                onClick={() => onSelect(s.session_id)}
                disabled={busy}
              >
                <span className="radio" />
                <span className="sbody">
                  <span className="sline">
                    <span className="m">{s.session_id}</span>
                    <span className="when">
                      {s.ticket_id ? `${s.ticket_id} · ` : ''}
                      {dateShort(s.checked_at)} {timeShort(s.checked_at)}
                    </span>
                  </span>
                  <span className="sline">
                    <StatusBadge status={s.status} code={s.anomaly_type} />
                    <span className="m">{num(s.anomaly_score)}</span>
                  </span>
                </span>
              </button>
            ))}
            {sessions.length === 0 ? <div className="trow mut">Проверок нет</div> : null}
          </div>
        </div>

        <div className="blk">
          <div className="sec">
            <b>
              <Icon name="chart-line" size="s" />
              Оценка отклонения
            </b>
            <span>пунктир: порог 0,5</span>
          </div>
          <div className="chart">
            <ScoreChart sessions={vehicle.sessions} selected={sessionId} />
            <div className="cap">
              <Icon name={TREND_ICON[vehicle.trend.direction]} size="s" />
              {vehicle.trend.text}
            </div>
          </div>
        </div>

        <div className="blk">
          <div className="sec">
            <b>
              <Icon name="clipboard-list" size="s" />
              Заявки по машине
            </b>
            <span className="m">{vehicle.tickets.length}</span>
          </div>
          <div className="box">
            {vehicle.tickets.length ? (
              vehicle.tickets.map((t) => (
                <div className="trow" key={t.ticket_id} title={t.conclusion}>
                  <Icon name="clipboard-check" className="mut" />
                  <span>
                    <span className="m">{t.ticket_id}</span> · {t.anomaly_type} · {PRIORITY_LABEL[t.urgency]}
                    <span className="when">
                      {t.session_id} · {dateTime(t.created_at)}
                    </span>
                  </span>
                </div>
              ))
            ) : (
              <div className="trow mut">Заявок пока нет</div>
            )}
          </div>
        </div>
      </div>
    </aside>
  );
}
