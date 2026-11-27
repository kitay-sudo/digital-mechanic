'use client';

import Link from 'next/link';
import { useCallback, useEffect, useState } from 'react';
import { GAPS_EVENT, api } from '@/lib/api';
import { dateTime, int, num } from '@/lib/format';
import { useFitRows, usePaged } from '@/lib/paging';
import { useSettings } from '@/lib/settings';
import type { AuditItem, MessageKind } from '@/lib/types';
import { Icon } from './Icon';
import { Pager } from './Pager';
import { ErrorState, Loading } from './States';

const KIND_LABEL: Record<MessageKind, string> = {
  verdict: 'Вердикт',
  answer: 'Ответ',
  ticket_draft: 'Черновик заявки',
  ticket_created: 'Заявка создана',
  notice: 'Сообщение',
};

const TOOL_LABEL: Record<string, string> = {
  get_diagnosis: 'диагностика',
  get_vehicle_history: 'история машины',
  search_manuals: 'поиск в руководствах',
  read_manual_page: 'страница руководства',
  prepare_ticket: 'черновик заявки',
  submit_ticket: 'отправка заявки',
};

function Sources({ item }: { item: AuditItem }) {
  if (!item.sources.length) return <span className="ls mut">нет</span>;
  return (
    <span className="ls">
      {item.sources.map((s, i) => (
        <span key={i}>
          <Icon name="file-text" size="s" />
          {s.short} · стр. {s.pdf_page}
        </span>
      ))}
    </span>
  );
}

/** Инструменты обращения в порядке первого вызова; повторные вызовы сложены в счётчик. */
function toolGroups(item: AuditItem): { label: string; count: number }[] {
  const groups = new Map<string, number>();
  for (const t of item.tools) {
    const label = TOOL_LABEL[t] ?? t;
    groups.set(label, (groups.get(label) ?? 0) + 1);
  }
  return [...groups].map(([label, count]) => ({ label, count }));
}

/** Три колонки строки: что вызывал агент (по одному инструменту в строке), время ответа и токены числами. */
function Usage({ item }: { item: AuditItem }) {
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
          <span className="mut">не вызывал</span>
        )}
      </span>
      <span className="ln m">{u?.duration_ms !== undefined ? `${num(u.duration_ms / 1000, 1)} с` : '—'}</span>
      <span className="ln m">{u ? int((u.input_tokens ?? 0) + (u.output_tokens ?? 0)) : '—'}</span>
    </>
  );
}

/** Как часто журнал перечитывается с сервера, мс */
const REFRESH_MS = 10_000;

const isOpenGap = (it: AuditItem) => Boolean(it.gap && !it.gap.reviewed_at);


/** Кнопка «Разобрано» у случая для администратора */
function GapMark({ item, onReview }: { item: AuditItem; onReview: (item: AuditItem) => void }) {
  const gap = item.gap;
  if (!gap) return null;
  const done = Boolean(gap.reviewed_at);
  return (
    <button
      type="button"
      className={`lrev${done ? ' done' : ''}`}
      onClick={() => onReview(item)}
      aria-pressed={done}
      title={done ? `Разобрано ${dateTime(gap.reviewed_at ?? '')}. Нажмите, чтобы вернуть в работу` : 'Отметить разобранным'}
    >
      <Icon name={done ? 'circle-check' : 'square'} size="s" />
      {done ? 'разобрано' : 'Разобрано'}
    </button>
  );
}

/** Журнал обращений: кто что спросил, что ответил агент и на какие страницы сослался. */
export function LogView() {
  const [items, setItems] = useState<AuditItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  /** Показывать только случаи без ответа, которые администратор ещё не разобрал */
  const [onlyGaps, setOnlyGaps] = useState(false);
  const rows = items ? (onlyGaps ? items.filter(isOpenGap) : items) : [];
  const gapsOpen = items ? items.filter(isOpenGap).length : 0;
  // Страница не прокручивается: в таблице столько строк, сколько помещается, остальное листается
  const settings = useSettings();
  const { areaRef, pageSize } = useFitRows([settings.size, items, onlyGaps]);
  const paged = usePaged(rows, pageSize);

  const [loading, setLoading] = useState(false);
  /** Когда журнал последний раз получен с сервера */
  const [updatedAt, setUpdatedAt] = useState<string | null>(null);

  /** quiet — фоновое обновление: список на экране не трогаем, пока не пришёл новый, сбой связи не показываем */
  const load = useCallback((quiet: boolean) => {
    if (!quiet) {
      setError(null);
      setLoading(true);
    }
    api
      .audit(100)
      .then((d) => {
        setError(null);
        setUpdatedAt(new Date().toISOString());
        // Тот же список не перерисовываем: строки и открытая страница остаются на месте
        setItems((cur) =>
          cur &&
          cur.length === d.items.length &&
          cur.every((it, i) => it.id === d.items[i].id && (it.gap?.reviewed_at ?? null) === (d.items[i].gap?.reviewed_at ?? null))
            ? cur
            : d.items,
        );
      })
      .catch((e: Error) => {
        if (!quiet) setError(e.message);
      })
      .finally(() => {
        if (!quiet) setLoading(false);
      });
  }, []);

  // Журнал обновляется сам в фоне: раз в REFRESH_MS, пока вкладка на экране, и сразу при возврате на неё.
  // Кнопка «Обновить» остаётся для обновления вручную
  useEffect(() => {
    load(false);
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

  const review = useCallback((item: AuditItem) => {
    const reviewed = !item.gap?.reviewed_at;
    api
      .reviewGap(item.id, reviewed)
      .then((r) => {
        setItems((list) =>
          list ? list.map((it) => (it.id === item.id && it.gap ? { ...it, gap: { ...it.gap, reviewed_at: r.reviewed_at } } : it)) : list,
        );
        window.dispatchEvent(new Event(GAPS_EVENT));
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  return (
    <div className="body fit">
      {/* Отдельной полосы под шапкой нет: название, число обращений, время обновления и кнопка стоят в панели таблицы */}
      <div className="ftools">
        <div className="ft-t">
          <Icon name="history" size="s" />
          {/* На телефоне панель в одну строку: длинные подписи туда не помещаются */}
          <b>
            Журнал<span className="only-d"> обращений</span>
          </b>
          {items ? <span className="ft-n">{items.length}</span> : null}
        </div>
        {updatedAt ? (
          <span className="ft-hint" title="Журнал обновляется сам каждые 10 секунд">
            <span className="only-d">обновлено </span>
            <span className="m">{dateTime(updatedAt)}</span>
          </span>
        ) : null}
        {/* Вопросы без ответа в руководстве: администратор разбирает и отмечает их (Q&A с заказчиком 27.11) */}
        <button
          type="button"
          className={`btn sm gapf${onlyGaps ? ' on' : ''}${gapsOpen ? ' has' : ''}`}
          onClick={() => setOnlyGaps((v) => !v)}
          disabled={!gapsOpen && !onlyGaps}
          aria-pressed={onlyGaps}
          title="Вопросы, на которые в руководстве нет ответа, и сбои базы знаний: показать только неразобранные"
        >
          <Icon name="alert-triangle" size="s" />
          <span className="only-d">Требуют внимания</span>
          <b className="m">{gapsOpen}</b>
        </button>
        <button type="button" className="btn sm" onClick={() => load(false)} disabled={loading} aria-label="Обновить журнал" title="Обновить">
          <Icon name="refresh" size="s" className={loading ? 'spin' : ''} />
          <span className="only-d">Обновить</span>
        </button>
      </div>
      {error ? (
        <div className="box center">
          <ErrorState text={error} onRetry={() => load(false)} />
        </div>
      ) : !items ? (
        <div className="box center">
          <Loading text="Загружаю журнал…" />
        </div>
      ) : !rows.length && onlyGaps ? (
        <div className="box center">
          <Icon name="circle-check" size="xl" />
          <div className="e1">Неразобранных случаев нет</div>
          <div>Все вопросы без ответа в руководстве отмечены разобранными.</div>
        </div>
      ) : !rows.length ? (
        <div className="box center">
          <Icon name="history" size="xl" />
          <div className="e1">Обращений пока нет</div>
          <div>Они появятся здесь после первого сообщения агенту.</div>
        </div>
      ) : (
        <>
          <div className="fit-area" ref={areaRef}>
            <div className="ftable">
              <div className="lhead" data-head>
              <span>Время</span>
              <span>Машина</span>
              <span>Вопрос</span>
              <span>Ответ</span>
              <span>Источники</span>
              <span>Инструменты агента</span>
              <span className="ln">Время ответа</span>
              <span className="ln">Токены</span>
            </div>
              {paged.rows.map((it) => (
                <div className={`lrow${isOpenGap(it) ? ' gap' : ''}`} key={it.id} data-row>
                <span className="lt">
                  <span className="m">{dateTime(it.created_at)}</span>
                  {/* Кто из механиков спрашивал: смены */}
                  {it.author ? <span className="l2 lwho">{it.author}</span> : null}
                  <GapMark item={it} onReview={review} />
                </span>
                <span className="lv">
                  <Link href={`/v/${encodeURIComponent(it.vehicle_id)}`} className="llink m">
                    {it.vehicle_id}
                  </Link>
                  <span className="l2">
                    {it.vehicle_title}
                    {it.session_id ? ` · ${it.session_id}` : ''}
                  </span>
                </span>
                <span className="lq">{it.question}</span>
                <span className="la">
                  {it.gap ? (
                    <span className={`lkind lgap${it.gap.reviewed_at ? ' done' : ''}`} title={it.gap.title}>
                      <Icon name="alert-triangle" size="s" />
                      {it.gap.label}
                    </span>
                  ) : (
                    <span className="lkind">
                      {KIND_LABEL[it.kind] ?? it.kind}
                      {it.ticket_id ? <span className="m"> · {it.ticket_id}</span> : null}
                    </span>
                  )}
                  {/* Сообщение механика в поддержку важнее текста ответа: администратор видит, что не так */}
                  <span className="l2">
                    {it.report
                      ? `${it.report.reason}${it.report.text ? `: ${it.report.text}` : ''}${it.report.author ? ` (${it.report.author})` : ''}`
                      : it.answer}
                  </span>
                </span>
                <Sources item={it} />
                <Usage item={it} />
              </div>
              ))}
            </div>
          </div>
          <Pager paged={paged} label="обращения" />
        </>
      )}
    </div>
  );
}
