'use client';

import Link from 'next/link';
import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api } from '@/lib/api';
import { PRIORITY_LABEL, QUALITY_LABEL, dateTime, num } from '@/lib/format';
import type { Session, Ticket, VehicleDetail } from '@/lib/types';
import { PriorityBadge, StatusBadge } from './Badges';
import { Icon } from './Icon';
import { ChartDrop, ChartSheet } from './ChartSheet';
import { Pager } from './Pager';
import { ErrorState, Loading } from './States';
import { useFitRows, usePaged } from '@/lib/paging';
import { useSettings } from '@/lib/settings';

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

/** Узкий экран: график открывается панелью снизу, на широком выпадает под строкой. */
function useNarrow(): boolean {
  const [narrow, setNarrow] = useState(false);
  useEffect(() => {
    const query = window.matchMedia('(max-width: 900px)');
    const update = () => setNarrow(query.matches);
    update();
    query.addEventListener('change', update);
    return () => query.removeEventListener('change', update);
  }, []);
  return narrow;
}

/**
 * Строка проверки. Нажатие на строку показывает график оценки здесь же, а в чат ведёт отдельная кнопка:
 * механик сначала смотрит, как менялась оценка, и только потом решает, разбирать ли проверку.
 */
function CheckRow({
  vehicleId,
  s,
  current,
  open,
  onToggle,
}: {
  vehicleId: string;
  s: Session;
  current: boolean;
  open: boolean;
  onToggle: () => void;
}) {
  const flawed = s.signal_quality !== 'good';
  return (
    <div
      className={`frow crow${s.status === 'anomaly' ? ' s-attention' : ''}${current ? ' cur' : ''}${open ? ' open' : ''}`}
      data-row
      role="button"
      tabIndex={0}
      aria-expanded={open}
      aria-label={`Проверка ${s.session_id}: показать график оценки`}
      onClick={onToggle}
      onKeyDown={(e) => {
        if (e.target === e.currentTarget && (e.key === 'Enter' || e.key === ' ')) {
          e.preventDefault();
          onToggle();
        }
      }}
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
      <span className="d acts">
        <button
          type="button"
          className={`btn sm${open ? ' on' : ''}`}
          aria-expanded={open}
          title="График оценки отклонения"
          onClick={(e) => {
            e.stopPropagation();
            onToggle();
          }}
        >
          <Icon name="chart-line" size="s" />
          <span className="bt">График</span>
        </button>
        <Link href={chatHref(vehicleId, s.session_id)} className="btn sm" title="Разобрать проверку в чате" onClick={(e) => e.stopPropagation()}>
          <Icon name="message-2" size="s" />
          <span className="bt">В чат</span>
        </Link>
      </span>
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
    </div>
  );
}

function TicketRow({ vehicleId, t }: { vehicleId: string; t: Ticket }) {
  return (
    <details className="trec">
      <summary className="frow" data-row>
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

/** История машины: все проверки, график оценки в выдвижной панели и все заявки. Отдельный экран, чтобы списки не теснились в боковой панели. */
export function VehicleHistory({ vehicleId, tab, current }: { vehicleId: string; tab: HistoryTab; current: string | null }) {
  const [vehicle, setVehicle] = useState<VehicleDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Проверка, для которой открыт график. closingId держит блок на экране, пока он плавно сворачивается
  const [openId, setOpenId] = useState<string | null>(null);
  const [closingId, setClosingId] = useState<string | null>(null);
  const [seenOpen, setSeenOpen] = useState<string | null>(null);
  const lastOpen = useRef('');
  const narrow = useNarrow();
  const closeChart = useCallback(() => setOpenId(null), []);
  const toggleChart = useCallback((id: string) => setOpenId((cur) => (cur === id ? null : id)), []);

  // Прежний блок помечается закрывающимся в том же рендере, где сменился openId.
  // Если ставить пометку позже, в эффекте, блок успевает исчезнуть и сворачивается без анимации
  if (seenOpen !== openId) {
    setSeenOpen(openId);
    if (seenOpen) setClosingId(seenOpen);
  }

  useEffect(() => {
    if (!closingId) return;
    const timer = window.setTimeout(() => setClosingId((cur) => (cur === closingId ? null : cur)), 300);
    return () => window.clearTimeout(timer);
  }, [closingId]);

  // Компьютер: блок не модальный, поэтому закрываем его сами — нажатием на пустое место или клавишей Esc
  useEffect(() => {
    if (!openId || narrow) return;
    const onDown = (event: PointerEvent) => {
      if (!(event.target as HTMLElement).closest('.cdrop, .crow')) setOpenId(null);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpenId(null);
    };
    document.addEventListener('pointerdown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('pointerdown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [openId, narrow]);

  const load = useCallback(() => {
    setError(null);
    api
      .vehicle(vehicleId)
      .then(setVehicle)
      .catch((e: Error) => setError(e.message));
  }, [vehicleId]);

  useEffect(load, [load]);

  // Новые сверху: механику нужна последняя
  const sessions = useMemo(() => (vehicle ? [...vehicle.sessions].reverse() : []), [vehicle]);
  const tickets = useMemo(() => (vehicle ? [...vehicle.tickets].reverse() : []), [vehicle]);
  // Страница не прокручивается: в таблице столько строк, сколько помещается, остальное листается
  const settings = useSettings();
  const { areaRef, pageSize } = useFitRows([settings.size, tab, vehicle]);
  const pagedChecks = usePaged(sessions, pageSize, tab);
  const pagedTickets = usePaged(tickets, pageSize, tab);

  if (error) return <ErrorState text={error} onRetry={load} />;
  if (!vehicle) return <Loading text="Загружаю историю машины…" />;

  // Проверка, которая сейчас в чате. Без неё в адресе чат откроется на последней
  const inChat = current && vehicle.sessions.some((s) => s.session_id === current) ? current : null;
  if (openId) lastOpen.current = openId;
  const trendIcon = TREND_ICON[vehicle.trend.direction];

  return (
    <>
      <div className="hdr hhdr">
        {/* Та же кнопка «назад», что на остальных экранах */}
        <Link href={chatHref(vehicleId, inChat)} className="hb" aria-label="Назад в чат" title="Назад в чат">
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
          {tab === 'checks' ? 'Нажмите строку, чтобы увидеть график оценки' : tickets.length ? 'Нажмите строку, чтобы увидеть состав заявки' : ''}
        </span>
      </div>

      <div className="body fit">
        {tab === 'checks' ? (
          <>
            {sessions.length ? (
              <div className="trendbar">
                <Icon name={trendIcon} />
                <span className="tb-t">{vehicle.trend.text}</span>
              </div>
            ) : null}
            {sessions.length ? (
              <div className="fit-area" ref={areaRef}>
                <div className="ftable ctable">
                  <div className="fhead" data-head>
                    <span>Проверка</span>
                    <span>Дата</span>
                    <span>Результат ML</span>
                    <span>Оценка</span>
                    <span className="cf">Уверенность</span>
                    <span>Запись</span>
                    <span>Заявка</span>
                    <span />
                  </div>
                  {pagedChecks.rows.map((s) => (
                    <Fragment key={s.session_id}>
                      <CheckRow
                        vehicleId={vehicleId}
                        s={s}
                        current={s.session_id === inChat}
                        open={openId === s.session_id}
                        onToggle={() => toggleChart(s.session_id)}
                      />
                      {!narrow && (openId === s.session_id || closingId === s.session_id) ? (
                        <ChartDrop
                          sessions={vehicle.sessions}
                          selected={s.session_id}
                          trendIcon={trendIcon}
                          trendText={vehicle.trend.text}
                          chatHref={chatHref(vehicleId, s.session_id)}
                          closing={openId !== s.session_id}
                        />
                      ) : null}
                    </Fragment>
                  ))}
                </div>
              </div>
            ) : (
              <div className="box center" style={{ minHeight: 160 }}>
                <Icon name="history" size="xl" />
                <div className="e1">Проверок нет</div>
              </div>
            )}
            <Pager paged={pagedChecks} label="проверки" />
            <ChartSheet
              open={narrow && openId !== null}
              onClose={closeChart}
              sessions={vehicle.sessions}
              selected={lastOpen.current}
              trendIcon={trendIcon}
              trendText={vehicle.trend.text}
              chatHref={chatHref(vehicleId, lastOpen.current)}
            />
          </>
        ) : (
          <>
            {tickets.length ? (
              <div className="fit-area" ref={areaRef}>
                <div className="ftable ttable">
                  <div className="fhead" data-head>
                  <span>Заявка</span>
                  <span>Создана</span>
                  <span>Проверка</span>
                  <span>Тип</span>
                  <span>Приоритет</span>
                  <span>Диагноз</span>
                </div>
                  {pagedTickets.rows.map((t) => (
                    <TicketRow key={t.ticket_id} vehicleId={vehicleId} t={t} />
                  ))}
                </div>
              </div>
            ) : (
              <div className="box center" style={{ minHeight: 160 }}>
                <Icon name="clipboard-list" size="xl" />
                <div className="e1">Заявок пока нет</div>
                <div>Заявка оформляется в чате после результата с отклонением.</div>
              </div>
            )}
            <Pager paged={pagedTickets} label="заявки" />
          </>
        )}
      </div>
    </>
  );
}
