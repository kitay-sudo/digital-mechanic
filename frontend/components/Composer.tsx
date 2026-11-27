'use client';

import { type CSSProperties, type ClipboardEvent, type DragEvent, useCallback, useEffect, useRef, useState } from 'react';
import { api } from '@/lib/api';
import { MAX_PHOTOS, photoFromFile } from '@/lib/photos';
import { sounds } from '@/lib/sounds';
import { serverVoiceSupported, useServerVoice } from '@/lib/voice';
import { Icon } from './Icon';

/* Распознавание речи браузера — запасной путь, когда на сервере распознавание не настроено.
   Типов в lib.dom нет, описываем нужное сами. */
interface SpeechResultEvent {
  results: ArrayLike<ArrayLike<{ transcript: string }>>;
}
interface Recognition {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  onresult: ((e: SpeechResultEvent) => void) | null;
  onend: (() => void) | null;
  onerror: ((e: { error?: string }) => void) | null;
  start: () => void;
  stop: () => void;
  abort?: () => void;
}
type RecognitionCtor = new () => Recognition;

function getRecognition(): RecognitionCtor | null {
  if (typeof window === 'undefined') return null;
  const w = window as unknown as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

function voiceErrorText(code: string | undefined): string | null {
  switch (code) {
    case 'aborted':
      return null;
    case 'not-allowed':
    case 'service-not-allowed':
      return 'Нет доступа к микрофону. Разрешите его в настройках браузера.';
    case 'no-speech':
      return 'Не расслышал. Нажмите микрофон и повторите.';
    case 'audio-capture':
      return 'Микрофон не найден.';
    case 'network':
      return 'Распознавание речи недоступно без сети.';
    case 'language-not-supported':
      return 'Браузер не распознаёт русскую речь.';
    default:
      return 'Не получилось распознать речь. Повторите или введите текст.';
  }
}

/** Язык распознавания речи: система работает только на русском. */
const SPEECH_LANG = 'ru-RU';

/** Сколько висит сообщение над панелью ввода; полоса внизу показывает, сколько осталось */
const NOTE_MS = 6000;

/** Сообщение от экрана чата: успех («отправлено»), подсказка или ошибка. id — чтобы одинаковый текст показался снова */
export interface Flash {
  id: number;
  kind: 'ok' | 'info' | 'err';
  text: string;
}

/** Кнопка «Создать заявку» в панели ввода: доступна, недоступна с причиной или заявка уже создана */
export type TicketButton =
  | { state: 'on' }
  | { state: 'off'; reason: string }
  | { state: 'done'; ticketId: string; reason: string };

interface Attached {
  key: number;
  url: string;
}
let photoKey = 0;

/**
 * Панель ввода. Голос — главный способ: механик говорит, фраза сама уходит в чат.
 * К вопросу можно приложить фото узла: на телефоне кнопка открывает камеру или галерею.
 * Любая фраза идёт агенту как обычное сообщение, инструмент выбирает он.
 */
export function Composer({
  busy,
  canDiagnose,
  onDiagnose,
  ticket,
  onTicket,
  flash = null,
  onSend,
}: {
  busy: boolean;
  canDiagnose: boolean;
  onDiagnose: () => void;
  ticket: TicketButton;
  onTicket: () => void;
  /** Сообщение экрана чата: показывается здесь же, над панелью ввода */
  flash?: Flash | null;
  onSend: (text: string, images: string[]) => void;
}) {
  const [text, setText] = useState('');
  const [photos, setPhotos] = useState<Attached[]>([]);
  const [preparing, setPreparing] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  /** Подсказка, не ошибка: например, почему заявку пока нельзя создать */
  const [info, setInfo] = useState<string | null>(null);
  /** Распознавание на сервере: запись с индикатором уровня, работает в любом браузере с микрофоном */
  const [serverVoice, setServerVoice] = useState(false);
  const [browserVoice, setBrowserVoice] = useState(false);
  const [listening, setListening] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const recRef = useRef<Recognition | null>(null);
  const heardRef = useRef('');
  const busyRef = useRef(busy);
  const sendRef = useRef(onSend);
  const photosRef = useRef(photos);
  busyRef.current = busy;
  sendRef.current = onSend;
  photosRef.current = photos;

  /** Фраза распознана: уходит агенту вместе с приложенными фото */
  const deliver = useCallback((heard: string) => {
    if (busyRef.current) {
      setText(heard); // агент ещё отвечает: текст остаётся в поле
      return;
    }
    sounds.sent();
    sendRef.current(heard, photosRef.current.map((p) => p.url));
    setText('');
    setPhotos([]);
  }, []);

  const voice = useServerVoice({ onText: deliver, onError: setNotice, levelRef: rootRef });
  const recording = voice.state !== 'idle';

  // Конец записи слышно: запись ушла на распознавание (по паузе в речи или по нажатию)
  const voiceStateRef = useRef(voice.state);
  useEffect(() => {
    if (voiceStateRef.current === 'listening' && voice.state === 'transcribing') sounds.stop();
    voiceStateRef.current = voice.state;
  }, [voice.state]);

  const cancelVoice = () => {
    sounds.cancel();
    voice.cancel();
  };

  useEffect(() => {
    setBrowserVoice(Boolean(getRecognition()));
    api
      .config()
      .then((c) => setServerVoice(Boolean(c.stt?.server) && serverVoiceSupported()))
      .catch(() => setServerVoice(false));
    return () => {
      const rec = recRef.current;
      if (rec) {
        rec.onend = null;
        rec.onerror = null;
        rec.onresult = null;
        rec.stop();
      }
    };
  }, []);

  /** Успех: «отправлено администратору» и подобное */
  const [ok, setOk] = useState<string | null>(null);

  // Сообщения экрана чата встают в тот же ряд над панелью ввода
  useEffect(() => {
    if (!flash) return;
    if (flash.kind === 'err') setNotice(flash.text);
    else if (flash.kind === 'ok') setOk(flash.text);
    else setInfo(flash.text);
  }, [flash]);

  // Сообщения сами исчезают через NOTE_MS; полоса внизу сообщения показывает, сколько осталось
  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(null), NOTE_MS);
    return () => clearTimeout(timer);
  }, [notice]);

  useEffect(() => {
    if (!info) return;
    const timer = setTimeout(() => setInfo(null), NOTE_MS);
    return () => clearTimeout(timer);
  }, [info]);

  useEffect(() => {
    if (!ok) return;
    const timer = setTimeout(() => setOk(null), NOTE_MS);
    return () => clearTimeout(timer);
  }, [ok]);

  // Сообщение появляется и уходит сразу, без анимации: полупрозрачный текст поверх переписки выглядел как сбой
  const shownText = notice ?? info ?? ok;
  const shownKind = notice ? 'err' : info ? 'info' : ok ? 'ok' : null;

  const submit = () => {
    if (busy || preparing || (!text.trim() && !photos.length)) return;
    onSend(text, photos.map((p) => p.url));
    setText('');
    setPhotos([]);
  };

  const addFiles = useCallback(async (files: File[]) => {
    const images = files.filter((f) => f.type.startsWith('image/'));
    if (!images.length) {
      if (files.length) setNotice('Приложить можно только фото.');
      return;
    }
    const room = MAX_PHOTOS - photosRef.current.length;
    if (room <= 0) {
      setNotice(`К одному вопросу — не больше ${MAX_PHOTOS} фото.`);
      return;
    }
    if (images.length > room) setNotice(`К одному вопросу — не больше ${MAX_PHOTOS} фото, лишние не добавлены.`);
    setPreparing(true);
    try {
      for (const file of images.slice(0, room)) {
        const url = await photoFromFile(file);
        setPhotos((list) => [...list, { key: ++photoKey, url }]);
      }
    } catch (e) {
      setNotice((e as Error).message);
    } finally {
      setPreparing(false);
    }
  }, []);

  /** Голос в браузере: запасной путь без индикатора уровня */
  const toggleBrowserVoice = useCallback(() => {
    if (recRef.current) {
      recRef.current.stop(); // фраза закончена: сработает onend и отправит распознанное
      return;
    }
    const Ctor = getRecognition();
    if (!Ctor) return;
    const rec = new Ctor();
    rec.lang = SPEECH_LANG;
    rec.interimResults = true;
    rec.continuous = false;
    heardRef.current = '';
    setNotice(null);
    setText('');
    rec.onresult = (e) => {
      let out = '';
      for (let i = 0; i < e.results.length; i++) out += e.results[i][0].transcript;
      heardRef.current = out;
      setText(out);
    };
    rec.onerror = (e) => {
      const message = voiceErrorText(e?.error);
      if (message) setNotice(message);
    };
    rec.onend = () => {
      recRef.current = null;
      setListening(false);
      sounds.stop();
      const heard = heardRef.current.trim();
      heardRef.current = '';
      if (heard) deliver(heard);
    };
    recRef.current = rec;
    sounds.start();
    setListening(true);
    try {
      rec.start();
    } catch {
      recRef.current = null;
      setListening(false);
      setNotice('Не получилось включить микрофон. Повторите.');
    }
  }, [deliver]);

  const onMic = () => {
    if (!serverVoice) {
      toggleBrowserVoice();
      return;
    }
    if (voice.state === 'idle') {
      setNotice(null);
      sounds.start();
      void voice.start();
    } else if (voice.state === 'listening') voice.stop();
  };

  const hasVoice = serverVoice || browserVoice;
  const live = listening || voice.state === 'listening' || voice.state === 'starting';
  const transcribing = voice.state === 'transcribing';
  const micDisabled = serverVoice ? (busy && !recording) || transcribing || voice.state === 'starting' : busy && !listening;
  /** Подсказка в поле ввода, пока идёт запись: сама запись видна по кнопке микрофона */
  const voiceHint = transcribing ? 'Распознаю…' : voice.state === 'starting' ? 'Включаю микрофон…' : 'Говорите';

  /** Недоступная кнопка заявки не глохнет молча: нажатие объясняет, почему её нельзя создать */
  const pressTicket = () => {
    if (ticket.state === 'on') {
      if (!busy) onTicket();
      return;
    }
    setNotice(null);
    setInfo(ticket.reason);
  };

  const onPaste = (e: ClipboardEvent<HTMLInputElement>) => {
    const files = [...e.clipboardData.files];
    if (files.some((f) => f.type.startsWith('image/'))) {
      e.preventDefault();
      void addFiles(files);
    }
  };
  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    if (!e.dataTransfer.files.length) return;
    e.preventDefault();
    void addFiles([...e.dataTransfer.files]);
  };

  return (
    <div
      ref={rootRef}
      className={`ftr composer${hasVoice ? ' has-voice' : ''}${recording ? ' rec' : ''}`}
      onDragOver={(e) => {
        if (e.dataTransfer.types.includes('Files')) e.preventDefault();
      }}
      onDrop={onDrop}
    >
      {shownText || photos.length || preparing ? (
        <div className="cextra">
          {shownText ? (
            <div
              key={`${shownKind}\u0000${shownText}`}
              className={`cnote ${shownKind === 'err' ? 'verr' : shownKind === 'ok' ? 'vok' : 'vinfo'}`}
              role={shownKind === 'err' ? 'alert' : 'status'}
              style={{ '--note-ms': `${NOTE_MS}ms` } as CSSProperties}
            >
              <Icon name={shownKind === 'err' ? 'alert-circle' : shownKind === 'ok' ? 'circle-check' : 'info-circle'} size="s" />
              <span>{shownText}</span>
              <i className="cnote-bar" aria-hidden />
            </div>
          ) : null}
          {photos.length || preparing ? (
            <div className="cphotos">
              {photos.map((p, i) => (
                <span className="cph" key={p.key}>
                  {/* eslint-disable-next-line @next/next/no-img-element -- снимок из памяти браузера, оптимизировать нечего */}
                  <img src={p.url} alt={`Фото ${i + 1}`} />
                  <button
                    type="button"
                    className="cph-x"
                    onClick={() => setPhotos((list) => list.filter((x) => x.key !== p.key))}
                    aria-label={`Убрать фото ${i + 1}`}
                    title="Убрать фото"
                  >
                    <Icon name="x" size="s" />
                  </button>
                </span>
              ))}
              {preparing ? (
                <span className="cph wait" aria-label="Готовлю фото">
                  <Icon name="loader-2" className="spin" />
                </span>
              ) : null}
              <span className="cph-n">
                Фото уйдут вместе с вопросом
                <span className="m">
                  {' '}
                  {photos.length} из {MAX_PHOTOS}
                </span>
              </span>
            </div>
          ) : null}
        </div>
      ) : null}
      {/* Две главные кнопки механика. Места мало (крупный шрифт, открыто руководство) — подписи короче,
          ещё меньше — остаются значки: подпись дублируют title и aria-label. На телефоне — одной строкой, одного размера */}
      <div className="cacts">
        <button
          type="button"
          // Залита та кнопка, что ведёт к следующему шагу: после вердикта с разрешённой заявкой — «Создать заявку»
          className={`btn diag${ticket.state === 'on' && !busy ? '' : ' pri'}`}
          onClick={onDiagnose}
          disabled={busy || !canDiagnose}
          aria-label="Получить результат диагностики"
          title="Получить результат диагностики"
        >
          <Icon name="wave-sine" />
          <span className="lbl lbl-l">Получить результат диагностики</span>
          <span className="lbl lbl-s">Диагностика</span>
        </button>
        <button
          type="button"
          className={`btn tkt${ticket.state === 'on' && !busy ? ' pri' : ''}${ticket.state === 'done' ? ' done' : ''}${ticket.state !== 'on' || busy ? ' off' : ''}`}
          onClick={pressTicket}
          aria-disabled={ticket.state !== 'on' || busy}
          aria-label={ticket.state === 'done' ? `Заявка ${ticket.ticketId} создана` : 'Создать заявку'}
          title={ticket.state === 'on' ? 'Агент соберёт заявку по руководству, перед отправкой вы её подтвердите' : ticket.reason}
        >
          <Icon name={ticket.state === 'done' ? 'clipboard-check' : 'clipboard-list'} />
          {ticket.state === 'done' ? (
            <>
              <span className="lbl lbl-l">Заявка {ticket.ticketId}</span>
              <span className="lbl lbl-s m">{ticket.ticketId}</span>
            </>
          ) : (
            <>
              <span className="lbl lbl-l">Создать заявку</span>
              <span className="lbl lbl-s">Заявка</span>
            </>
          )}
        </button>
      </div>
      <form
        className="cgroup"
        onSubmit={(e) => {
          e.preventDefault();
          if (voice.state === 'listening') voice.stop();
          else submit();
        }}
      >
        {hasVoice ? (
          // Запись видна по самой кнопке: внутри неё столбики идут за голосом. Нажатие заканчивает фразу и отправляет
          <button
            type="button"
            className={`btn ic mic${live ? ' live' : ''}${transcribing ? ' wait' : ''}`}
            onClick={onMic}
            disabled={micDisabled}
            aria-label={transcribing ? 'Распознаю речь' : live ? 'Закончить и отправить' : 'Сказать голосом'}
            aria-pressed={live}
            title={live ? 'Идёт запись. Нажмите, чтобы закончить и отправить' : 'Сказать голосом: фраза сама уйдёт агенту'}
          >
            {transcribing ? (
              <Icon name="loader-2" size="l" className="spin" />
            ) : live ? (
              <span className="mlv" aria-hidden>
                <i />
                <i />
                <i />
                <i />
              </span>
            ) : (
              <Icon name="microphone" size="l" />
            )}
          </button>
        ) : null}
        <button
          type="button"
          className="btn ic photo"
          onClick={() => fileRef.current?.click()}
          disabled={recording || listening || preparing || photos.length >= MAX_PHOTOS}
          aria-label="Фото узла: сфотографировать или выбрать"
          title="Фото узла: сфотографировать или выбрать снимок"
        >
          <Icon name="camera" />
        </button>
        <input
          ref={fileRef}
          type="file"
          accept="image/*"
          multiple
          hidden
          onChange={(e) => {
            const files = [...(e.target.files ?? [])];
            e.target.value = '';
            void addFiles(files);
          }}
        />
        <input
          className={`inp${live || transcribing ? ' live' : ''}`}
          value={recording ? '' : text}
          onChange={(e) => setText(e.target.value)}
          onPaste={onPaste}
          placeholder={
            recording ? voiceHint : listening ? 'Говорите' : photos.length ? 'Вопрос к фото' : hasVoice ? 'Ваш вопрос' : 'Вопрос по руководству или команда'
          }
          aria-label="Вопрос агенту"
          enterKeyHint="send"
          readOnly={listening || recording}
        />
        {/* Во время записи на месте отправки — отмена: запись выбрасывается, ничего не уходит */}
        {voice.state === 'listening' || voice.state === 'starting' ? (
          <button type="button" className="btn ic vx" onClick={cancelVoice} aria-label="Отменить запись" title="Отменить запись">
            <Icon name="x" />
          </button>
        ) : (
          <button
            type="submit"
            className="btn ic"
            disabled={busy || listening || recording || preparing || (!text.trim() && !photos.length)}
            aria-label="Отправить"
          >
            <Icon name="arrow-up" />
          </button>
        )}
      </form>
    </div>
  );
}
