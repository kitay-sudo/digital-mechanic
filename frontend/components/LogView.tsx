'use client';

import Link from 'next/link';
import { useCallback, useEffect, useState } from 'react';
import { api } from '@/lib/api';
import { dateTime, int, num, plural } from '@/lib/format';
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
  get_vehicle_history: 'история',
  search_manuals: 'поиск',
  read_manual_page: 'страница',
  prepare_ticket: 'черновик',
  submit_ticket: 'отправка',
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

/** Расход и инструменты: сверху время и токены числами, ниже метки инструментов. */
function Usage({ item }: { item: AuditItem }) {
  const u = item.usage;
  const tokens = u ? (u.input_tokens ?? 0) + (u.output_tokens ?? 0) : 0;
  const groups = toolGroups(item);
  return (
    <span className="lu">
      {u ? (
        <span className="lu-c">
          {u.duration_ms !== undefined ? (
            <span>
              <b className="m">{num(u.duration_ms / 1000, 1)}</b> с
            </span>
          ) : null}
          <span>
            <b className="m">{int(tokens)}</b> {plural(tokens, 'токен', 'токена', 'токенов')}
          </span>
        </span>
      ) : null}
      {groups.length ? (
        <span className="lu-t">
          {groups.map((g) => (
            <span key={g.label}>
              {g.label}
              {g.count > 1 ? <b className="m">×{g.count}</b> : null}
            </span>
          ))}
        </span>
      ) : (
        <span className="mut">без инструментов</span>
      )}
    </span>
  );
}

/** Журнал обращений: кто что спросил, что ответил агент и на какие страницы сослался. */
export function LogView() {
  const [items, setItems] = useState<AuditItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  // Страница не прокручивается: в таблице столько строк, сколько помещается, остальное листается
  const settings = useSettings();
  const { areaRef, pageSize } = useFitRows([settings.size, items]);
  const paged = usePaged(items ?? [], pageSize);

  const load = useCallback(() => {
    setError(null);
    setLoading(true);
    api
      .audit(100)
      .then((d) => setItems(d.items))
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

  return (
    <div className="body fit">
      {/* Отдельной полосы под шапкой нет: название, число обращений и обновление стоят в панели таблицы */}
      <div className="ftools">
        <div className="ft-t">
          <Icon name="history" size="s" />
          <b>Журнал обращений</b>
          {items ? <span className="ft-n">{items.length}</span> : null}
        </div>
        <button type="button" className="btn sm" onClick={load} disabled={loading}>
          <Icon name="refresh" size="s" className={loading ? 'spin' : ''} />
          Обновить
        </button>
      </div>
      {error ? (
        <div className="box center">
          <ErrorState text={error} onRetry={load} />
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
              <span>Расход и инструменты</span>
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
