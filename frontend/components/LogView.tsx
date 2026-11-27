'use client';

import Link from 'next/link';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { GAPS_EVENT } from '@/lib/api';
import { dateTime, int, num, plural } from '@/lib/format';
import {
  NO_FILTERS,
  activeFilters,
  exportUrl,
  filtersFromUrl,
  filtersToUrl,
  journalApi,
  type CaseStatus,
  type JournalFilters,
  type JournalItem,
  type JournalPage,
} from '@/lib/journal';
import { useFitRows, type Paged } from '@/lib/paging';
import { usePresence } from '@/lib/presence';
import { useSettings } from '@/lib/settings';
import type { MessageKind } from '@/lib/types';
import { CaseSheet, StatusChip } from './CaseSheet';
import { FilterSheet } from './JournalFilters';
import { Icon } from './Icon';
import { Pager } from './Pager';
import { ErrorState, Loading } from './States';

const KIND_LABEL: Record<MessageKind | 'admin', string> = {
  verdict: 'Вердикт',
  answer: 'Ответ',
  ticket_draft: 'Черновик заявки',
  ticket_created: 'Заявка создана',
  notice: 'Сообщение',
  admin: 'Вопрос администратору',
};

const TOOL_LABEL: Record<string, string> = {
  get_diagnosis: 'диагностика',
  get_vehicle_history: 'история машины',
  search_manuals: 'поиск в руководствах',
  read_manual_page: 'страница руководства',
  prepare_ticket: 'черновик заявки',
  submit_ticket: 'отправка заявки',
};

/** «повторилось 3 раза» */
export function repeatsText(n: number): string {
  return `повторилось ${n} ${plural(n, 'раз', 'раза', 'раз')}`;
}

/** Кто написал: у сообщения механика — его автор, у остальных — кто задал вопрос */
export function whoOf(it: JournalItem): string | null {
  return it.report?.author ?? it.author;
}

function Sources({ item }: { item: JournalItem }) {
  if (!item.sources.length) return <span className="ls mut">{item.source === 'admin' ? '—' : 'нет'}</span>;
  return (
    <span className="ls">
      {item.sources.map((s, i) => (
        <span key={i}>
          <Icon name="file-text" size="s" />
          {s.short} <span className="mut">стр.</span> {s.pdf_page}
        </span>
      ))}
    </span>
  );
}

/** Инструменты обращения в порядке первого вызова; повторные вызовы сложены в счётчик. */
function toolGroups(item: JournalItem): { label: string; count: number }[] {
  const groups = new Map<string, number>();
  for (const t of item.tools) {
    const label = TOOL_LABEL[t] ?? t;
    groups.set(label, (groups.get(label) ?? 0) + 1);
  }
  return [...groups].map(([label, count]) => ({ label, count }));
}

/** Три колонки строки: что вызывал агент (по одному инструменту в строке), время ответа и токены числами. */
function Usage({ item }: { item: JournalItem }) {
  const u = item.usage;
  const groups = toolGroups(item);
  return (
    <>
      <span className="lu">
        {groups.length ? (
          groups.map((g) => (
            <span key={g.label}>
              {g.label}
              {g.count > 1 ? <b className="m"> ×{g.count}</b> : null}
            </span>
          ))
        ) : (
          <span className="mut">{item.source === 'admin' ? '—' : 'не вызывал'}</span>
        )}
      </span>
      <span className="ln m">{u?.duration_ms !== undefined ? `${num(u.duration_ms / 1000, 1)} с` : '—'}</span>
      <span className="ln m">{u ? int((u.input_tokens ?? 0) + (u.output_tokens ?? 0)) : '—'}</span>
    </>
  );
}

const isOpen = (it: JournalItem) => it.status === 'new' || it.status === 'in_work';

function Row({
  it,
  selected,
  onSelect,
  onOpen,
}: {
  it: JournalItem;
  selected: boolean;
  onSelect: (it: JournalItem) => void;
  onOpen: (it: JournalItem) => void;
}) {
  const who = whoOf(it);
  const gap = it.gap;
  return (
    <div
      className={`lrow jrow${isOpen(it) ? ' gap' : ''}${selected ? ' sel' : ''}`}
      data-row
      tabIndex={0}
      onClick={() => onOpen(it)}
      onKeyDown={(e) => {
        // Enter на строке открывает карточку; на чекбоксе и ссылке внутри строки — их собственное действие
        if (e.key === 'Enter' && e.target === e.currentTarget) onOpen(it);
      }}
      title="Открыть карточку случая"
    >
      <span className="jc-sel" onClick={(e) => e.stopPropagation()}>
        {gap ? (
          <input type="checkbox" checked={selected} onChange={() => onSelect(it)} aria-label="Выбрать строку" />
        ) : null}
      </span>
      <span className="lt">
        <span className="m">{dateTime(it.created_at)}</span>
        {who ? (
          <span className="l2 lwho" title={it.report ? 'Автор сообщения механика' : 'Кто задал вопрос'}>
            {who}
          </span>
        ) : null}
        {it.status ? <StatusChip status={it.status} /> : null}
      </span>
      <span className="lv">
        {it.vehicle_id ? (
          <Link href={`/v/${encodeURIComponent(it.vehicle_id)}`} className="llink m" onClick={(e) => e.stopPropagation()}>
            {it.vehicle_id}
          </Link>
        ) : (
          <span className="mut">без машины</span>
        )}
        <span className="l2">
          {it.vehicle_title && it.vehicle_title !== it.vehicle_id ? <span>{it.vehicle_title}</span> : null}
          {it.session_id ? <span className="jgap m">{it.session_id}</span> : null}
        </span>
      </span>
      <span className="lq">{it.question || <span className="mut">{it.photos ? 'фото без текста' : '—'}</span>}</span>
      <span className="la">
        {gap ? (
          <span className={`lkind lgap${gap.status === 'reviewed' ? ' done' : ''}`} title={gap.title}>
            <Icon name="alert-triangle" size="s" />
            {gap.label}
          </span>
        ) : (
          <span className="lkind">
            {KIND_LABEL[it.kind] ?? it.kind}
            {it.ticket_id ? <span className="jgap m">{it.ticket_id}</span> : null}
          </span>
        )}
        {/* Сообщение механика важнее текста ответа: администратор видит, что не так */}
        <span className="l2">
          {it.repeats > 1 ? <span className="jrep">{repeatsText(it.repeats)}</span> : null}
          {it.injection && gap?.type !== 'injection' ? <span className="jinj">посторонний текст в диагностике</span> : null}
          {it.report
            ? `${it.report.reason}${it.report.text ? `: ${it.report.text}` : ''}`
            : it.source === 'admin'
              ? 'Вопрос напрямую, без ответа агента'
              : it.answer}
        </span>
      </span>
      <Sources item={it} />
      <Usage item={it} />
    </div>
  );
}

/** Как часто журнал перечитывается с сервера, мс */
const REFRESH_MS = 10_000;
/** Пауза после ввода в поиске, мс */
const TYPE_MS = 350;

/** Подпись строки журнала для сравнения: не перерисовываем тот же список при фоновом обновлении */
const signature = (d: JournalPage) =>
  `${d.total}|${d.page}|${d.gaps_open}|` + d.items.map((i) => `${i.id}:${i.status}:${i.repeats}:${i.reports_count}`).join(',');

/** Журнал обращений: кто что спросил, что ответил агент и на какие страницы сослался. Случаи разбирает администратор. */
export function LogView() {
  const settings = useSettings();
  const [ready, setReady] = useState(false);
  const [filters, setFilters] = useState<JournalFilters>(NO_FILTERS);
  const [search, setSearch] = useState('');
  const [pageNo, setPageNo] = useState(1);
  const [data, setData] = useState<JournalPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  /** Когда журнал последний раз получен с сервера */
  const [updatedAt, setUpdatedAt] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [busy, setBusy] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [opened, setOpened] = useState<string | null>(null);

  // Страница не прокручивается: в таблице столько строк, сколько помещается, остальное листается на сервере
  const { areaRef, pageSize } = useFitRows([settings.size, data ? data.items.length > 0 : false]);

  // Фильтры из адреса страницы (ссылка со сводки смены), поиск — из них же
  useEffect(() => {
    const f = filtersFromUrl(window.location.search);
    setFilters(f);
    setSearch(f.q);
    setReady(true);
  }, []);

  /** Смена фильтров: первая страница, выбор снимается */
  const setFilter = useCallback((patch: Partial<JournalFilters>) => {
    setFilters((f) => ({ ...f, ...patch }));
    setPageNo(1);
    setSelected(new Set());
  }, []);

  // Поиск уходит на сервер после паузы в наборе
  useEffect(() => {
    if (!ready || search === filters.q) return;
    const timer = window.setTimeout(() => setFilter({ q: search }), TYPE_MS);
    return () => window.clearTimeout(timer);
  }, [search, filters.q, ready, setFilter]);

  // Адрес страницы помнит фильтры: после обновления страницы журнал открывается с ними же
  useEffect(() => {
    if (ready) window.history.replaceState(null, '', `/log${filtersToUrl(filters)}`);
  }, [filters, ready]);

  // Помещается другое число строк: остаёмся на той же первой строке
  const seenSize = useRef(pageSize);
  useEffect(() => {
    if (seenSize.current === pageSize) return;
    const first = (pageNo - 1) * seenSize.current;
    seenSize.current = pageSize;
    setPageNo(Math.floor(first / pageSize) + 1);
  }, [pageSize, pageNo]);

  const seq = useRef(0);
  /** quiet — фоновое обновление: список на экране не трогаем, пока не пришёл новый, сбой связи не показываем */
  const load = useCallback(
    (quiet: boolean) => {
      if (!ready) return;
      const mine = ++seq.current;
      if (!quiet) {
        setError(null);
        setLoading(true);
      }
      journalApi
        .page(filters, pageNo, pageSize)
        .then((d) => {
          if (mine !== seq.current) return;
          setError(null);
          setUpdatedAt(new Date().toISOString());
          setData((cur) => (cur && signature(cur) === signature(d) ? cur : d));
          if (d.page !== pageNo) setPageNo(d.page);
        })
        .catch((e: Error) => {
          if (!quiet && mine === seq.current) setError(e.message);
        })
        .finally(() => {
          if (!quiet && mine === seq.current) setLoading(false);
        });
    },
    [filters, pageNo, pageSize, ready],
  );

  useEffect(() => load(false), [load]);

  // Журнал обновляется сам в фоне: раз в REFRESH_MS, пока вкладка на экране, и сразу при возврате на неё
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

  const toggle = useCallback((it: JournalItem) => {
    setSelected((cur) => {
      const next = new Set(cur);
      if (next.has(it.id)) next.delete(it.id);
      else next.add(it.id);
      return next;
    });
  }, []);

  const cases = useMemo(() => (data ? data.items.filter((i) => i.gap) : []), [data]);
  const allOnPage = cases.length > 0 && cases.every((i) => selected.has(i.id));
  const toggleAll = () =>
    setSelected((cur) => {
      const next = new Set(cur);
      cases.forEach((i) => (allOnPage ? next.delete(i.id) : next.add(i.id)));
      return next;
    });

  const changed = useCallback(() => {
    window.dispatchEvent(new Event(GAPS_EVENT));
    load(true);
  }, [load]);

  const mark = (status: CaseStatus) => {
    setBusy(true);
    journalApi
      .setStatus({ ids: [...selected], status, reviewer: settings.mechanic.trim() || null })
      .then(() => {
        setSelected(new Set());
        changed();
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setBusy(false));
  };

  const reset = () => {
    setSearch('');
    setFilter(NO_FILTERS);
  };

  const onlyOpen = filters.status === 'open';
  const extra = activeFilters(filters);
  const filtered = extra > 0 || Boolean(filters.q) || onlyOpen;
  const gapsOpen = data?.gaps_open ?? 0;

  const closeFilters = useCallback(() => setFiltersOpen(false), []);
  const filtersView = usePresence(filtersOpen ? true : null);
  const closeCase = useCallback(() => setOpened(null), []);
  const caseView = usePresence(opened);

  const paged: Paged<JournalItem> | null = data
    ? {
        page: data.page - 1,
        pages: Math.max(1, Math.ceil(data.total / data.page_size)),
        rows: data.items,
        from: data.total ? (data.page - 1) * data.page_size + 1 : 0,
        to: (data.page - 1) * data.page_size + data.items.length,
        total: data.total,
        setPage: (p: number) => setPageNo(p + 1),
      }
    : null;

  return (
    <div className="body fit">
      {/* Отдельной полосы под шапкой нет: название, поиск, фильтры, обновление и действия стоят в панели таблицы */}
      <div className="ftools jtools">
        {selected.size ? (
          <div className="ft-t jsel">
            <button type="button" className="hb" onClick={() => setSelected(new Set())} aria-label="Снять выбор" title="Снять выбор">
              <Icon name="x" />
            </button>
            <b>
              <span className="only-d">Выбрано </span>
              <span className="m">{selected.size}</span>
            </b>
          </div>
        ) : (
          <div className="ft-t">
            <Icon name="history" size="s" />
            {/* На телефоне панель в одну строку: длинные подписи туда не помещаются */}
            <b>
              Журнал<span className="only-d"> обращений</span>
            </b>
            {data ? <span className="ft-n">{data.total}</span> : null}
          </div>
        )}
        {!selected.size && updatedAt ? (
          <span className="ft-hint jt-hint" title="Журнал обновляется сам каждые 10 секунд">
            обновлено <span className="m">{dateTime(updatedAt)}</span>
          </span>
        ) : null}
        {/* Поиск стоит на месте и при выборе строк: панель не меняет высоту, таблица не листается заново */}
        <label className="search">
          <Icon name="search" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Escape') setSearch('');
            }}
            placeholder="Поиск по вопросу и ответу"
            aria-label="Поиск по журналу"
            maxLength={200}
          />
        </label>
        {selected.size ? (
          <>
            <button type="button" className="btn sm" onClick={() => mark('in_work')} disabled={busy}>
              <Icon name="progress" size="s" />В работу
            </button>
            <button type="button" className="btn sm" onClick={() => mark('reviewed')} disabled={busy}>
              <Icon name="circle-check" size="s" />
              Разобрано
            </button>
            <button type="button" className="btn sm only-d" onClick={() => mark('new')} disabled={busy}>
              <Icon name="arrow-back-up" size="s" />
              Вернуть в новые
            </button>
          </>
        ) : (
          <>
            <button
              type="button"
              className={`btn sm${extra ? ' on' : ''}`}
              onClick={() => setFiltersOpen(true)}
              aria-label="Фильтры журнала"
              title="Период, машина, механик, тип и статус случая"
            >
              <Icon name="filter" size="s" />
              <span className="only-d jl-wide">Фильтры</span>
              {extra ? <b className="m">{extra}</b> : null}
            </button>
            {/* Случаи, которые ждут разбора: новые и в работе. Повторы считаются одним случаем */}
            <button
              type="button"
              className={`btn sm gapf${onlyOpen ? ' on' : ''}${gapsOpen ? ' has' : ''}`}
              onClick={() => setFilter({ status: onlyOpen ? 'all' : 'open' })}
              disabled={!gapsOpen && !onlyOpen}
              aria-pressed={onlyOpen}
              title="Случаи, которые ждут разбора: новые и в работе"
            >
              <Icon name="alert-triangle" size="s" />
              <span className="only-d jl-wide">Требуют внимания</span>
              <b className="m">{gapsOpen}</b>
            </button>
            {/* Выгрузка журнала с тем же периодом, машиной и механиком. На телефоне — в панели фильтров */}
            <a
              className="btn sm only-d"
              href={exportUrl(filters)}
              download
              aria-label="Выгрузить журнал в xlsx"
              title="Выгрузить в xlsx: период, машина и механик как в фильтрах"
            >
              <Icon name="file-spreadsheet" size="s" />
              <span className="jl-wide">Выгрузить xlsx</span>
            </a>
            <button type="button" className="btn sm" onClick={() => load(false)} disabled={loading} aria-label="Обновить журнал" title="Обновить">
              <Icon name="refresh" size="s" className={loading ? 'spin' : ''} />
              <span className="jt-l">Обновить</span>
              {/* Где подписи «обновлено» нет (телефон, узкий экран), время стоит на кнопке */}
              {updatedAt ? <span className="jt-time m">{dateTime(updatedAt).split(' ')[1]}</span> : null}
            </button>
          </>
        )}
      </div>
      {error ? (
        <div className="box center">
          <ErrorState text={error} onRetry={() => load(false)} />
        </div>
      ) : !data ? (
        <div className="box center">
          <Loading text="Загружаю журнал…" />
        </div>
      ) : !data.items.length ? (
        <div className="box center">
          <Icon name={onlyOpen ? 'circle-check' : filtered ? 'search-off' : 'history'} size="xl" />
          {onlyOpen && extra === 0 && !filters.q ? (
            <>
              <div className="e1">Неразобранных случаев нет</div>
              <div>Все случаи разобраны.</div>
            </>
          ) : filtered ? (
            <>
              <div className="e1">Ничего не найдено</div>
              <div>Измените поиск или сбросьте фильтры</div>
              <button type="button" className="btn" onClick={reset}>
                <Icon name="x" />
                Сбросить фильтры
              </button>
            </>
          ) : (
            <>
              <div className="e1">Обращений пока нет</div>
              <div>Они появятся здесь после первого сообщения агенту.</div>
            </>
          )}
        </div>
      ) : (
        <>
          <div className="fit-area" ref={areaRef}>
            <div className="ftable jtable">
              <div className="lhead" data-head>
                <span className="jc-sel">
                  {cases.length ? (
                    <input type="checkbox" checked={allOnPage} onChange={toggleAll} aria-label="Выбрать все случаи на странице" />
                  ) : null}
                </span>
                <span>Время</span>
                <span>Машина</span>
                <span>Вопрос</span>
                <span>Ответ</span>
                <span>Источники</span>
                <span>Инструменты агента</span>
                <span className="ln">Время ответа</span>
                <span className="ln">Токены</span>
              </div>
              {data.items.map((it) => (
                <Row key={it.id} it={it} selected={selected.has(it.id)} onSelect={toggle} onOpen={(i) => setOpened(i.id)} />
              ))}
            </div>
          </div>
          {paged ? <Pager paged={paged} label="обращения" /> : null}
        </>
      )}
      {filtersView.shown && data ? (
        <FilterSheet
          filters={filters}
          facets={data.facets}
          leaving={filtersView.leaving}
          onChange={setFilter}
          onReset={reset}
          onClose={closeFilters}
        />
      ) : null}
      {caseView.shown ? <CaseSheet id={caseView.shown} leaving={caseView.leaving} onClose={closeCase} onChanged={changed} /> : null}
    </div>
  );
}
