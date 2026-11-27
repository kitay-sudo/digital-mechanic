'use client';

import Link from 'next/link';
import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { dateTime } from '@/lib/format';
import { STATUS_LABEL, journalApi, type CaseCard, type CaseStatus } from '@/lib/journal';
import { useSettings } from '@/lib/settings';
import { Icon } from './Icon';
import { Loading } from './States';

const STATUS_ICON: Record<CaseStatus, string> = { new: 'circle-dot', in_work: 'progress', reviewed: 'circle-check' };

/** Статус разбора случая: новый, в работе, разобрано */
export function StatusChip({ status }: { status: CaseStatus }) {
  return (
    <span className={`jst st-${status}`}>
      <Icon name={STATUS_ICON[status]} size="s" />
      {STATUS_LABEL[status]}
    </span>
  );
}

function Section({ label, children }: { label: string; children: ReactNode }) {
  return (
    <section className="jc-s">
      <div className="sp-l">{label}</div>
      {children}
    </section>
  );
}

/** «Повторилось N раз» и где: время, машина, механик */
function Occurrences({ card }: { card: CaseCard }) {
  if (card.occurrences.length < 2) return null;
  return (
    <Section label={`Повторы: ${card.occurrences.length}`}>
      <div className="jc-t">
        <div className="jc-tr jc-th">
          <span>Время</span>
          <span>Машина</span>
          <span>Механик</span>
        </div>
        {card.occurrences.map((o) => (
          <div className="jc-tr" key={o.id}>
            <span className="m">{dateTime(o.created_at)}</span>
            <span className="m">{o.vehicle_id ?? '—'}</span>
            <span>{o.author ?? <span className="mut">не указан</span>}</span>
          </div>
        ))}
      </div>
    </Section>
  );
}

/**
 * Карточка случая: панель снизу по центру экрана. Полный вопрос, ответ агента, источники,
 * сообщения механика, повторы, история статуса, внизу — статус и комментарий к решению.
 */
export function CaseSheet({
  id,
  leaving,
  onClose,
  onChanged,
}: {
  id: string;
  leaving: boolean;
  onClose: () => void;
  onChanged: () => void;
}) {
  const settings = useSettings();
  const [card, setCard] = useState<CaseCard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<CaseStatus>('new');
  const [comment, setComment] = useState('');
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const load = useCallback(() => {
    setError(null);
    journalApi
      .card(id)
      .then((c) => {
        setCard(c);
        setStatus(c.status ?? 'new');
        setComment(c.comment);
      })
      .catch((e: Error) => setError(e.message));
  }, [id]);

  useEffect(load, [load]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const dirty = card ? status !== (card.status ?? 'new') || comment.trim() !== card.comment : false;

  const save = () => {
    if (!card) return;
    setSaving(true);
    setError(null);
    journalApi
      .setStatus({ ids: [card.id], status, comment: comment.trim(), reviewer: settings.mechanic.trim() || null })
      .then(() => {
        setSaved(true);
        onChanged();
        load();
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setSaving(false));
  };

  const d = card?.details;
  const who = card?.reviewer ?? null;

  return (
    <>
      <button type="button" className={`sp-dim${leaving ? ' leaving' : ''}`} aria-label="Закрыть карточку" onClick={onClose} />
      <aside className={`sp jsheet jcard${leaving ? ' leaving' : ''}`} role="dialog" aria-label="Карточка случая">
        <div className="handle">
          <i />
        </div>
        <div className="sp-h">
          <Icon name={card?.gap ? 'alert-triangle' : 'message-2'} className={card?.gap ? 'jc-warn' : ''} />
          <span className="jc-title">{card ? (card.gap?.label ?? 'Обращение') : 'Случай'}</span>
          {card?.status ? <StatusChip status={card.status} /> : null}
          <button type="button" className="hb" onClick={onClose} aria-label="Закрыть">
            <Icon name="x" />
          </button>
        </div>
        {!card ? (
          <div className="sp-b jc-b">{error ? <div className="alert">{error}</div> : <Loading text="Загружаю случай…" />}</div>
        ) : (
          <>
            <div className="sp-b jc-b">
              {/* Полная формулировка случая, если она что-то добавляет к подписи в заголовке */}
              {card.gap && card.gap.type !== 'no_answer' ? <div className="jc-gap">{card.gap.title}</div> : null}
              <Section label={card.source === 'admin' ? 'Сообщение механика' : 'Вопрос'}>
                <div className="jc-q">{card.question || <span className="mut">{card.photos ? 'Фото без текста' : 'Без текста'}</span>}</div>
                <div className="jc-meta">
                  <span>
                    <Icon name="clock" size="s" />
                    <span className="m">{dateTime(card.created_at)}</span>
                  </span>
                  {card.vehicle_id ? (
                    <Link href={`/v/${encodeURIComponent(card.vehicle_id)}`} className="llink">
                      <Icon name="truck" size="s" />
                      <span className="m">{card.vehicle_id}</span>
                      {card.vehicle_title && card.vehicle_title !== card.vehicle_id ? <span className="jc-sub">{card.vehicle_title}</span> : null}
                    </Link>
                  ) : (
                    <span className="mut">без машины</span>
                  )}
                  <span>
                    <Icon name="user" size="s" />
                    {card.author ?? <span className="mut">фамилия не указана</span>}
                  </span>
                  {card.photos ? (
                    <span>
                      <Icon name="photo" size="s" />
                      фото: <span className="m">{card.photos}</span>
                    </span>
                  ) : null}
                </div>
              </Section>
              {card.reports.length ? (
                <Section label={card.reports.length > 1 ? `Сообщения механиков: ${card.reports.length}` : 'Сообщение механика'}>
                  <div className="jc-list">
                    {card.reports.map((r, i) => (
                      <div className="jc-li" key={i}>
                        <b>{r.reason}</b>
                        {r.text ? <div>{r.text}</div> : null}
                        <div className="jc-by">
                          {r.author ?? 'фамилия не указана'}
                          <span className="m">{dateTime(r.created_at)}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </Section>
              ) : null}
              {card.source === 'answer' && d ? (
                <Section label="Ответ агента">
                  <div className="jc-a">{card.answer || d.summary || '—'}</div>
                  {d.anomaly_title ? <div className="jc-by">Тип неисправности: {d.anomaly_title}</div> : null}
                  {d.checks.length ? (
                    <ol className="jc-ol">
                      {d.checks.map((t, i) => (
                        <li key={`c${i}`}>{t}</li>
                      ))}
                    </ol>
                  ) : null}
                  {d.repair.length ? (
                    <>
                      <div className="jc-by">Ремонт</div>
                      <ol className="jc-ol">
                        {d.repair.map((t, i) => (
                          <li key={`r${i}`}>{t}</li>
                        ))}
                      </ol>
                    </>
                  ) : null}
                  {d.limitations.length ? (
                    <ul className="jc-ol jc-lim">
                      {d.limitations.map((t, i) => (
                        <li key={`l${i}`}>{t}</li>
                      ))}
                    </ul>
                  ) : null}
                  {d.recommendation_text ? <div className="jc-rec">{d.recommendation_text}</div> : null}
                  {d.warnings.map((w, i) => (
                    <div className="alert a-warn jc-w" key={`w${i}`}>
                      <Icon name="alert-triangle" />
                      <span>{w}</span>
                    </div>
                  ))}
                </Section>
              ) : null}
              {card.sources.length ? (
                <Section label="Источники">
                  <div className="ls">
                    {card.sources.map((s, i) => (
                      <span key={i}>
                        <Icon name="file-text" size="s" />
                        {s.short} <span className="mut">стр.</span> {s.pdf_page}
                      </span>
                    ))}
                  </div>
                </Section>
              ) : null}
              <Occurrences card={card} />
              {card.history.length ? (
                <Section label="История разбора">
                  <div className="jc-list">
                    {[...card.history].reverse().map((h, i) => (
                      <div className="jc-li" key={i}>
                        <span className="jc-hl">
                          <StatusChip status={h.status} />
                          <span>{h.reviewer ?? <span className="mut">без фамилии</span>}</span>
                          <span className="m mut">{dateTime(h.at)}</span>
                        </span>
                        {h.comment ? <div>{h.comment}</div> : null}
                      </div>
                    ))}
                  </div>
                </Section>
              ) : null}
            </div>
            {card.gap ? (
              <div className="jc-f">
                <textarea
                  className="inp pop-ta jc-ta"
                  value={comment}
                  onChange={(e) => {
                    setComment(e.target.value);
                    setSaved(false);
                  }}
                  placeholder="Комментарий к решению: что сделано, кому передано"
                  aria-label="Комментарий к решению"
                  maxLength={2000}
                  rows={2}
                />
                <div className="jc-act">
                  <div className="seg full" role="radiogroup" aria-label="Статус разбора">
                    {(['new', 'in_work', 'reviewed'] as CaseStatus[]).map((s) => (
                      <button
                        key={s}
                        type="button"
                        role="radio"
                        aria-checked={status === s}
                        className={status === s ? 'on' : ''}
                        onClick={() => {
                          setStatus(s);
                          setSaved(false);
                        }}
                      >
                        {STATUS_LABEL[s]}
                      </button>
                    ))}
                  </div>
                  <button type="button" className="btn pri" onClick={save} disabled={saving || !dirty}>
                    <Icon name={saved && !dirty ? 'check' : 'device-floppy'} />
                    {saved && !dirty ? 'Сохранено' : 'Сохранить'}
                  </button>
                </div>
                <div className="jc-hint">
                  {error ? (
                    <span className="jc-err">{error}</span>
                  ) : card.updated_at ? (
                    <>
                      Изменил {who ?? 'без фамилии'} <span className="m">{dateTime(card.updated_at)}</span>
                    </>
                  ) : settings.mechanic.trim() ? (
                    <>Решение подпишется фамилией из настроек: {settings.mechanic.trim()}</>
                  ) : (
                    <>Фамилию для подписи решения можно указать в настройках</>
                  )}
                  {card.repeats > 1 ? <span className="jc-all">отмечается вся группа повторов</span> : null}
                </div>
              </div>
            ) : null}
          </>
        )}
      </aside>
    </>
  );
}
