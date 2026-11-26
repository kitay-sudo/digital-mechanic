'use client';

import Link from 'next/link';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '@/lib/api';
import { dateTime, vehicleIcon } from '@/lib/format';
import type { Fleet, FleetStatus, VehicleBrief } from '@/lib/types';
import { PriorityBadge, StatusBadge } from './Badges';
import { Icon } from './Icon';
import { ErrorState, Loading } from './States';

const TILES: { key: FleetStatus; label: string; hint: string; cls: string; icon: string }[] = [
  { key: 'ok', label: 'Норма', hint: 'Готовы к работе', cls: '', icon: 'circle-check' },
  { key: 'attention', label: 'Требует внимания', hint: 'Плановый контроль', cls: 't-att', icon: 'alert-triangle' },
  { key: 'quarantine', label: 'Карантин', hint: 'На дефектовку до рейса', cls: 't-q', icon: 'alert-octagon' },
];

function lastTicket(v: VehicleBrief): string | null {
  return v.tickets.length ? v.tickets[v.tickets.length - 1].ticket_id : null;
}

function Row({ v }: { v: VehicleBrief }) {
  const s = v.last_session;
  const ticket = lastTicket(v);
  return (
    <Link href={`/v/${encodeURIComponent(v.vehicle_id)}`} className={`frow s-${v.fleet_status}`}>
      <span>
        <span className="vid">{v.vehicle_id}</span>
        <span className="gno">{v.garage_no}</span>
      </span>
      <span className="d vt">
        <Icon name={vehicleIcon(v.make)} />
        {v.title}
      </span>
      <span className="d m">{v.engine_model}</span>
      <span className="d m">{s ? dateTime(s.checked_at) : '—'}</span>
      <span>{s ? <StatusBadge status={s.status} code={s.anomaly_type} /> : <span className="mut">нет проверок</span>}</span>
      <span className="d">
        {v.priority ? <PriorityBadge priority={v.priority} /> : <span className="mut">{v.needs_recheck ? 'повторить запись' : '—'}</span>}
      </span>
      <span className="d">{ticket ? <span className="m">{ticket}</span> : <span className="mut">—</span>}</span>
      <span className="m2">
        {v.title} · {v.engine_model}
      </span>
      <span className="m2 r">
        {v.priority ? <PriorityBadge priority={v.priority} /> : v.needs_recheck ? 'повторить запись' : s ? dateTime(s.checked_at) : ''}
        {ticket ? ` · ${ticket}` : ''}
      </span>
    </Link>
  );
}

export function FleetView() {
  const [fleet, setFleet] = useState<Fleet | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<FleetStatus | null>(null);
  const [query, setQuery] = useState('');

  const load = useCallback(() => {
    setError(null);
    api
      .fleet()
      .then(setFleet)
      .catch((e: Error) => setError(e.message));
  }, []);

  useEffect(load, [load]);

  const rows = useMemo(() => {
    if (!fleet) return [];
    const q = query.trim().toLowerCase();
    return fleet.vehicles.filter((v) => {
      if (filter && v.fleet_status !== filter) return false;
      if (!q) return true;
      return [v.vehicle_id, v.garage_no, v.title, v.make, v.model ?? '', v.engine_model].some((f) => f.toLowerCase().includes(q));
    });
  }, [fleet, filter, query]);

  if (error) return <ErrorState text={error} onRetry={load} />;
  if (!fleet) return <Loading text="Загружаю парк…" />;

  const { summary } = fleet;

  return (
    <>
      <div className="fbar">
        <div>
          <div className="h1">Парк</div>
        </div>
        <span className="st only-d">
          Сводка главного механика · машин: <span className="m">{summary.total}</span>
        </span>
        <label className="search">
          <Icon name="search" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Госномер, гаражный номер или модель"
            aria-label="Поиск машины"
          />
        </label>
      </div>
      <div className="body">
        <div className="tiles">
          {TILES.map((t) => (
            <button
              key={t.key}
              type="button"
              className={`tile ${t.cls}${filter === t.key ? ' on' : ''}`}
              onClick={() => setFilter(filter === t.key ? null : t.key)}
              aria-pressed={filter === t.key}
            >
              <span className="cnt">{summary[t.key]}</span>
              <span>
                <span className="lbl">{t.label}</span>
                <span className="hint">
                  {t.key === 'attention' && summary.recheck ? `${t.hint} · повторить запись: ${summary.recheck}` : t.hint}
                </span>
              </span>
              <Icon name={t.icon} size="l" />
            </button>
          ))}
        </div>
        <div className="sec" style={{ marginBottom: 8 }}>
          <b>
            <Icon name="list-details" size="s" />
            {filter ? TILES.find((t) => t.key === filter)?.label : 'Все машины'} · {rows.length}
          </b>
          {filter || query ? (
            <button
              type="button"
              className="btn sm"
              onClick={() => {
                setFilter(null);
                setQuery('');
              }}
            >
              <Icon name="x" size="s" />
              Сбросить
            </button>
          ) : (
            <span>сначала те, кому нужна дефектовка</span>
          )}
        </div>
        {rows.length ? (
          <div className="ftable">
            <div className="fhead">
              <span>Госномер, гаражный №</span>
              <span>Машина</span>
              <span>Двигатель</span>
              <span>Последняя проверка</span>
              <span>Результат ML</span>
              <span>Приоритет</span>
              <span>Заявка</span>
            </div>
            {rows.map((v) => (
              <Row key={v.vehicle_id} v={v} />
            ))}
          </div>
        ) : (
          <div className="box center" style={{ minHeight: 200 }}>
            <Icon name="search-off" size="xl" />
            <div className="e1">Ничего не найдено</div>
            <div>Измените поиск или сбросьте фильтр</div>
          </div>
        )}
      </div>
    </>
  );
}
