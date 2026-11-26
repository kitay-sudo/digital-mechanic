'use client';

import Link from 'next/link';
import { useCallback, useEffect, useRef, useState } from 'react';
import { api, chatStream, confirmDraftStream } from '@/lib/api';
import { dateTime } from '@/lib/format';
import { profileOf, speechLang, useSettings } from '@/lib/settings';
import type { ManualTarget, Message, Step, StreamEvent, VehicleDetail } from '@/lib/types';
import { Composer } from './Composer';
import { Icon } from './Icon';
import { ManualPanel } from './ManualPanel';
import { MessageView, PendingSteps } from './MessageView';
import { ErrorState, Loading } from './States';
import { VehiclePanel } from './VehiclePanel';

export const DIAGNOSE_TEXT = 'Получи результат диагностики';
export const TICKET_TEXT = 'Создай заявку на дефектовку';

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
  const chatRef = useRef<HTMLDivElement>(null);
  const settings = useSettings();
  const profile = profileOf(settings);
  const profileRef = useRef(profile);
  profileRef.current = profile;

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

  const loadAll = useCallback(() => {
    setLoadError(null);
    Promise.all([loadVehicle(), api.conversation(vehicleId)])
      .then(([v, conv]) => {
        setMessages(conv.messages);
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
  }, [loadVehicle, vehicleId, initialSession]);

  useEffect(loadAll, [loadAll]);

  // Чат прокручивается вниз при новых сообщениях и шагах
  useEffect(() => {
    const el = chatRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, steps, busy]);

  const onEvent = useCallback((e: StreamEvent) => {
    if (e.type === 'user' || e.type === 'message') {
      setMessages((list) => (list.some((m) => m.id === e.message.id) ? list : [...list, e.message]));
      if (e.type === 'message') setSteps([]);
    } else if (e.type === 'step') {
      const step: Step = { id: e.id, tool: e.tool, title: e.title, status: e.status, detail: e.detail };
      setSteps((list) => (list.some((s) => s.id === step.id) ? list.map((s) => (s.id === step.id ? step : s)) : [...list, step]));
    } else if (e.type === 'error') {
      setMessages((list) => [...list, localNotice(e.text)]);
    }
  }, []);

  /** Общая обёртка хода: поток событий, затем сверка с сервером. */
  const runTurn = useCallback(
    async (start: (cb: (e: StreamEvent) => void) => Promise<void>) => {
      if (busy) return;
      setBusy(true);
      setSteps([]);
      try {
        await start(onEvent);
      } catch (err) {
        setMessages((list) => [...list, localNotice((err as Error).message)]);
      } finally {
        setBusy(false);
        setSteps([]);
        // Заявки, статусы черновиков и история могли измениться
        loadVehicle().catch(() => undefined);
        api
          .conversation(vehicleId)
          .then((conv) => setMessages((list) => [...conv.messages, ...list.filter((m) => m.localError)]))
          .catch(() => undefined);
      }
    },
    [busy, loadVehicle, onEvent, vehicleId],
  );

  const send = useCallback(
    (text: string) => {
      const clean = text.trim();
      if (!clean) return;
      setMessages((list) => list.filter((m) => !m.localError));
      void runTurn((cb) => chatStream({ vehicle_id: vehicleId, session_id: sessionId, text: clean, profile: profileRef.current }, cb));
    },
    [runTurn, sessionId, vehicleId],
  );

  const confirmDraft = useCallback(
    (draftId: string, warningAck: boolean) => {
      void runTurn((cb) => confirmDraftStream(draftId, { warning_ack: warningAck, profile: profileRef.current }, cb));
    },
    [runTurn],
  );

  const clearChat = useCallback(() => {
    if (busy) return;
    if (!window.confirm('Очистить чат по этой машине? Заявки и история проверок останутся.')) return;
    api
      .clearConversation(vehicleId)
      .then(() => setMessages([]))
      .catch((e: Error) => setMessages((list) => [...list, localNotice(e.message)]));
  }, [busy, vehicleId]);

  const openManual = useCallback((target: ManualTarget) => {
    setManual(target);
    setSideOpen(false);
  }, []);

  if (loadError) return <ErrorState text={loadError} onRetry={loadAll} />;
  if (!vehicle) return <Loading text="Загружаю машину…" />;

  const session = vehicle.sessions.find((s) => s.session_id === sessionId) ?? null;
  const sessionLine = session ? `Проверка ${session.session_id} · ${dateTime(session.checked_at)}` : 'Проверок нет';

  return (
    <div className={`ws${manual ? ' with-manual' : ''}`}>
      <button
        type="button"
        className={`dimmer${sideOpen || manual ? ' open' : ''}`}
        aria-label="Закрыть"
        onClick={() => {
          if (manual) setManual(null);
          else setSideOpen(false);
        }}
      />

      <VehiclePanel
        vehicle={vehicle}
        session={session}
        onOpenManual={openManual}
        open={sideOpen}
        onClose={() => setSideOpen(false)}
      />

      <section className="col chatcol">
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
              {vehicle.engine_model} · {session ? `${session.session_id} · ${dateTime(session.checked_at)}` : 'проверок нет'}
            </div>
          </div>
          <div className="rt">
            <button type="button" className="hb" onClick={clearChat} disabled={busy} aria-label="Очистить чат" title="Очистить чат">
              <Icon name="eraser" />
            </button>
            <button type="button" className="hb only-m" onClick={() => setSideOpen(true)} aria-label="Машина и проверки" title="Машина и проверки">
              <Icon name="list-details" />
            </button>
          </div>
        </div>

        <div className="chat" ref={chatRef}>
          {messages.length === 0 && !busy ? (
            <div className="center">
              <Icon name="message-2" size="xl" />
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
            />
          ))}
          {busy ? <PendingSteps steps={steps} /> : null}
        </div>

        <Composer
          busy={busy}
          canDiagnose={Boolean(session)}
          speechLang={speechLang(settings.language)}
          onDiagnose={() => send(DIAGNOSE_TEXT)}
          onSend={send}
        />
      </section>

      {manual ? <ManualPanel target={manual} onNavigate={setManual} onClose={() => setManual(null)} /> : null}
    </div>
  );
}
