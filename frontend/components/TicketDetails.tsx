'use client';

import Link from 'next/link';
import type { Manual, ManualTarget, Ticket } from '@/lib/types';
import { PriorityBadge } from './Badges';
import { Icon } from './Icon';
import { RefChip, sameTarget } from './RefChip';

/** Работы и шаги по порядку — маршрутом: номера на одной линии, как «Ход разбора». */
export function Road({ items }: { items: React.ReactNode[] }) {
  return (
    <ol className="road">
      {items.map((item, i) => (
        <li key={i}>
          <span className="n m">{i + 1}</span>
          <div className="tx">{item}</div>
        </li>
      ))}
    </ol>
  );
}

/**
 * Состав заявки — один вид в чате и в истории машины: поля таблицей, как в карточке результата,
 * работы маршрутом, запчасти списком, источники короткими ссылками на страницы.
 */
export function TicketDetails({
  t,
  manuals,
  chatHref,
  activeManual = null,
  onOpenManual,
}: {
  t: Ticket;
  /** Руководства машины: по ним длинное название документа в заявке становится коротким «РЭ ЗМЗ-409» */
  manuals: Manual[];
  /** Ссылка в чат с этой проверкой (в истории машины) */
  chatHref?: string;
  activeManual?: ManualTarget | null;
  /** В чате ссылки на страницы открывают руководство рядом */
  onOpenManual?: (target: ManualTarget) => void;
}) {
  const refs = t.references.map((r) => {
    const m = manuals.find((x) => x.designation === r.manual || x.title === r.manual || x.manual_id === r.manual);
    return { manual_id: m?.manual_id ?? null, short: m?.short ?? r.manual, page: r.pdf_page };
  });
  return (
    <div className="tdet">
      <div className="kv">
        <div>Диагноз</div>
        <div>{t.conclusion}</div>
        <div>Приоритет</div>
        <div>
          <PriorityBadge priority={t.urgency} />
        </div>
        <div>Работы</div>
        <div>
          <Road items={t.operations} />
        </div>
        <div>Запчасти</div>
        <div>
          {t.spare_parts.length ? (
            <ul className="plain">
              {t.spare_parts.map((p, i) => (
                <li key={i}>{p}</li>
              ))}
            </ul>
          ) : (
            <span className="mut">не нужны</span>
          )}
        </div>
        <div>Источники</div>
        <div>
          <div className="chips">
            {refs.map((r, i) => {
              if (r.manual_id && onOpenManual) {
                const target: ManualTarget = { manual_id: r.manual_id, page: r.page, short: r.short };
                return (
                  <RefChip key={i} target={target} label={r.short} active={sameTarget(activeManual, target)} onOpen={onOpenManual} />
                );
              }
              return (
                <span key={i} className="src static">
                  <Icon name="file-text" size="s" />
                  {r.short}
                  <span className="pg">стр. {r.page}</span>
                </span>
              );
            })}
          </div>
        </div>
      </div>
      {chatHref ? (
        <Link href={chatHref} className="navrow tgo">
          <Icon name="message-2" />
          <span>Проверка {t.session_id} в чате</span>
          <span />
          <Icon name="chevron-right" />
        </Link>
      ) : null}
    </div>
  );
}
