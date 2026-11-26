'use client';

import Link from 'next/link';
import { useCallback, useEffect, useState } from 'react';
import { api } from '@/lib/api';
import { PRIORITY_LABEL, QUALITY_LABEL, dateTime, num } from '@/lib/format';
import type { Session, Ticket, VehicleDetail } from '@/lib/types';
import { PriorityBadge, StatusBadge } from './Badges';
import { Icon } from './Icon';
import { ScoreChart } from './ScoreChart';
import { ErrorState, Loading } from './States';

export type HistoryTab = 'checks' | 'tickets';

const TREND_ICON = { rising: 'trending-up', falling: 'trending-down', stable: 'arrows-right', none: 'minus' } as const;

/** Адрес чата машины. Проверка в адресе выбирает, что разбирать в чате. */
export function chatHref(vehicleId: string, sessionId?: string | null): string {
  const base = `/v/${encodeURIComponent(vehicleId)}`;
  return sessionId ? `${base}?session=${encodeURIComponent(sessionId)}` : base;
}

/** Адрес истории машины. Проверка из чата едет в адресе, чтобы кнопка «В чат» вернула к ней же. */
export function historyHref(vehicleId: string, tab: HistoryTab, sessionId?: string | null): string {
  const base = `/v/${encodeURIComponent(vehicleId)}/${tab}`;
  return sessionId ? `${base}?session=${encodeURIComponent(sessionId)}` : base;
}

function CheckRow({ vehicleId, s, current }: { vehicleId: string; s: Session; current: boolean }) {
  const flawed = s.signal_quality !== 'good';
  return (
    <Link
      href={chatHref(vehicleId, s.session_id)}
      className={`frow${s.status === 'anomaly' ? ' s-attention' : ''}${current ? ' cur' : ''}`}
    >
      <span>
        <span className="vid">{s.session_id}</span>
        {current ? <span className="tag">в чате</span> : null}
      </span>
      <span className="d m">{dateTime(s.checked_at)}</span>
      <span className="res">
        <StatusBadge status={s.status} code={s.anomaly_type} />
        {s.anomaly_title ? <span className="only-d sub2" title={s.anomaly_title}>{s.anomaly_title}</span> : null}
      </span>
      <span className="d m">{num(s.anomaly_score)}</span>
      <span className="d m cf">{num(s.confidence)}</span>
      <span className={`d${s.signal_quality === 'bad' ? ' c-h' : flawed ? ' c-m' : ''}`}>{QUALITY_LABEL[s.signal_quality]}</span>
      <span className="d">{s.ticket_id ? <span className="m">{s.ticket_id}</span> : <span className="mut">—</span>}</span>
      {/* Телефон и планшет: дата под номером, оценка под результатом, редкие пометки отдельной строкой */}
      <span className="m2 m">{dateTime(s.checked_at)}</span>
      <span className="m2 r">
        {s.anomaly_score !== null ? (
          <>
            оценка <b className="m">{num(s.anomaly_score)}</b>
          </>
        ) : null}
      </span>
      {flawed || s.ticket_id ? (
        <span className="m2 ex">
          {flawed ? (
            <span className={s.signal_quality === 'bad' ? 'c-h' : 'c-m'}>
              <Icon name="alert-triangle" size="s" />
              {s.signal_quality === 'bad' ? 'плохая запись' : 'запись с помехами'}
            </span>
          ) : null}
          {s.ticket_id ? (
            <span>
              <Icon name="clipboard-check" size="s" />
              заявка <b className="m">{s.ticket_id}</b>
            </span>
          ) : null}
        </span>
      ) : null}
    </Link>
  );
}

function TicketRow({ vehicleId, t }: { vehicleId: string; t: Ticket }) {
  return (
    <details className="trec">
      <summary className="frow">
        <span>
          <Icon name="chevron-right" className="chev" />
          <span className="vid">{t.ticket_id}</span>
        </span>
        <span className="d m">{dateTime(t.created_at)}</span>
        <span className="d m">{t.session_id}</span>
        <span className="d m">{t.anomaly_type}</span>
        <span className="res">
          <PriorityBadge priority={t.urgency} />
        </span>
        <span className="d">{t.conclusion}</span>
        <span className="m2 ex">
          <span className="m">{dateTime(t.created_at)}</span>
          <span>
            проверка <b className="m">{t.session_id}</b>
          </span>
          <span>
            тип <b className="m">{t.anomaly_type}</b>
          </span>
        </span>
      </summary>
      <div className="tin">
        <dl>
          <dt>Диагноз</dt>
          <dd>{t.conclusion}</dd>
          <dt>Приоритет</dt>
          <dd>{PRIORITY_LABEL[t.urgency]}</dd>
          <dt>Работы</dt>
          <dd>
            <ol>
              {t.operations.map((o, i) => (
                <li key={i}>{o}</li>
              ))}
            </ol>
          </dd>
          <dt>Запчасти</dt>
          <dd>{t.spare_parts.length ? t.spare_parts.join('; ') : 'нет'}</dd>
          <dt>Источники</dt>
          <dd>{t.references.map((r) => `${r.manual}, стр. ${r.pdf_page}`).join('; ')}</dd>
        </dl>
        <Link href={chatHref(vehicleId, t.session_id)} className="btn sm">
          <Icon name="message-2" size="s" />
          Проверка {t.session_id} в чате
        </Link>
      </div>
    </details>
  );
}

/** История машины: все проверки с графиком оценки и все заявки. Отдельный экран, чтобы списки не теснились в боковой панели. */
export function VehicleHistory({ vehicleId, tab, current }: { vehicleId: string; tab: HistoryTab; current: string | null }) {
  const [vehicle, setVehicle] = useState<VehicleDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setError(null);
    api
      .vehicle(vehicleId)
      .then(setVehicle)
      .catch((e: Error) => setError(e.message));
  }, [vehicleId]);

  useEffect(load, [load]);

  if (error) return <ErrorState text={error} onRetry={load} />;
  if (!vehicle) return <Loading text="Загружаю историю машины…" />;

  // Новые сверху: механику нужна последняя
  const sessions = [...vehicle.sessions].reverse();
  const tickets = [...vehicle.tickets].reverse();
  // Проверка, которая сейчас в чате. Без неё в адресе чат откроется на последней
  const inChat = current && vehicle.sessions.some((s) => s.session_id === current) ? current : null;

  return (
    <>
      <div className="hdr hhdr">
        <Link href={chatHref(vehicleId, inChat)} className="btn back">
          <Icon name="arrow-left" />
          В чат
        </Link>
        <div className="grow">
          <div className="h1">
            {vehicle.title} <span className="m">{vehicle.vehicle_id}</span>
          </div>
          <div className="sub m">
            {vehicle.garage_no} · {vehicle.engine_model}
          </div>
        </div>
        {/* Вкладки как разделы в верхнем меню. Они заменяют запись в истории браузера: «Назад» ведёт сразу в чат */}
        <nav className="htabs" aria-label="История машины">
          <Link href={historyHref(vehicleId, 'checks', inChat)} replace className={tab === 'checks' ? 'on' : ''} aria-current={tab === 'checks' ? 'page' : undefined}>
            <Icon name="history" />
            Проверки
            <span className="m">{sessions.length}</span>
          </Link>
          <Link href={historyHref(vehicleId, 'tickets', inChat)} replace className={tab === 'tickets' ? 'on' : ''} aria-current={tab === 'tickets' ? 'page' : undefined}>
            <Icon name="clipboard-list" />
            Заявки
            <span className="m">{tickets.length}</span>
          </Link>
        </nav>
        <span className="st only-d hhint">
          {tab === 'checks' ? 'Нажмите строку, чтобы разобрать проверку в чате' : tickets.length ? 'Нажмите строку, чтобы увидеть состав заявки' : ''}
        </span>
      </div>

      <div className="body">
        {tab === 'checks' ? (
          <div className="hgrid">
            <div>
              {sessions.length ? (
                <div className="ftable ctable">
                  <div className="fhead">
                    <span>Проверка</span>
                    <span>Дата</span>
                    <span>Результат ML</span>
                    <span>Оценка</span>
                    <span className="cf">Уверенность</span>
                    <span>Запись</span>
                    <span>Заявка</span>
                  </div>
                  {sessions.map((s) => (
                    <CheckRow key={s.session_id} vehicleId={vehicleId} s={s} current={s.session_id === inChat} />
                  ))}
                </div>
              ) : (
                <div className="box center" style={{ minHeight: 160 }}>
                  <Icon name="history" size="xl" />
                  <div className="e1">Проверок нет</div>
                </div>
              )}
            </div>
            {sessions.length ? (
              <div>
                {/* Шапка графика того же вида, что шапка таблицы: два блока стоят на одной линии */}
                <div className="chead">
                  <span>Оценка отклонения</span>
                  <span>пунктир: порог 0,5</span>
                </div>
                <div className="chart">
                  <ScoreChart sessions={vehicle.sessions} selected={inChat} />
                  <div className="cap">
                    <Icon name={TREND_ICON[vehicle.trend.direction]} size="s" />
                    {vehicle.trend.text}
                  </div>
                </div>
              </div>
            ) : null}
          </div>
        ) : (
          <>
            {tickets.length ? (
              <div className="ftable ttable">
                <div className="fhead">
                  <span>Заявка</span>
                  <span>Создана</span>
                  <span>Проверка</span>
                  <span>Тип</span>
                  <span>Приоритет</span>
                  <span>Диагноз</span>
                </div>
                {tickets.map((t) => (
                  <TicketRow key={t.ticket_id} vehicleId={vehicleId} t={t} />
                ))}
              </div>
            ) : (
              <div className="box center" style={{ minHeight: 160 }}>
                <Icon name="clipboard-list" size="xl" />
                <div className="e1">Заявок пока нет</div>
                <div>Заявка оформляется в чате после результата с отклонением.</div>
              </div>
            )}
          </>
        )}
      </div>
    </>
  );
}
