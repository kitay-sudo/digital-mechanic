'use client';

import Link from 'next/link';
import { useCallback, useEffect, useState } from 'react';
import { api } from '@/lib/api';
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

/** Журнал обращений: кто что спросил, что ответил агент и на какие страницы сослался. */
export function LogView() {
  const [items, setItems] = useState<AuditItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Страница не прокручивается: в таблице столько строк, сколько помещается, остальное листается
  const settings = useSettings();
  const { areaRef, pageSize } = useFitRows([settings.size, items]);
  const paged = usePaged(items ?? [], pageSize);

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
        setItems((cur) => (cur && cur.length === d.items.length && cur.every((it, i) => it.id === d.items[i].id) ? cur : d.items));
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
      ) : !items.length ? (
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
                <div className="lrow" key={it.id} data-row>
                <span className="m lt">{dateTime(it.created_at)}</span>
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
                  <span className="lkind">
                    {KIND_LABEL[it.kind] ?? it.kind}
                    {it.ticket_id ? <span className="m"> · {it.ticket_id}</span> : null}
                  </span>
                  <span className="l2">{it.answer}</span>
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
