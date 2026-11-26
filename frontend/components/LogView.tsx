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

function tools(item: AuditItem): string {
  if (!item.tools.length) return 'без инструментов';
  return item.tools.map((t) => TOOL_LABEL[t] ?? t).join(' → ');
}

function cost(item: AuditItem): string {
  const u = item.usage;
  if (!u) return '';
  const tokens = (u.input_tokens ?? 0) + (u.output_tokens ?? 0);
  const parts = [`${int(tokens)} ${plural(tokens, 'токен', 'токена', 'токенов')}`];
  if (u.duration_ms !== undefined) parts.push(`${num(u.duration_ms / 1000, 1)} с`);
  return parts.join(' · ');
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
    <>
      <div className="fbar lbar">
        <div className="h1">Журнал</div>
        <span className="st only-d">Обращения к агенту: вопрос, ответ, источники, инструменты</span>
        <button type="button" className="btn lrefresh" onClick={load} disabled={loading}>
          <Icon name="refresh" className={loading ? 'spin' : ''} />
          Обновить
        </button>
      </div>
      {error ? (
        <ErrorState text={error} onRetry={load} />
      ) : !items ? (
        <Loading text="Загружаю журнал…" />
      ) : !items.length ? (
        <div className="center">
          <Icon name="history" size="xl" />
          <div className="e1">Обращений пока нет</div>
          <div>Они появятся здесь после первого сообщения агенту.</div>
        </div>
      ) : (
        <div className="body fit">
          <div className="fit-area" ref={areaRef}>
            <div className="ftable">
              <div className="lhead" data-head>
              <span>Время</span>
              <span>Машина</span>
              <span>Вопрос</span>
              <span>Ответ</span>
              <span>Источники</span>
              <span>Инструменты и расход</span>
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
                <span className="lu">
                  <span>{tools(it)}</span>
                  <span className="l2 m">{cost(it)}</span>
                </span>
              </div>
              ))}
            </div>
          </div>
          <Pager paged={paged} label="обращения" />
        </div>
      )}
    </>
  );
}
