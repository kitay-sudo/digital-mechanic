'use client';

import { useEffect, useState, type ReactNode } from 'react';
import { api } from '@/lib/api';
import { PRIORITY_LABEL, QUALITY_LABEL, capitalize, dateTime, int, num, plural, timeShort } from '@/lib/format';
import type {
  Answer,
  AnswerItem,
  Assessment,
  Conflict,
  Draft,
  ManualTarget,
  Marks,
  Message,
  Priority,
  Ref,
  Report,
  Step,
  Ticket,
  Usage,
  VehicleDetail,
} from '@/lib/types';
import { PriorityBadge, StatusBadge } from './Badges';
import { Icon } from './Icon';
import { RefChip, sameTarget } from './RefChip';

interface Ctx {
  vehicle: VehicleDetail;
  busy: boolean;
  activeManual: ManualTarget | null;
  onOpenManual: (t: ManualTarget) => void;
  /** Отметки «сделано» по шагам: общие для всех механиков машины */
  marks: Marks;
  onToggleStep: (key: string, index: number) => void;
}

const refTarget = (r: Ref): ManualTarget => ({ manual_id: r.manual_id, page: r.pdf_page, quote: r.quote, short: r.short });

function Chips({ refs, ctx }: { refs: Ref[]; ctx: Ctx }) {
  if (!refs.length) return null;
  return (
    <div className="chips">
      {refs.map((r, i) => {
        const t = refTarget(r);
        return <RefChip key={`${r.manual_id}-${r.pdf_page}-${i}`} target={t} label={r.short} active={sameTarget(ctx.activeManual, t)} onOpen={ctx.onOpenManual} />;
      })}
    </div>
  );
}

/* ---------- Расхождение в руководствах ---------- */

const LETTERS = 'АБВГДЕЖЗ';

function DisputedMark() {
  return (
    <div className="dsp">
      <Icon name="alert-triangle" size="s" />
      По этому условию документы расходятся
    </div>
  );
}

const upperFirst = (t: string) => t.charAt(0).toUpperCase() + t.slice(1);

function ConflictBlocks({ conflicts, ctx }: { conflicts: Conflict[]; ctx: Ctx }) {
  return (
    <>
      {conflicts.map((c, n) => (
        <div className="cdiv" key={n}>
          <section className="cfl">
            <div className="sec">
              <b>
                <Icon name="alert-triangle" size="s" />
                Расхождение в руководствах
              </b>
              <span className="cfl-tag">формулировок: {c.statements.length}</span>
            </div>
            <div className="cfl-topic">{c.topic}</div>
            <div className="items">
              {c.statements.map((s, i) => (
                <div className="item" key={i}>
                  <span className="ltr">{LETTERS[i] ?? i + 1}</span>
                  <div>
                    {s.text ? <div className="cfl-say">{s.text}</div> : null}
                    <div className="tx">«{s.ref.quote}»</div>
                    <Chips refs={[s.ref]} ctx={ctx} />
                  </div>
                </div>
              ))}
            </div>
            {/* Согласованное решение заменяет общий совет: механику нужен один ответ, что делать */}
            <div className="cfl-how">
              <div className="cfl-hl">
                <Icon name={c.resolution ? 'circle-check' : 'arrow-right'} size="s" />
                Как поступить
              </div>
              <div className="cfl-ht">{c.resolution || c.recommendation}</div>
              {c.resolution && c.resolution_source ? <div className="cfl-src">{upperFirst(c.resolution_source)}</div> : null}
            </div>
          </section>
        </div>
      ))}
    </>
  );
}

/* ---------- Шаги агента ---------- */

const STEP_ICON: Record<Step['status'], string> = { running: 'loader-2', done: 'circle-check', error: 'alert-circle' };

function StepList({ steps }: { steps: Step[] }) {
  return (
    <ul className="steps">
      {steps.map((s) => (
        <li key={s.id} className={s.status === 'error' ? 'err' : s.status === 'done' ? 'ok' : ''}>
          <Icon name={STEP_ICON[s.status]} className={s.status === 'running' ? 'spin' : ''} />
          <span>
            {s.title}
            {s.detail ? <span className="dt">{s.detail}</span> : null}
          </span>
        </li>
      ))}
    </ul>
  );
}

/** Шаги во время хода: видно, что агент делает прямо сейчас. */
export function PendingSteps({ steps }: { steps: Step[] }) {
  return (
    <div className="a">
      <div className="who">
        <Icon name="engine" size="s" />
        Цифровой механик
      </div>
      <div className="card strip">
        <div className="pending">
          <div className="ph">
            <span className="dots">
              <i />
              <i />
              <i />
            </span>
            {steps.length ? 'Агент работает' : 'Агент думает…'}
          </div>
          {steps.length ? <StepList steps={steps} /> : null}
        </div>
      </div>
    </div>
  );
}

function usageLine(usage: Usage | null | undefined): string {
  if (!usage) return '';
  const parts = [`${int(usage.input_tokens + usage.output_tokens)} ${plural(usage.input_tokens + usage.output_tokens, 'токен', 'токена', 'токенов')}`];
  parts.push(`${num(usage.cost_rub)} ₽`);
  parts.push(`${num(usage.duration_ms / 1000, 1)} с`);
  return parts.join(' · ');
}

function StepsFold({ steps, usage }: { steps?: Step[]; usage?: Usage | null }) {
  if (!steps?.length && !usage) return null;
  const count = steps?.length ?? 0;
  return (
    <details className="fold cdiv">
      <summary>
        <Icon name="chevron-right" />
        <span>
          Ход разбора{count ? ` · ${count} ${plural(count, 'шаг', 'шага', 'шагов')}` : ''}
          <span className="usub only-m">{usageLine(usage)}</span>
        </span>
        <span className="rt">
          {usageLine(usage)}
          {usage?.mock ? ' · заглушка' : ''}
        </span>
      </summary>
      <div className="fin">
        {steps?.length ? <StepList steps={steps} /> : null}
        {usage ? (
          <div className="st m" style={{ marginTop: 8 }}>
            модель {usage.model} · вызовов {usage.llm_calls} · вход {int(usage.input_tokens)} · выход {int(usage.output_tokens)}
          </div>
        ) : null}
      </div>
    </details>
  );
}

/* ---------- Блоки ответа: наблюдения, гипотезы, проверки, ремонт, ограничения ---------- */

/** Шаги по руководству с отметкой «сделано»: механик идёт по списку и отмечает. */
function StepItems({
  title,
  icon,
  items,
  ctx,
  storeKey,
  after,
}: {
  title: string;
  icon: string;
  items: AnswerItem[];
  ctx: Ctx;
  storeKey: string;
  after?: (allDone: boolean) => ReactNode;
}) {
  const marks = ctx.marks[storeKey] ?? {};
  const done = Object.keys(marks).map(Number);
  const doneCount = done.filter((i) => i < items.length).length;
  const allDone = doneCount === items.length;
  return (
    <section className="ab cdiv">
      <div className="sec">
        <b>
          <Icon name={icon} size="s" />
          {title}
        </b>
        <span className={`prog${allDone ? ' all' : ''}`}>
          {/* На телефоне слово убрано, чтобы подпись раздела не переносилась на вторую строку */}
          <span className="only-d">Сделано </span>
          {doneCount} из {items.length}
        </span>
      </div>
      <div className="items">
        {items.map((it, i) => {
          const isDone = done.includes(i);
          return (
            <div className={`item${isDone ? ' done' : ''}`} key={i}>
              <button
                type="button"
                className="chk"
                aria-pressed={isDone}
                aria-label={isDone ? `Шаг ${i + 1} сделан. Снять отметку` : `Отметить шаг ${i + 1} сделанным`}
                title={isDone ? 'Сделано. Нажмите, чтобы снять отметку' : 'Отметить, что шаг сделан'}
                onClick={() => ctx.onToggleStep(storeKey, i)}
              >
                {isDone ? <Icon name="check" /> : i + 1}
              </button>
              <div>
                <div className="tx">{it.text}</div>
                {/* Кто отметил и когда: сменщик видит, на чём остановились */}
                {isDone ? (
                  <div className="byline">
                    Сделано: {marks[String(i)]?.author ? `${marks[String(i)].author}, ` : ''}
                    {dateTime(marks[String(i)].at)}
                  </div>
                ) : null}
                {it.disputed ? <DisputedMark /> : null}
                <Chips refs={it.refs} ctx={ctx} />
              </div>
            </div>
          );
        })}
      </div>
      {after ? after(allDone) : null}
    </section>
  );
}

/**
 * Вывод агента. Если в нём шаги по порядку («1) … 2) … 3) …»), каждый шаг — своей строкой:
 * так ответ «что делать» читается с телефона, а не одним абзацем.
 */
function SummaryText({ text }: { text: string }) {
  const parts = text.split(/\s(?=\d\)\s)/);
  if (parts.length < 3 || !/^\d\)\s/.test(parts[1])) return <>{text}</>;
  const [lead, ...steps] = parts;
  return (
    <>
      {lead.trim() ? <div>{lead.trim()}</div> : null}
      <ol className="sumsteps">
        {steps.map((step, i) => (
          <li key={i}>
            <span className="n m">{i + 1}</span>
            <span>{step.replace(/^\d\)\s/, '')}</span>
          </li>
        ))}
      </ol>
    </>
  );
}

function AnswerBlocks({
  answer,
  ctx,
  showSummary,
  messageId,
  onCreateTicket,
}: {
  answer: Answer;
  ctx: Ctx;
  showSummary?: boolean;
  messageId: string;
  /** Задан, когда заявку можно создавать: после всех проверок появится подсказка */
  onCreateTicket?: () => void;
}) {
  return (
    <>
      {showSummary && answer.summary ? (
        <div className="cpad">
          <div className="vtext" style={{ color: 'var(--tx)' }}>
            <SummaryText text={answer.summary} />
          </div>
        </div>
      ) : null}
      {answer.not_found ? (
        <div className={`notfound${showSummary && answer.summary ? ' cdiv' : ''}`}>
          <Icon name="book-off" />
          <div>
            <b>В руководстве этого двигателя ответа нет.</b> Данные других двигателей агент не использует.
          </div>
        </div>
      ) : null}
      {answer.conflicts?.length ? <ConflictBlocks conflicts={answer.conflicts} ctx={ctx} /> : null}
      {answer.observations.length ? (
        <section className="ab cdiv">
          <div className="sec">
            <b>
              <Icon name="eye" size="s" />
              Наблюдения
            </b>
          </div>
          <ul className="plain">
            {answer.observations.map((t, i) => (
              <li key={i}>{t}</li>
            ))}
          </ul>
        </section>
      ) : null}
      {answer.hypotheses.length ? (
        // Предположения агента — тот же вид раздела, отличие сказано словами под заголовком
        <section className="ab cdiv hyp">
          <div className="sec">
            <b>
              <Icon name="bulb" size="s" />
              Гипотезы
            </b>
          </div>
          <div className="hyp-note">Предположения агента. В руководстве этого нет: подтверждайте проверками по шагам.</div>
          <ul className="plain">
            {answer.hypotheses.map((t, i) => (
              <li key={i}>{t}</li>
            ))}
          </ul>
        </section>
      ) : null}
      {answer.checks.length ? (
        <StepItems
          title="Проверки по руководству"
          icon="list-check"
          items={answer.checks}
          ctx={ctx}
          storeKey={`${messageId}:checks`}
          after={(allDone) =>
            allDone && onCreateTicket ? (
              <div className="nextstep">
                <Icon name="circle-check" />
                <span>Все проверки отмечены. Можно оформлять заявку на дефектовку.</span>
                <button type="button" className="btn pri" onClick={onCreateTicket} disabled={ctx.busy}>
                  <Icon name="clipboard-list" />
                  Создать заявку
                </button>
              </div>
            ) : null
          }
        />
      ) : null}
      {answer.repair.length ? (
        <StepItems title="Возможный ремонт" icon="tool" items={answer.repair} ctx={ctx} storeKey={`${messageId}:repair`} />
      ) : null}
      {answer.limitations.length ? (
        <section className="ab cdiv lim">
          <div className="sec">
            <b>
              <Icon name="alert-circle" size="s" />
              Ограничения
            </b>
          </div>
          <ul className="plain">
            {answer.limitations.map((t, i) => (
              <li key={i}>{t}</li>
            ))}
          </ul>
        </section>
      ) : null}
    </>
  );
}

function CopyBlock({ text, title = 'Рекомендация на дефектовку' }: { text: string; title?: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };
  return (
    <div className="reco">
      <div className="rh">
        <span className="sec" style={{ minHeight: 0 }}>
          <b>
            <Icon name="clipboard-text" size="s" />
            {title}
          </b>
        </span>
        <button type="button" className="btn sm" onClick={copy}>
          <Icon name={copied ? 'check' : 'copy'} size="s" />
          {copied ? 'Скопировано' : 'Скопировать'}
        </button>
      </div>
      <pre>{text}</pre>
    </div>
  );
}

/* ---------- Вердикт ---------- */

function verdictTone(a: Assessment | null | undefined): string {
  if (a?.outcome === 'normal') return ' v-ok';
  if (!a || a.outcome !== 'anomaly' || a.flags.engine_mismatch) return '';
  return a.priority === 'high' ? ' v-h' : a.priority === 'low' ? ' v-l' : ' v-m';
}

function VerdictCard({ m, ctx, onCreateTicket }: { m: Message; ctx: Ctx; onCreateTicket: () => void }) {
  const d = m.diagnosis;
  const a = m.assessment;
  const outcome = a?.outcome ?? d?.status ?? 'normal';
  const mismatch = Boolean(a?.flags.engine_mismatch);
  const title = mismatch
    ? 'Результат не подходит двигателю машины'
    : outcome === 'anomaly'
      ? (d?.anomaly_title ?? 'Отклонение')
      : outcome === 'check_failed'
        ? 'Запись непригодна для анализа'
        : 'Отклонений не найдено';
  const lowConf = d && a && d.confidence !== null && d.confidence < a.confidence_min;

  return (
    <div className={`card strip${verdictTone(a)}`}>
      <div className="cpad">
        <div className="row1">
          <StatusBadge status={outcome} code={d?.anomaly_type} mismatch={mismatch} />
          {a?.priority ? <PriorityBadge priority={a.priority} long /> : null}
        </div>
        <div className="vtitle">{title}</div>
        {m.text ? (
          <div className="vtext">
            <SummaryText text={m.text} />
          </div>
        ) : null}
        {a?.warnings.length ? (
          <div className="warns">
            {a.warnings.map((w, i) => (
              <div className="alert a-warn" key={i}>
                <Icon name="alert-triangle" />
                <div>{w}</div>
              </div>
            ))}
          </div>
        ) : null}
      </div>

      {a?.priority && a.priority_action ? (
        <div className="cdiv">
          <div className="cpad" style={{ paddingBottom: 4 }}>
            <div className="pact">
              <Icon name="flag" size="l" className={a.priority === 'high' ? 'c-h' : a.priority === 'low' ? 'c-l' : 'c-m'} />
              <div>
                <div className="pl">Что делать</div>
                <div className="pa">{a.priority_action}</div>
              </div>
            </div>
          </div>
          <details className="fold">
            <summary>
              <Icon name="chevron-right" />
              На чём основан приоритет
            </summary>
            <div className="fin">
              <ul className="basis">
                {a.basis.map((b, i) => (
                  <li key={i}>{b}</li>
                ))}
              </ul>
            </div>
          </details>
        </div>
      ) : null}

      {d ? (
        <div className="cdiv">
          <div className="kv">
            <div>
              <span>
                Оценка
                <span className="only-d">&nbsp;отклонения</span>
              </span>
            </div>
            <div className={`m${outcome === 'anomaly' && !mismatch ? ' over' : ''}`}>{num(d.anomaly_score)}</div>
            <div>
              <span>
                Уверенность
                <span className="only-d">&nbsp;модели</span>
              </span>
            </div>
            <div>
              <span className={`m${lowConf ? ' over' : ''}`}>{num(d.confidence)}</span>
              {a && d.confidence !== null ? (
                <span className="st">
                  порог для заявки <span className="m">{num(a.confidence_min)}</span>
                </span>
              ) : null}
            </div>
            <div>
              <span>
                Качество
                <span className="only-d">&nbsp;записи</span>
              </span>
            </div>
            <div className={d.signal_quality === 'good' ? '' : 'over'}>{QUALITY_LABEL[d.signal_quality]}</div>
            <div>Признаки</div>
            <div>{d.description}</div>
            <div>Проверка</div>
            <div className="m">
              {d.session_id} · {dateTime(d.checked_at)} · {d.model_version}
            </div>
          </div>
        </div>
      ) : null}

      {m.answer ? (
        <AnswerBlocks answer={m.answer} ctx={ctx} messageId={m.id} onCreateTicket={a?.ticket_allowed ? onCreateTicket : undefined} />
      ) : null}

      {m.answer?.recommendation_text ? (
        <div className="cdiv" style={{ paddingTop: 16 }}>
          <CopyBlock text={m.answer.recommendation_text} title={mismatch ? 'Сообщение о расхождении данных' : undefined} />
        </div>
      ) : null}

      {/* Кнопка «Создать заявку» постоянно стоит в панели ввода. В карточке — только причина, если заявка недоступна */}
      {!a?.ticket_allowed && a?.ticket_block_reason ? (
        <div className="cfoot">
          <div className="cap">
            <Icon name="lock" />
            <span>
              <b style={{ fontWeight: 600, color: 'var(--tx)' }}>Заявка недоступна.</b> {a.ticket_block_reason}
            </span>
          </div>
        </div>
      ) : null}

      <StepsFold steps={m.steps} usage={m.usage} />
    </div>
  );
}

/* ---------- Заявка ---------- */

const URGENCY: Priority[] = ['low', 'medium', 'high'];

function WorkList({ items, ctx, empty }: { items: AnswerItem[]; ctx: Ctx; empty: string }) {
  if (!items.length) return <span className="mut">{empty}</span>;
  return (
    <div className="wks">
      {items.map((it, i) => (
        <div className="wk" key={i}>
          <span className="n">{i + 1}</span>
          <div>
            <div className="tx">{it.text}</div>
            {it.disputed ? <DisputedMark /> : null}
            <Chips refs={it.refs} ctx={ctx} />
          </div>
        </div>
      ))}
    </div>
  );
}

function DraftCard({ m, ctx, onConfirm }: { m: Message; ctx: Ctx; onConfirm: (draftId: string, ack: boolean) => void }) {
  const [draft, setDraft] = useState<Draft>(m.draft as Draft);
  const [conclusion, setConclusion] = useState(draft.conclusion);
  const [ack, setAck] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Сервер мог обновить черновик (например, статус после отправки)
  useEffect(() => {
    if (m.draft) {
      setDraft(m.draft);
      setConclusion(m.draft.conclusion);
    }
  }, [m.draft]);

  const editable = draft.status === 'draft' && !ctx.busy;
  const session = ctx.vehicle.sessions.find((s) => s.session_id === draft.session_id);
  const shortOf = (manualId: string, fallback: string) => ctx.vehicle.manuals.find((x) => x.manual_id === manualId)?.short ?? fallback;

  const patch = async (body: Partial<Pick<Draft, 'conclusion' | 'urgency'>>) => {
    setSaving(true);
    setError(null);
    try {
      const next = await api.patchDraft(draft.draft_id, body);
      setDraft(next);
      setConclusion(next.conclusion);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const dirty = conclusion.trim() !== draft.conclusion.trim();
  const canSend = editable && !saving && !dirty && conclusion.trim().length > 0 && (!draft.requires_warning_ack || ack);

  return (
    <div className="card">
      <div className="chead">
        <Icon name={draft.status === 'sent' ? 'clipboard-check' : 'clipboard-list'} />
        Заявка на дефектовку
        <span className="st">
          {draft.status === 'sent' ? `отправлена${draft.ticket_id ? ' · ' + draft.ticket_id : ''}` : draft.status === 'cancelled' ? 'отменена' : 'черновик'}
        </span>
        {saving ? (
          <span className="st rt">
            <Icon name="loader-2" size="s" className="spin" />
          </span>
        ) : null}
      </div>
      <div className="frm">
        <div className="k">Машина</div>
        <div className="v">
          {ctx.vehicle.title} <span className="m">{draft.vehicle_id}</span> · <span className="m">{ctx.vehicle.engine_model}</span>
        </div>
        <div className="k">Проверка</div>
        <div className="v m">
          {draft.session_id}
          {session ? ` · ${dateTime(session.checked_at)}` : ''}
        </div>
        <div className="k">Тип неисправности</div>
        <div className="v">
          <span className="m">{draft.anomaly_type}</span> · {draft.anomaly_title}
        </div>
        <div className="k">Диагноз</div>
        <div className="v">
          {draft.status === 'draft' ? (
            <>
              <textarea
                value={conclusion}
                onChange={(e) => setConclusion(e.target.value)}
                onBlur={() => {
                  if (dirty && conclusion.trim()) void patch({ conclusion: conclusion.trim() });
                }}
                disabled={!editable}
                aria-label="Диагноз"
                rows={3}
              />
              <span className="sub2">Можно поправить. Сохраняется, когда вы выходите из поля.</span>
            </>
          ) : (
            draft.conclusion
          )}
        </div>
        <div className="k">Приоритет</div>
        <div className="v">
          {draft.status === 'draft' ? (
            <div className="seg" role="radiogroup" aria-label="Приоритет">
              {URGENCY.map((u) => (
                <button
                  key={u}
                  type="button"
                  role="radio"
                  aria-checked={draft.urgency === u}
                  className={draft.urgency === u ? 'on' : ''}
                  disabled={!editable || saving}
                  onClick={() => {
                    if (u !== draft.urgency) void patch({ urgency: u });
                  }}
                >
                  {capitalize(PRIORITY_LABEL[u])}
                </button>
              ))}
            </div>
          ) : (
            <PriorityBadge priority={draft.urgency} />
          )}
          {draft.status === 'draft' ? (
            <span className="sub2">Приоритет предложил агент. Его можно изменить: окончательный выбор за вами.</span>
          ) : null}
          {draft.urgency_basis.length ? <span className="sub2">{draft.urgency_basis.join(' · ')}</span> : null}
        </div>
        <div className="k">Работы</div>
        <div className="v">
          <WorkList items={draft.operations} ctx={ctx} empty="нет" />
        </div>
        <div className="k">Запчасти</div>
        <div className="v">
          <WorkList items={draft.spare_parts} ctx={ctx} empty="нет: в руководстве запчасти для этих работ не указаны" />
        </div>
        <div className="k" style={{ borderBottom: 'none' }}>
          Источники
        </div>
        <div className="v" style={{ borderBottom: 'none' }}>
          <div className="chips" style={{ marginTop: 0 }}>
            {draft.references.map((r, i) => {
              const t: ManualTarget = { manual_id: r.manual_id, page: r.pdf_page, short: shortOf(r.manual_id, r.manual) };
              return <RefChip key={i} target={t} label={shortOf(r.manual_id, r.manual)} active={sameTarget(ctx.activeManual, t)} onOpen={ctx.onOpenManual} />;
            })}
          </div>
          <span className="sub2">Каждая ссылка сверена со страницей PDF руководства этого двигателя.</span>
        </div>
      </div>

      {draft.warnings.length ? (
        <div className="cdiv cpad">
          <div className="warns" style={{ marginTop: 0 }}>
            {draft.warnings.map((w, i) => (
              <div className="alert a-warn" key={i}>
                <Icon name="alert-triangle" />
                <div>{w}</div>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {draft.status === 'draft' && draft.requires_warning_ack ? (
        <label className="ack">
          <span>Понимаю, что запись с помехами и вывод предварительный</span>
          <input type="checkbox" role="switch" className="switch" checked={ack} onChange={(e) => setAck(e.target.checked)} disabled={!editable} />
        </label>
      ) : null}

      {error ? (
        <div className="cdiv cpad">
          <div className="alert">
            <Icon name="alert-circle" />
            <div>{error}</div>
          </div>
        </div>
      ) : null}

      {draft.status === 'draft' ? (
        <div className="cfoot">
          <div className="cap">
            <Icon name="shield-check" />
            <span>Уйдёт ровно этот состав. Без вашего подтверждения заявка не отправляется.</span>
          </div>
          <button type="button" className="btn pri" disabled={!canSend} onClick={() => onConfirm(draft.draft_id, ack)}>
            <Icon name="send" />
            Подтвердить и отправить в ТОиР
          </button>
        </div>
      ) : null}
      <StepsFold steps={m.steps} usage={m.usage} />
    </div>
  );
}

function TicketCard({ m }: { m: Message }) {
  const t = m.ticket as Ticket;
  return (
    <div className="card">
      <div className="okline">
        <Icon name="circle-check" size="xl" className="mut" />
        <div>
          <div className="big">
            Заявка <span className="m">{t.ticket_id}</span> создана в ТОиР
          </div>
          <div className="st m">
            {dateTime(t.created_at)} · проверка {t.session_id} · приоритет {PRIORITY_LABEL[t.urgency]}
          </div>
        </div>
      </div>
      <details className="fold cdiv">
        <summary>
          <Icon name="chevron-right" />
          Состав заявки
        </summary>
        <div className="fin">
          <ul className="basis">
            <li>
              Тип неисправности: <span className="m">{t.anomaly_type}</span>
            </li>
            <li>Диагноз: {t.conclusion}</li>
            <li>Работы: {t.operations.join('; ')}</li>
            <li>Запчасти: {t.spare_parts.length ? t.spare_parts.join('; ') : 'нет'}</li>
            <li>Источники: {t.references.map((r) => `${r.manual}, стр. ${r.pdf_page}`).join('; ')}</li>
          </ul>
        </div>
      </details>
      <StepsFold steps={m.steps} usage={m.usage} />
    </div>
  );
}

/* ---------- Сообщение ---------- */

export function MessageView({
  message: m,
  vehicle,
  busy,
  activeManual,
  onOpenManual,
  onCreateTicket,
  onConfirmDraft,
  marks,
  onToggleStep,
  report,
  onReport,
}: {
  message: Message;
  vehicle: VehicleDetail;
  busy: boolean;
  activeManual: ManualTarget | null;
  onOpenManual: (t: ManualTarget) => void;
  onCreateTicket: () => void;
  onConfirmDraft: (draftId: string, ack: boolean) => void;
  marks: Marks;
  onToggleStep: (key: string, index: number) => void;
  /** Сообщение механика в поддержку об этом ответе, если было */
  report?: Report;
  onReport: (messageId: string) => void;
}) {
  if (m.role === 'user') {
    return (
      <div className="q" data-mid={m.id}>
        {/* Подпись отправителя: какой механик спрашивал (смены), без фамилии — просто «Механик» */}
        <div className="who">
          <Icon name="user" size="s" />
          {m.author || 'Механик'}
          <span className="tm">{timeShort(m.created_at)}</span>
          {m.session_id ? <span className="tm">{m.session_id}</span> : null}
        </div>
        {m.images?.length ? (
          <div className="qph">
            {m.images.map((p, i) => (
              <a key={p.id} href={p.url} target="_blank" rel="noreferrer" title="Открыть фото целиком">
                {/* eslint-disable-next-line @next/next/no-img-element -- снимок отдаёт сервер приложения как есть */}
                <img src={p.url} alt={`Фото механика ${i + 1}`} loading="lazy" />
              </a>
            ))}
          </div>
        ) : null}
        {m.text ? <div>{m.text}</div> : null}
      </div>
    );
  }

  const ctx: Ctx = { vehicle, busy, activeManual, onOpenManual, marks, onToggleStep };
  let body;
  if (m.localError) {
    body = (
      <div className={`card strip${m.localOk ? ' v-ok' : ' v-err'}`}>
        <div className="cpad" style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
          <Icon name={m.localOk ? 'circle-check' : 'alert-circle'} className={m.localOk ? 'c-ok' : 'c-h'} />
          <div>{m.text}</div>
        </div>
      </div>
    );
  } else if (m.kind === 'verdict') {
    body = <VerdictCard m={m} ctx={ctx} onCreateTicket={onCreateTicket} />;
  } else if (m.kind === 'ticket_draft' && m.draft) {
    body = <DraftCard m={m} ctx={ctx} onConfirm={onConfirmDraft} />;
  } else if (m.kind === 'ticket_created' && m.ticket) {
    body = <TicketCard m={m} />;
  } else if (m.kind === 'answer' && m.answer) {
    body = (
      <div className="card">
        <AnswerBlocks answer={m.answer} ctx={ctx} showSummary messageId={m.id} />
        {m.answer.recommendation_text ? (
          <div className="cdiv" style={{ paddingTop: 16 }}>
            <CopyBlock text={m.answer.recommendation_text} />
          </div>
        ) : null}
        <StepsFold steps={m.steps} usage={m.usage} />
      </div>
    );
  } else {
    body = (
      <div className="card">
        <div className="cpad" style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>
          <SummaryText text={m.text ?? ''} />
        </div>
        <StepsFold steps={m.steps} usage={m.usage} />
      </div>
    );
  }

  return (
    <div className="a" data-mid={m.id}>
      <div className="who">
        <Icon name="engine" size="s" />
        Цифровой механик
        <span className="tm">{timeShort(m.created_at)}</span>
      </div>
      {body}
      {/* Механик сообщает администратору: ответ неверный, в руководстве ошибка, система не работает */}
      {m.localError ? null : report ? (
        <div className="afoot">
          <span className="rep done" title={report.text || undefined}>
            <Icon name="flag" size="s" />
            <span>Отправлено администратору: {report.reason.toLowerCase()}</span>
          </span>
        </div>
      ) : (
        <div className="afoot">
          <button type="button" className="rep" onClick={() => onReport(m.id)} title="Сообщить администратору о проблеме с этим ответом">
            <Icon name="flag" size="s" />
            <span>Сообщить о проблеме</span>
          </button>
        </div>
      )}
    </div>
  );
}
