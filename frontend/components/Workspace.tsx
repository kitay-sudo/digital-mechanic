'use client';

import Link from 'next/link';
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { StreamLostError, api, chatStream, confirmDraftStream, turnStream } from '@/lib/api';
import { dateTime, num } from '@/lib/format';
import { usePresence } from '@/lib/presence';
import { logout } from '@/lib/auth';
import { profileOf, useSettings } from '@/lib/settings';
import type { ManualTarget, Marks, Message, Report, Session, Step, StreamEvent, VehicleDetail } from '@/lib/types';
import { Composer, type Flash, type TicketButton } from './Composer';
import { Icon } from './Icon';
import { Blueprint } from './Blueprint';
import { Parts } from './Parts';
import { ManualPanel } from './ManualPanel';
import { MessageView, PendingSteps } from './MessageView';
import { sameTarget } from './RefChip';
import { ErrorState, Loading } from './States';
import { VehiclePanel } from './VehiclePanel';

export const DIAGNOSE_TEXT = 'Получи результат диагностики';
export const TICKET_TEXT = 'Создай заявку на дефектовку';

/** Начало хода: новый запрос или подключение к ходу, который уже идёт на сервере. */
type TurnStart = (onEvent: (e: StreamEvent) => void, signal: AbortSignal) => Promise<void>;

const pause = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/** Отступ над вопросом механика, когда ответ прокручивается к началу */
const CHAT_TOP_GAP = 12;

/** Через сколько часов после последнего сообщения чат напоминает, на чём остановились */
const RESUME_HOURS = 6;

/** Причины сообщения в поддержку: механик выбирает одну, комментарий по желанию */
const REPORT_REASONS = ['Ответ неверный', 'Нужного нет в руководстве', 'Ошибка в руководстве', 'Система работает не так', 'Другое'];

/**
 * На чём остановились: механик вернулся к машине через несколько часов или пришла другая смена.
 * Считается по чату без модели: кто и когда писал последним, сколько шагов отмечено, какие заявки.
 */
function resumeLine(messages: Message[], marks: Marks, vehicle: VehicleDetail, me: string): string | null {
  const last = [...messages].reverse().find((m) => m.role === 'user' && !m.localError);
  if (!last) return null;
  const hours = (Date.now() - new Date(last.created_at).getTime()) / 3_600_000;
  const otherShift = Boolean(me && last.author && last.author !== me);
  if (hours < RESUME_HOURS && !otherShift) return null;
  const done = Object.values(marks).reduce((n, list) => n + Object.keys(list).length, 0);
  const parts = [`Последнее сообщение ${dateTime(last.created_at)}${last.author ? `, механик ${last.author}` : ''}.`];
  parts.push(done ? `Отмечено сделанным шагов: ${done}.` : 'Сделанных шагов не отмечено.');
  const ticket = vehicle.tickets?.[vehicle.tickets.length - 1];
  if (ticket) parts.push(`Последняя заявка ${ticket.ticket_id}.`);
  return parts.join(' ');
}

/**
 * Состояние кнопки «Создать заявку» в панели ввода — по проверке, которая сейчас в чате:
 * заявка уже есть, вердикт разрешил заявку, или почему её пока нельзя создать.
 */
function ticketButton(messages: Message[], vehicle: VehicleDetail, session: Session | null): TicketButton {
  if (!session) return { state: 'off', reason: 'У машины нет проверок: заявку не к чему привязать.' };
  const sid = session.session_id;
  const made = [...vehicle.tickets].reverse().find((t) => t.session_id === sid);
  if (made) {
    return { state: 'done', ticketId: made.ticket_id, reason: `По проверке ${sid} заявка ${made.ticket_id} создана ${dateTime(made.created_at)}.` };
  }
  // Черновик уже собран и ждёт подтверждения: второй не нужен, отправка — из карточки черновика
  const last = [...messages].reverse().find((m) => !m.localError && m.role === 'assistant' && m.session_id === sid);
  if (last?.kind === 'ticket_draft' && last.draft?.status === 'draft') {
    return { state: 'off', reason: 'Черновик заявки уже готов: проверьте состав и нажмите «Подтвердить и отправить в ТОиР» в его карточке.' };
  }
  const verdict = [...messages].reverse().find((m) => m.kind === 'verdict' && m.session_id === sid && m.assessment);
  if (!verdict?.assessment) return { state: 'off', reason: 'Сначала нажмите «Получить результат диагностики»: заявка собирается по результату проверки.' };
  if (verdict.assessment.ticket_allowed) return { state: 'on' };
  return { state: 'off', reason: verdict.assessment.ticket_block_reason ?? 'По этой проверке заявку создать нельзя.' };
}

let localId = 0;
const localNotice = (text: string): Message => ({
  id: `local_${++localId}`,
  role: 'assistant',
  created_at: new Date().toISOString(),
  session_id: null,
  kind: 'notice',
  text,
  localError: true,
});

export function Workspace({ vehicleId, initialSession = null }: { vehicleId: string; initialSession?: string | null }) {
  const [vehicle, setVehicle] = useState<VehicleDetail | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [steps, setSteps] = useState<Step[]>([]);
  const [manual, setManual] = useState<ManualTarget | null>(null);
  const [sideOpen, setSideOpen] = useState(false);
  /** Отметки «сделано» по шагам: хранятся на сервере, видны сменщику */
  const [marks, setMarks] = useState<Marks>({});
  /** Сообщения механиков в поддержку по ответам агента */
  const [reports, setReports] = useState<Record<string, Report>>({});
  /** Панель «Кто работает» (смена механика) и панель сообщения в поддержку */
  const [whoOpen, setWhoOpen] = useState(false);
  const [reportFor, setReportFor] = useState<string | null>(null);
  /** Сообщение над панелью ввода: успех или мелкая ошибка, само исчезает */
  const [flash, setFlash] = useState<Flash | null>(null);
  const say = useCallback((kind: Flash['kind'], text: string) => setFlash({ id: Date.now(), kind, text }), []);
  /** Вопрос администратору не по конкретному ответу */
  const [adminOpen, setAdminOpen] = useState(false);
  const chatRef = useRef<HTMLDivElement>(null);
  /** Колонка чата: высоты стеклянных шапки и панели ввода пишутся в неё (--hdr-h, --cmp-h), переписка уходит под них */
  const colRef = useRef<HTMLElement>(null);
  // Плавное закрытие: панель остаётся на экране, пока уезжает
  const manualView = usePresence(manual);
  const sideView = usePresence(sideOpen ? true : null);
  const whoView = usePresence(whoOpen ? true : null);
  const reportView = usePresence(reportFor);
  const adminView = usePresence(adminOpen ? true : null);
  const settings = useSettings();
  const me = settings.mechanic.trim();
  const profile = profileOf(settings);
  const profileRef = useRef(profile);
  profileRef.current = profile;
  /** Соединение идущего хода. Занято — второй ход с этой страницы не начинается */
  const turnRef = useRef<AbortController | null>(null);
  const aliveRef = useRef(true);

  const loadVehicle = useCallback(
    () =>
      api.vehicle(vehicleId).then((v) => {
        setVehicle(v);
        // Проверку механик выбирает на экране истории машины, она приходит в адресе. Иначе берём последнюю
        const picked = initialSession && v.sessions.some((s) => s.session_id === initialSession) ? initialSession : null;
        setSessionId((cur) => picked ?? cur ?? v.sessions[v.sessions.length - 1]?.session_id ?? null);
        return v;
      }),
    [vehicleId, initialSession],
  );

  const onEvent = useCallback((e: StreamEvent) => {
    if (e.type === 'user' || e.type === 'message') {
      setMessages((list) => (list.some((m) => m.id === e.message.id) ? list : [...list, e.message]));
      if (e.type === 'message') setSteps([]);
    } else if (e.type === 'step') {
      const step: Step = { id: e.id, tool: e.tool, title: e.title, status: e.status, detail: e.detail };
      setSteps((list) => (list.some((s) => s.id === step.id) ? list.map((s) => (s.id === step.id ? step : s)) : [...list, step]));
    } else if (e.type === 'error') {
      // При повторном подключении события приходят с начала хода: ту же ошибку дважды не показываем
      setMessages((list) => (list.some((m) => m.localError && m.text === e.text) ? list : [...list, localNotice(e.text)]));
    }
  }, []);

  /**
   * Общая обёртка хода: поток событий, затем сверка с сервером.
   * Ход идёт на сервере сам по себе. Если связь оборвалась или запрос ушёл с другого устройства,
   * страница подключается к нему заново и досматривает до конца.
   */
  const runTurn = useCallback(
    (first: TurnStart) => {
      const attach: TurnStart = (cb, signal) => turnStream(vehicleId, cb, signal);
      const go = async (start: TurnStart): Promise<void> => {
        if (turnRef.current || !aliveRef.current) return;
        const ctl = new AbortController();
        turnRef.current = ctl;
        const release = () => {
          if (turnRef.current === ctl) turnRef.current = null;
          setBusy(false);
          setSteps([]);
        };
        setBusy(true);
        setSteps([]);
        let finished = false;
        let failed = false;
        let lost = false;
        try {
          await start((e) => {
            if (e.type === 'done') finished = true;
            if (e.type === 'error') failed = true;
            onEvent(e);
          }, ctl.signal);
        } catch (err) {
          if (ctl.signal.aborted) return;
          if (err instanceof StreamLostError) lost = true;
          else {
            finished = true;
            setMessages((list) => [...list, localNotice((err as Error).message)]);
          }
        }
        if (ctl.signal.aborted) return;
        // Ход закончен: кнопки свободны сразу, сверка идёт следом
        if (finished) release();
        // Заявки, статусы черновиков и история могли измениться
        loadVehicle().catch(() => undefined);
        try {
          if (lost) await pause(1000);
          // Ошибка хода показана механику: сервер больше не напомнит о ней при возврате на страницу
          if (failed) await api.seenTurn(vehicleId).catch(() => undefined);
          const conv = await api.conversation(vehicleId);
          if (ctl.signal.aborted) return;
          setMessages((list) => [...conv.messages, ...list.filter((m) => m.localError)]);
          setMarks(conv.marks ?? {});
          setReports(conv.reports ?? {});
          if (conv.turn) {
            // Агент ещё работает: поток оборвался раньше хода или ход начат с другого устройства
            if (turnRef.current === ctl) turnRef.current = null;
            return go(attach);
          }
        } catch (err) {
          if (ctl.signal.aborted) return;
          if (!finished) setMessages((list) => [...list, localNotice((err as Error).message)]);
        }
        if (!finished) release();
      };
      return go(first);
    },
    [loadVehicle, onEvent, vehicleId],
  );

  // Уход со страницы закрывает только соединение: агент на сервере дорабатывает ход
  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
      turnRef.current?.abort();
      turnRef.current = null;
      setBusy(false);
      setSteps([]);
    };
  }, [vehicleId]);

  const loadAll = useCallback(() => {
    setLoadError(null);
    Promise.all([loadVehicle(), api.conversation(vehicleId)])
      .then(([v, conv]) => {
        setMessages(conv.messages);
        setMarks(conv.marks ?? {});
        setReports(conv.reports ?? {});
        // Запрос отправлен до ухода со страницы и ещё выполняется (или оборвался): показываем его ход
        if (conv.turn) void runTurn((cb, signal) => turnStream(vehicleId, cb, signal));
        // Чат продолжается по той проверке, о которой шёл разговор: иначе кнопка «Создать заявку»
        // из старого вердикта ушла бы с другой, последней проверкой.
        // Явный выбор механика из истории машины важнее.
        if (initialSession && v.sessions.some((s) => s.session_id === initialSession)) return;
        const last = [...conv.messages].reverse().find((m) => m.session_id);
        if (last?.session_id && v.sessions.some((s) => s.session_id === last.session_id)) {
          setSessionId(last.session_id);
        }
      })
      .catch((e: Error) => setLoadError(e.message));
  }, [loadVehicle, runTurn, vehicleId, initialSession]);

  useEffect(loadAll, [loadAll]);

  /**
   * Прокрутка чата. Пока агент работает — вниз: видно вопрос и шаги разбора.
   * Пришёл ответ (или чат открыли) — наверх встаёт вопрос механика, под ним начало ответа:
   * длинный ответ с таблицами читается сверху, а не с последней строки.
   */
  const shownRef = useRef<string | null>(null);
  useEffect(() => {
    const el = chatRef.current;
    if (!el) return;
    if (busy) {
      el.scrollTop = el.scrollHeight;
      return;
    }
    const last = messages[messages.length - 1];
    if (!last || last.id === shownRef.current) return;
    shownRef.current = last.id;
    const prev = messages[messages.length - 2];
    const anchor = last.role === 'assistant' && prev?.role === 'user' ? prev : last;
    const node = el.querySelector<HTMLElement>(`[data-mid="${CSS.escape(anchor.id)}"]`);
    if (!node) {
      el.scrollTop = el.scrollHeight;
      return;
    }
    // Шапка стеклянная и лежит поверх переписки: вопрос встаёт сразу под ней
    const header = colRef.current?.querySelector<HTMLElement>(':scope > .hdr');
    el.scrollTop += node.getBoundingClientRect().top - el.getBoundingClientRect().top - (header?.offsetHeight ?? 0) - CHAT_TOP_GAP;
  }, [messages, steps, busy]);

  const send = useCallback(
    (text: string, images: string[] = []) => {
      const clean = text.trim();
      if (!clean && !images.length) return;
      setMessages((list) => list.filter((m) => !m.localError));
      void runTurn((cb, signal) =>
        chatStream(
          { vehicle_id: vehicleId, session_id: sessionId, text: clean, images, profile: profileRef.current },
          cb,
          signal,
        ),
      );
    },
    [runTurn, sessionId, vehicleId],
  );

  const confirmDraft = useCallback(
    (draftId: string, warningAck: boolean) => {
      void runTurn((cb, signal) => confirmDraftStream(draftId, { warning_ack: warningAck, profile: profileRef.current }, cb, signal));
    },
    [runTurn],
  );

  /** Отметка шага сразу видна на экране, сервер её сохраняет с фамилией механика */
  const toggleStep = useCallback(
    (key: string, index: number) => {
      const done = !marks[key]?.[String(index)];
      setMarks((cur) => {
        const list = { ...(cur[key] ?? {}) };
        if (done) list[String(index)] = { author: me || null, at: new Date().toISOString() };
        else delete list[String(index)];
        return { ...cur, [key]: list };
      });
      api
        .mark(vehicleId, { key, index, done, author: me || null })
        .then((r) => setMarks(r.marks))
        .catch((e: Error) => {
          say('err', `Отметка не сохранилась: ${e.message}`);
          api.conversation(vehicleId).then((c) => setMarks(c.marks ?? {})).catch(() => undefined);
        });
    },
    [marks, me, vehicleId],
  );

  const sendReport = useCallback(
    (messageId: string, reason: string, text: string) => {
      setReportFor(null);
      api
        .report({ message_id: messageId, reason, text, author: me || null })
        .then((r) => {
          setReports((cur) => ({ ...cur, [messageId]: r.report }));
          say('ok', 'Сообщение о проблеме отправлено администратору.');
        })
        .catch((e: Error) => say('err', `Сообщение не отправлено: ${e.message}`));
    },
    [me, say],
  );

  const sendAdmin = useCallback(
    (text: string) => {
      setAdminOpen(false);
      api
        .adminMessage({ vehicle_id: vehicleId, text, author: me || null })
        .then(() => say('ok', 'Сообщение отправлено администратору. Он увидит его в журнале.'))
        .catch((e: Error) => say('err', `Сообщение не отправлено: ${e.message}`));
    },
    [me, say, vehicleId],
  );

  useEffect(() => {
    if (!whoOpen && !reportFor && !adminOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      setWhoOpen(false);
      setReportFor(null);
      setAdminOpen(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [whoOpen, reportFor, adminOpen]);

  // Повторное нажатие на ту же ссылку закрывает страницу руководства
  /**
   * Открытие и закрытие руководства меняет ширину колонки чата: текст переносится иначе и уезжает.
   * Перед этим запоминаем, где на экране нажатая ссылка (или верхнее сообщение), после — возвращаем её на то же место.
   */
  const pressedRef = useRef<Element | null>(null);
  const anchorRef = useRef<{ el: Element; top: number } | null>(null);
  const rememberPlace = useCallback(() => {
    const chat = chatRef.current;
    if (!chat) return;
    const box = chat.getBoundingClientRect();
    const pressed = pressedRef.current;
    const visible = (el: Element) => {
      const r = el.getBoundingClientRect();
      return r.bottom > box.top && r.top < box.bottom;
    };
    let el: Element | null = pressed && chat.contains(pressed) && visible(pressed) ? pressed : null;
    if (!el) el = [...chat.querySelectorAll('[data-mid]')].find(visible) ?? null;
    anchorRef.current = el ? { el, top: el.getBoundingClientRect().top } : null;
  }, []);

  const openManual = useCallback((target: ManualTarget) => {
    rememberPlace();
    setManual((cur) => (sameTarget(cur, target) ? null : target));
    setSideOpen(false);
  }, []);

  const withManual = Boolean(manualView.shown);

  // Переписка прокручивается под стеклянными шапкой и панелью ввода: отступы переписки — по их высоте
  const vehicleLoaded = Boolean(vehicle);
  useEffect(() => {
    const col = colRef.current;
    if (!col || typeof ResizeObserver === 'undefined') return;
    const header = col.querySelector<HTMLElement>(':scope > .hdr');
    const composer = col.querySelector<HTMLElement>(':scope > .composer');
    const measure = () => {
      if (header) col.style.setProperty('--hdr-h', `${header.offsetHeight}px`);
      if (composer) col.style.setProperty('--cmp-h', `${composer.offsetHeight}px`);
    };
    measure();
    const observer = new ResizeObserver(measure);
    if (header) observer.observe(header);
    if (composer) observer.observe(composer);
    return () => observer.disconnect();
  }, [vehicleLoaded]);
  useLayoutEffect(() => {
    const chat = chatRef.current;
    const anchor = anchorRef.current;
    anchorRef.current = null;
    if (!chat || !anchor || !anchor.el.isConnected) return;
    chat.scrollTop += anchor.el.getBoundingClientRect().top - anchor.top;
  }, [withManual]);

  if (loadError) return <ErrorState text={loadError} onRetry={loadAll} />;
  if (!vehicle) return <Loading text="Загружаю машину…" />;

  const session = vehicle.sessions.find((s) => s.session_id === sessionId) ?? null;
  const resume = resumeLine(messages, marks, vehicle, me);
  // Расход на весь чат по машине: сумма по всем ответам, в рублях — верна и при смене модели
  const chatCost = messages.reduce((sum, m) => sum + (m.usage?.cost_rub ?? 0), 0);
  const costPart = chatCost > 0 ? (
    <span className="chat-cost" title="Сколько стоили ответы агента в этом чате, по всем моделям">
      расход чата <b>{num(chatCost)} ₽</b>
    </span>
  ) : null;
  const sessionLine = (
    // Одной строкой: шапка чата той же высоты, что шапка руководства рядом
    <Parts nowrap items={[session ? `Проверка ${session.session_id}` : 'Проверок нет', session ? dateTime(session.checked_at) : null, costPart]} />
  );

  return (
    <div className={`ws${manualView.shown ? ' with-manual' : ''}`}>
      <button
        type="button"
        className={`dimmer${sideView.shown || manualView.shown ? ' open' : ''}${!sideOpen && !manual ? ' leaving' : ''}`}
        aria-label="Закрыть"
        onClick={() => {
          if (manual) {
            rememberPlace();
            setManual(null);
          }
          else setSideOpen(false);
        }}
      />

      <VehiclePanel
        vehicle={vehicle}
        session={session}
        onOpenManual={openManual}
        open={Boolean(sideView.shown)}
        leaving={sideView.leaving}
        onClose={() => setSideOpen(false)}
        onWriteAdmin={() => {
          setSideOpen(false);
          setAdminOpen(true);
        }}
      />

      <section className="col chatcol" ref={colRef}>
        <div className="hdr">
          <Link href="/" className="hb only-m" aria-label="Назад к парку">
            <Icon name="arrow-left" />
          </Link>
          <div className="grow">
            <div className="h1 only-d">Чат с агентом</div>
            <div className="h1 only-m">
              {vehicle.title} <span className="m">{vehicle.vehicle_id}</span>
            </div>
            <div className="sub m only-d">{sessionLine}</div>
            <div className="sub m only-m">
              <Parts nowrap items={[vehicle.engine_model, session ? session.session_id : 'проверок нет', session ? dateTime(session.checked_at) : null]} />
            </div>
          </div>
          <div className="rt">
            {/* Кто сейчас работает: вошедший механик. При смене — «Сменить механика», вход следующего по PIN */}
            <button
              type="button"
              className={`who-btn${me ? '' : ' empty'}${whoOpen ? ' on' : ''}`}
              onClick={() => setWhoOpen((v) => !v)}
              aria-label={me ? `Механик ${me}. Сменить механика` : 'Войти: кто работает'}
              aria-expanded={whoOpen}
              title={me ? 'Кто работает с машиной. Нажмите при смене механика' : 'Войдите: ваша фамилия будет видна в чате, журнале и сменщику'}
            >
              <Icon name={me ? 'user-check' : 'user-question'} />
              <span className="only-d">{me || 'Кто работает?'}</span>
            </button>
            <button type="button" className="hb only-m" onClick={() => setSideOpen(true)} aria-label="Машина и проверки" title="Машина и проверки">
              <Icon name="list-details" />
            </button>
          </div>
        </div>

        <div className="chat" ref={chatRef} onPointerDownCapture={(e) => (pressedRef.current = (e.target as Element).closest('button, a'))}>
          {messages.length === 0 && !busy ? (
            <div className="center">
              <Blueprint className="chat-art" />
              <div className="e1">Чат по машине {vehicle.vehicle_id}</div>
              <div style={{ maxWidth: 520 }}>
                Выберите проверку и нажмите «Получить результат диагностики». Агент разберёт результат и ответит по руководствам двигателя{' '}
                {vehicle.engine_model}. Можно сразу задать вопрос по руководству.
              </div>
            </div>
          ) : null}
          {messages.map((m) => (
            <MessageView
              key={m.id}
              message={m}
              vehicle={vehicle}
              busy={busy}
              activeManual={manual}
              onOpenManual={openManual}
              onCreateTicket={() => send(TICKET_TEXT)}
              onConfirmDraft={confirmDraft}
              marks={marks}
              onToggleStep={toggleStep}
              report={reports[m.id]}
              onReport={setReportFor}
            />
          ))}
          {/* Механик вернулся к машине через несколько часов или пришла другая смена: на чём остановились */}
          {!busy && resume ? (
            <div className="resume">
              <Icon name="history" />
              <div>
                <b>Продолжение работы по машине</b>
                <span>{resume}</span>
              </div>
            </div>
          ) : null}
          {busy ? <PendingSteps steps={steps} /> : null}
        </div>

        <Composer
          busy={busy}
          canDiagnose={Boolean(session)}
          onDiagnose={() => send(DIAGNOSE_TEXT)}
          ticket={ticketButton(messages, vehicle, session)}
          flash={flash}
          onTicket={() => send(TICKET_TEXT)}
          onSend={send}
        />
      </section>

      {manualView.shown ? (
        <ManualPanel
          target={manualView.shown}
          leaving={manualView.leaving}
          onNavigate={setManual}
          onClose={() => {
            rememberPlace();
            setManual(null);
          }}
        />
      ) : null}

      {whoView.shown ? (
        <WhoPanel
          name={me}
          leaving={whoView.leaving}
          onClose={() => setWhoOpen(false)}
          onSwitch={() => {
            setWhoOpen(false);
            void logout();
          }}
        />
      ) : null}

      {reportView.shown ? (
        <ReportPanel
          leaving={reportView.leaving}
          onClose={() => setReportFor(null)}
          onSend={(reason, text) => sendReport(reportView.shown as string, reason, text)}
        />
      ) : null}

      {adminView.shown ? (
        <ReportPanel direct leaving={adminView.leaving} onClose={() => setAdminOpen(false)} onSend={(_, text) => sendAdmin(text)} />
      ) : null}
    </div>
  );
}

/** Смена механика: выход к списку «Кто работает», следующий входит своим PIN. ФИО подписывает вопросы и отметки */
function WhoPanel({
  name,
  leaving,
  onClose,
  onSwitch,
}: {
  name: string;
  leaving: boolean;
  onClose: () => void;
  onSwitch: () => void;
}) {
  return (
    <>
      <button type="button" className={`veil${leaving ? ' leaving' : ''}`} aria-label="Отмена" onClick={onClose} />
      <div className={`pop${leaving ? ' leaving' : ''}`} role="dialog" aria-label="Кто работает с машиной">
        <div className="pop-t">{name ? `Работает ${name}` : 'Кто работает с машиной?'}</div>
        <div className="pop-s">
          {name
            ? 'При смене нажмите «Сменить механика»: следующий выберет себя в списке и наберёт PIN. Сменщик увидит, кто и что уже сделал.'
            : 'Войдите: выберите себя в списке и наберите PIN. Ваша фамилия подпишет вопросы и отметки шагов.'}
        </div>
        <div className="pop-f">
          <button type="button" className="btn" onClick={onClose}>
            Отмена
          </button>
          <button type="button" className="btn pri" onClick={onSwitch} autoFocus>
            <Icon name={name ? 'switch-horizontal' : 'login-2'} />
            {/* На телефоне кнопка в половину ширины: второе слово туда не помещается */}
            {name ? (
              <span>
                Сменить<span className="only-d">&nbsp;механика</span>
              </span>
            ) : (
              'Войти'
            )}
          </button>
        </div>
      </div>
    </>
  );
}

/**
 * Сообщение администратору. По ответу агента: причина из списка и комментарий по желанию —
 * администратор увидит вопрос и ответ в журнале. Напрямую (direct): свой текст, машина и фамилия подставятся сами.
 * Выезжает снизу, как настройки.
 */
function ReportPanel({
  direct = false,
  leaving,
  onClose,
  onSend,
}: {
  direct?: boolean;
  leaving: boolean;
  onClose: () => void;
  onSend: (reason: string, text: string) => void;
}) {
  const [reason, setReason] = useState(REPORT_REASONS[0]);
  const [text, setText] = useState('');
  const ready = !direct || text.trim().length > 0;
  const title = direct ? 'Написать администратору' : 'Сообщить о проблеме';
  return (
    <>
      <button type="button" className={`sp-dim${leaving ? ' leaving' : ''}`} aria-label="Отмена" onClick={onClose} />
      <form
        className={`sp rp${leaving ? ' leaving' : ''}`}
        role="dialog"
        aria-label={title}
        onSubmit={(e) => {
          e.preventDefault();
          if (ready) onSend(direct ? '' : reason, text.trim());
        }}
      >
        <div className="handle">
          <i />
        </div>
        <div className="sp-h">
          <Icon name={direct ? 'message-circle' : 'flag'} />
          <span>{title}</span>
          <button type="button" className="hb" onClick={onClose} aria-label="Закрыть">
            <Icon name="x" />
          </button>
        </div>
        <div className="sp-b one">
          {direct ? null : (
            <div className="sp-g">
              <div className="sp-l">Что не так</div>
              <div className="rsn" role="radiogroup" aria-label="Что не так">
                {REPORT_REASONS.map((r) => (
                  <button key={r} type="button" role="radio" aria-checked={reason === r} className={reason === r ? 'on' : ''} onClick={() => setReason(r)}>
                    <Icon name={reason === r ? 'circle-check' : 'circle'} />
                    <span>{r}</span>
                  </button>
                ))}
              </div>
            </div>
          )}
          <div className="sp-g">
            <div className="sp-l">{direct ? 'Сообщение' : 'Подробнее'}</div>
            <textarea
              className="inp pop-ta"
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder={direct ? 'Например: нет руководства на этот двигатель' : 'Что именно не так (по желанию)'}
              aria-label={direct ? 'Сообщение администратору' : 'Комментарий'}
              maxLength={1000}
              rows={3}
              autoFocus={direct}
            />
            <div className="sp-s">
              {direct
                ? 'Администратор увидит сообщение в журнале вместе с машиной и вашей фамилией.'
                : 'Администратор увидит в журнале ваш вопрос, ответ агента и это сообщение.'}
            </div>
          </div>
        </div>
        <div className="sp-f">
          <button type="button" className="btn" onClick={onClose}>
            Отмена
          </button>
          <button type="submit" className="btn pri" disabled={!ready}>
            <Icon name="send" />
            Отправить
          </button>
        </div>
      </form>
    </>
  );
}
