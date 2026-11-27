'use client';

import Link from 'next/link';
import { dateTime, num } from '@/lib/format';
import type { ManualTarget, Session, VehicleDetail } from '@/lib/types';
import { PriorityBadge, StatusBadge } from './Badges';
import { Icon } from './Icon';
import { historyHref } from './VehicleHistory';

/** Боковая панель чата: двигатель с руководствами, проверка в чате и переходы к истории машины. */
export function VehiclePanel({
  vehicle,
  session,
  onOpenManual,
  open,
  leaving = false,
  onClose,
  onWriteAdmin,
}: {
  vehicle: VehicleDetail;
  /** Проверка, которая сейчас в чате */
  session: Session | null;
  onOpenManual: (t: ManualTarget) => void;
  open: boolean;
  /** Шторка на телефоне закрывается: проигрывается анимация ухода */
  leaving?: boolean;
  onClose: () => void;
  /** Вопрос администратору не по конкретному ответу: нет нужного руководства, система ведёт себя странно */
  onWriteAdmin: () => void;
}) {
  const sid = session?.session_id ?? null;

  return (
    <aside className={`col side${open ? ' open' : ''}${leaving ? ' leaving' : ''}`}>
      <div className="handle">
        <i />
      </div>
      <div className="hdr">
        <Link href="/" className="hb only-d" aria-label="Назад к парку" title="К парку">
          <Icon name="arrow-left" />
        </Link>
        <div className="grow">
          <div className="h1">
            {vehicle.title} <span className="m">{vehicle.vehicle_id}</span>
          </div>
          <div className="sub">
            <span className="m">{vehicle.garage_no}</span> · {vehicle.vehicle_type}
          </div>
        </div>
        <div className="rt only-m">
          <button type="button" className="hb" onClick={onClose} aria-label="Закрыть">
            <Icon name="x" />
          </button>
        </div>
      </div>

      <div className="body">
        <div className="blk">
          <div className="sec">
            <b>
              <Icon name="engine" size="s" />
              Двигатель
            </b>
            {vehicle.priority ? <PriorityBadge priority={vehicle.priority} long /> : null}
          </div>
          <div className="vcard">
            <div className="eng">
              <b className="m">{vehicle.engine_model}</b>
              <span>{vehicle.fuel}</span>
            </div>
            <div className="mlist">
              {vehicle.manuals.length ? (
                vehicle.manuals.map((m) => (
                  <button
                    key={m.manual_id}
                    type="button"
                    className="src"
                    onClick={() => onOpenManual({ manual_id: m.manual_id, page: 1, short: m.short })}
                    title={`${m.designation}. ${m.title}. Страниц: ${m.pages}`}
                  >
                    <Icon name="book-2" size="s" />
                    {m.short}
                  </button>
                ))
              ) : (
                <span className="mut">руководства не подключены</span>
              )}
            </div>
          </div>
        </div>

        <div className="blk">
          <div className="sec">
            <b>
              <Icon name="message-2" size="s" />
              Проверка в чате
            </b>
          </div>
          <div className="slist">
            {session ? (
              // Тот же порядок, что у строки проверки на экране истории: номер и результат, под ними дата и оценка
              <div className="inchat">
                <span className="cid m">{session.session_id}</span>
                <span className="r">
                  <StatusBadge status={session.status} code={session.anomaly_type} />
                </span>
                <span className="cmeta m">{dateTime(session.checked_at)}</span>
                <span className="cmeta r">
                  {session.anomaly_score !== null ? (
                    <>
                      оценка <b className="m">{num(session.anomaly_score)}</b>
                    </>
                  ) : null}
                </span>
                {session.ticket_id ? (
                  <span className="cmeta ex">
                    <Icon name="clipboard-check" size="s" />
                    заявка <b className="m">{session.ticket_id}</b>
                  </span>
                ) : null}
              </div>
            ) : (
              <div className="trow mut">Проверок нет</div>
            )}
            <Link href={historyHref(vehicle.vehicle_id, 'checks', sid)} className="navrow">
              <Icon name="history" />
              <span>Все проверки и график</span>
              <span className="m">{vehicle.sessions.length}</span>
              <Icon name="chevron-right" />
            </Link>
            <Link href={historyHref(vehicle.vehicle_id, 'tickets', sid)} className="navrow">
              <Icon name="clipboard-list" />
              <span>Заявки по машине</span>
              <span className="m">{vehicle.tickets.length}</span>
              <Icon name="chevron-right" />
            </Link>
            <button type="button" className="navrow" onClick={onWriteAdmin}>
              <Icon name="message-circle" />
              <span>Написать администратору</span>
              <span />
              <Icon name="chevron-right" />
            </button>
          </div>
        </div>
      </div>
    </aside>
  );
}
