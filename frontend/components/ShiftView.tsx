'use client';

import Link from 'next/link';
import { useCallback, useEffect, useState, type CSSProperties, type ReactNode } from 'react';
import { PRIORITY_LABEL, capitalize, dateTime, int, num, plural } from '@/lib/format';
import { filtersToUrl, journalApi, NO_FILTERS, type PilotMetrics, type ShiftSummary } from '@/lib/journal';
import { useFitRows, usePaged } from '@/lib/paging';
import { usePresence } from '@/lib/presence';
import { useSettings } from '@/lib/settings';
import { Icon } from './Icon';
import { Pager } from './Pager';
import { ErrorState, Loading } from './States';

type Mode = 'today' | 'yesterday' | 'custom';
type List = 'mechanics' | 'marks' | 'tickets';

/** Как часто сводка перечитывается с сервера, мс */
const REFRESH_MS = 30_000;

/** Дата по местному времени автопарка: YYYY-MM-DD */
const ymd = (d: Date) => new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Moscow' }).format(d);

function periodOf(mode: Mode, custom: { from: string; to: string }): { from: string; to: string } {
  if (mode === 'custom') return custom;
  const day = new Date(Date.now() - (mode === 'yesterday' ? 86_400_000 : 0));
  return { from: ymd(day), to: ymd(day) };
}

/** «27.11 08:00 – 27.11 20:00» для кнопки периода */
function customLabel(p: { from: string; to: string }): string {
  const show = (v: string) => (v.length > 10 ? `${v.slice(8, 10)}.${v.slice(5, 7)} ${v.slice(11, 16)}` : `${v.slice(8, 10)}.${v.slice(5, 7)}`);
  if (!p.from && !p.to) return 'Период';
  return `${p.from ? show(p.from) : '…'} – ${p.to ? show(p.to) : '…'}`;
}

/** Число с подписью: плитка сводки. С onClick — вкладка: показывает свой список под плитками */
function Stat({
  label,
  value,
  hint,
  href,
  warn,
  onClick,
  on,
}: {
  label: string;
  value: string;
  hint?: string;
  href?: string;
  warn?: boolean;
  onClick?: () => void;
  on?: boolean;
}) {
  const body = (
    <>
      <span className="ss-l">{label}</span>
      <span className="ss-v m">{value}</span>
      <span className="ss-h">{hint}</span>
    </>
  );
  if (onClick) {
    return (
      <button type="button" className={`ss link tab${on ? ' on' : ''}`} onClick={onClick} aria-pressed={Boolean(on)}>
        {body}
      </button>
    );
  }
  return href ? (
    <Link href={href} className={`ss${warn ? ' warn' : ''} link`}>
      {body}
    </Link>
  ) : (
    <div className={`ss${warn ? ' warn' : ''}`}>{body}</div>
  );
}

function minutes(v: number | null): string {
  if (v === null) return '—';
  if (v < 60) return `${num(v, v < 10 ? 1 : 0)} мин`;
  return `${num(v / 60, 1)} ч`;
}

/** Таблица списка смены: колонки с подписями, на телефоне каждая строка — карточка с подписями значений */
interface Column<T> {
  label: string;
  width: string;
  num?: boolean;
  /** Первая колонка на телефоне идёт заголовком карточки без подписи */
  render: (row: T) => ReactNode;
}

function ListTable<T>({ rows, columns, label, empty }: { rows: T[]; columns: Column<T>[]; label: string; empty: string }) {
  const settings = useSettings();
  const { areaRef, pageSize } = useFitRows([settings.size, rows.length > 0]);
  const paged = usePaged(rows, pageSize);
  if (!rows.length) {
    return (
      <div className="box center">
        <Icon name="list-details" size="xl" />
        <div className="e1">{empty}</div>
      </div>
    );
  }
  const style = { '--cols': columns.map((c) => c.width).join(' ') } as CSSProperties;
  return (
    <>
      <div className="fit-area" ref={areaRef}>
        <div className="ftable stable" style={style}>
          <div className="shead" data-head>
            {columns.map((c) => (
              <span key={c.label} className={c.num ? 'snum' : undefined}>
                {c.label}
              </span>
            ))}
          </div>
          {paged.rows.map((row, i) => (
            <div className="srow" data-row key={i}>
              {columns.map((c, k) => (
                <span key={c.label} className={c.num ? 'snum' : undefined} data-label={k ? c.label : undefined}>
                  {c.render(row)}
                </span>
              ))}
            </div>
          ))}
        </div>
      </div>
      <Pager paged={paged} label={label} />
    </>
  );
}

const LIST_TITLE: Record<List, string> = { mechanics: 'Кто работал', marks: 'Отмеченные шаги', tickets: 'Заявки за смену' };

/** Период смены: панель снизу с началом и концом */
function PeriodSheet({
  value,
  leaving,
  onApply,
  onClose,
}: {
  value: { from: string; to: string };
  leaving: boolean;
  onApply: (p: { from: string; to: string }) => void;
  onClose: () => void;
}) {
  const today = ymd(new Date());
  const [from, setFrom] = useState(value.from.length > 10 ? value.from : `${value.from || today}T08:00`);
  const [to, setTo] = useState(value.to.length > 10 ? value.to : `${value.to || today}T20:00`);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);
  const bad = Boolean(from && to && to <= from);
  return (
    <>
      <button type="button" className={`sp-dim${leaving ? ' leaving' : ''}`} aria-label="Закрыть" onClick={onClose} />
      <aside className={`sp jsheet${leaving ? ' leaving' : ''}`} role="dialog" aria-label="Период смены">
        <div className="handle">
          <i />
        </div>
        <div className="sp-h">
          <Icon name="calendar" />
          <span>Период смены</span>
          <button type="button" className="hb" onClick={onClose} aria-label="Закрыть">
            <Icon name="x" />
          </button>
        </div>
        <div className="sp-b">
          <div className="jf-two">
            <div className="sp-g">
              <div className="sp-l">Начало</div>
              <input type="datetime-local" className="inp" value={from} onChange={(e) => setFrom(e.target.value)} aria-label="Начало смены" />
            </div>
            <div className="sp-g">
              <div className="sp-l">Конец</div>
              <input type="datetime-local" className="inp" value={to} onChange={(e) => setTo(e.target.value)} aria-label="Конец смены" />
            </div>
          </div>
          {bad ? <div className="sp-s jc-err">Конец смены раньше начала</div> : null}
        </div>
        <div className="jf-f">
          <button type="button" className="btn" onClick={onClose}>
            Отмена
          </button>
          <button type="button" className="btn pri" disabled={!from || !to || bad} onClick={() => onApply({ from, to })}>
            Показать
          </button>
        </div>
      </aside>
    </>
  );
}

/** Сводка смены для главного механика и метрики пилота за период. */
export function ShiftView() {
  const [mode, setMode] = useState<Mode>('today');
  const [custom, setCustom] = useState({ from: '', to: '' });
  /** Какой список показан под плитками: плитки «Механики», «Шагов отмечено», «Заявок создано» — вкладки */
  const [list, setList] = useState<List>('mechanics');
  const [summary, setSummary] = useState<ShiftSummary | null>(null);
  const [metrics, setMetrics] = useState<PilotMetrics | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [updatedAt, setUpdatedAt] = useState<string | null>(null);
  const [periodOpen, setPeriodOpen] = useState(false);
  const period = periodOf(mode, custom);

  const load = useCallback(
    (quiet: boolean) => {
      if (!quiet) {
        setLoading(true);
        setError(null);
      }
      Promise.all([journalApi.shift(period.from, period.to), journalApi.metrics(period.from, period.to)])
        .then(([s, m]) => {
          setSummary(s);
          setMetrics(m);
          setError(null);
          setUpdatedAt(new Date().toISOString());
        })
        .catch((e: Error) => {
          if (!quiet) setError(e.message);
        })
        .finally(() => {
          if (!quiet) setLoading(false);
        });
    },
    [period.from, period.to],
  );

  useEffect(() => load(false), [load]);

  // Сводка обновляется сама в фоне, пока вкладка на экране, и сразу при возврате на неё
  useEffect(() => {
    const refresh = () => {
      if (document.visibilityState === 'visible') load(true);
    };
    const timer = window.setInterval(refresh, REFRESH_MS);
    document.addEventListener('visibilitychange', refresh);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', refresh);
    };
  }, [load]);

  const closePeriod = useCallback(() => setPeriodOpen(false), []);
  const periodView = usePresence(periodOpen ? true : null);
  const journalLink = `/log${filtersToUrl({ ...NO_FILTERS, from: period.from, to: period.to, status: 'open' })}`;

  const tools = (
    <div className="ftools stools">
      <div className="ft-t">
        <Icon name="calendar-stats" size="s" />
        {/* На телефоне при своём периоде вместо подписи стоит сам период: обе в строку не помещаются */}
        <b className={mode === 'custom' ? 'only-d' : undefined}>
          Смена<span className="only-d"> и метрики пилота</span>
        </b>
        {mode === 'custom' ? <span className="ft-hint only-m m">{customLabel(custom)}</span> : null}
      </div>
      {updatedAt ? (
        <span className="ft-hint only-d" title="Сводка обновляется сама каждые 30 секунд">
          обновлено <span className="m">{dateTime(updatedAt)}</span>
        </span>
      ) : null}
      <div className="seg speriod" role="radiogroup" aria-label="Период">
        <button type="button" role="radio" aria-checked={mode === 'today'} className={mode === 'today' ? 'on' : ''} onClick={() => setMode('today')}>
          Сегодня
        </button>
        <button type="button" role="radio" aria-checked={mode === 'yesterday'} className={mode === 'yesterday' ? 'on' : ''} onClick={() => setMode('yesterday')}>
          Вчера
        </button>
        <button type="button" role="radio" aria-checked={mode === 'custom'} className={mode === 'custom' ? 'on' : ''} onClick={() => setPeriodOpen(true)}>
          <Icon name="calendar" size="s" />
          {/* На телефоне выбранный период стоит в подписи под кнопками: в кнопку он не помещается */}
          {mode === 'custom' ? <span className="m only-d">{customLabel(custom)}</span> : null}
          <span className={mode === 'custom' ? 'only-m' : ''}>Период</span>
        </button>
      </div>
      <button type="button" className="btn sm" onClick={() => load(false)} disabled={loading} aria-label="Обновить сводку" title="Обновить">
        <Icon name="refresh" size="s" className={loading ? 'spin' : ''} />
        <span className="only-d">Обновить</span>
      </button>
    </div>
  );

  const sheet = periodView.shown ? (
    <PeriodSheet
      value={custom}
      leaving={periodView.leaving}
      onClose={closePeriod}
      onApply={(p) => {
        setCustom(p);
        setMode('custom');
        setPeriodOpen(false);
      }}
    />
  ) : null;

  if (error || !summary || !metrics) {
    return (
      <div className="body fit">
        {tools}
        <div className="box center">{error ? <ErrorState text={error} onRetry={() => load(false)} /> : <Loading text="Собираю сводку смены…" />}</div>
        {sheet}
      </div>
    );
  }

  const t = summary.totals;
  const m = metrics;
  const share = m.refusals.share;
  return (
    <div className="body fit sbody">
      {tools}
      <section className="ssec">
        <div className="ssec-h">За смену</div>
        <div className="sstats">
          <Stat
            label="Механики"
            value={int(summary.mechanics.length)}
            hint={`${int(t.questions)} ${plural(t.questions, 'вопрос', 'вопроса', 'вопросов')} по ${t.vehicles} ${plural(t.vehicles, 'машине', 'машинам', 'машинам')}`}
            onClick={() => setList('mechanics')}
            on={list === 'mechanics'}
          />
          <Stat label="Шагов отмечено" value={int(t.marks)} hint="кем и когда" onClick={() => setList('marks')} on={list === 'marks'} />
          <Stat label="Заявок создано" value={int(t.tickets)} hint="машина и приоритет" onClick={() => setList('tickets')} on={list === 'tickets'} />
          <Stat label="Ответов агента" value={int(t.answers)} />
          <Stat
            label="Ждут разбора"
            value={int(t.open_cases)}
            hint={t.open_total > t.open_cases ? `всего в журнале ${t.open_total}` : 'открыть журнал'}
            href={journalLink}
            warn={t.open_cases > 0}
          />
        </div>
      </section>
      <section className="ssec">
        <div className="ssec-h">Метрики пилота</div>
        <div className="sstats">
          <Stat
            label="От вердикта до заявки"
            value={minutes(m.verdict_to_ticket.avg_min)}
            hint={m.verdict_to_ticket.count ? `по ${m.verdict_to_ticket.count} ${plural(m.verdict_to_ticket.count, 'заявке', 'заявкам', 'заявкам')}, медиана ${minutes(m.verdict_to_ticket.median_min)}` : 'заявок не было'}
          />
          <Stat
            label="Честные отказы"
            value={share === null ? '—' : `${num(share * 100, 0)} %`}
            hint={m.refusals.answers ? `${m.refusals.not_found} из ${m.refusals.answers} ответов` : 'ответов не было'}
          />
          <Stat label="Повтор после ремонта" value={int(m.repeat_after_repair)} hint={`вердиктов всего ${m.verdicts}`} />
          <Stat
            label="Время ответа"
            value={m.response.avg_ms === null ? '—' : `${num(m.response.avg_ms / 1000, 1)} с`}
            hint={m.response.count ? `в среднем по ${m.response.count} ${plural(m.response.count, 'ответу', 'ответам', 'ответам')}` : 'ответов не было'}
          />
          <Stat
            label="Стоимость, ₽"
            value={num(m.cost.total_rub + m.cost.speech_rub, 2)}
            hint={m.cost.per_answer_rub === null ? 'ответов не было' : `на ответ ${num(m.cost.per_answer_rub, 2)}`}
          />
        </div>
      </section>
      {/* Выбранный список — на всё оставшееся место, строки по высоте экрана, листание как в парке */}
      <div className="ssec-h slist-h">{LIST_TITLE[list]}</div>
        {list === 'mechanics' ? (
          <ListTable
            rows={summary.mechanics}
            label="механики"
            empty="За период никто не работал"
            columns={[
              { label: 'Механик', width: 'minmax(140px, 1.4fr)', render: (r) => r.name ?? <span className="mut">Фамилия не указана</span> },
              { label: 'Вопросов агенту', width: 'calc(150px * var(--k))', num: true, render: (r) => <span className="m">{r.questions}</span> },
              { label: 'Отметок шагов', width: 'calc(130px * var(--k))', num: true, render: (r) => <span className="m">{r.marks}</span> },
              { label: 'Сообщений администратору', width: 'calc(210px * var(--k))', num: true, render: (r) => <span className="m">{r.messages}</span> },
              { label: 'Первое действие', width: 'calc(150px * var(--k))', render: (r) => <span className="m">{dateTime(r.first_at)}</span> },
              { label: 'Последнее действие', width: 'calc(170px * var(--k))', render: (r) => <span className="m">{dateTime(r.last_at)}</span> },
            ]}
          />
        ) : list === 'marks' ? (
          <ListTable
            rows={summary.marks}
            label="шаги"
            empty="За период шаги не отмечали"
            columns={[
              { label: 'Шаг', width: 'minmax(200px, 2fr)', render: (r) => r.step },
              { label: 'Машина', width: 'minmax(150px, 1fr)', render: (r) => <span className="m">{r.vehicle_id}</span> },
              { label: 'Список', width: 'calc(110px * var(--k))', render: (r) => (r.list === 'checks' ? 'проверка' : 'ремонт') },
              { label: 'Механик', width: 'minmax(120px, 1fr)', render: (r) => r.author ?? <span className="mut">не указан</span> },
              { label: 'Время', width: 'calc(110px * var(--k))', render: (r) => <span className="m">{dateTime(r.at)}</span> },
            ]}
          />
        ) : (
          <ListTable
            rows={summary.tickets}
            label="заявки"
            empty="За период заявок не создавали"
            columns={[
              { label: 'Заявка', width: 'calc(120px * var(--k))', render: (r) => <span className="m">{r.ticket_id}</span> },
              { label: 'Машина', width: 'minmax(150px, 1fr)', render: (r) => <span className="m">{r.vehicle_id}</span> },
              { label: 'Приоритет', width: 'calc(110px * var(--k))', render: (r) => (r.urgency ? capitalize(PRIORITY_LABEL[r.urgency]) : '—') },
              { label: 'Заключение', width: 'minmax(200px, 2fr)', render: (r) => r.conclusion || '—' },
              { label: 'Время', width: 'calc(110px * var(--k))', render: (r) => <span className="m">{dateTime(r.created_at)}</span> },
            ]}
          />
        )}
      {sheet}
    </div>
  );
}
