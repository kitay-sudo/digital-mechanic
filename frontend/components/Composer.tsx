'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { Icon } from './Icon';

/* Распознавание речи браузера. Типов в lib.dom нет, описываем нужное сами. */
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

/**
 * Панель ввода. Голос — главный способ: механик говорит, фраза сама уходит в чат.
 * Любая фраза идёт агенту как обычное сообщение, инструмент выбирает он.
 */
export function Composer({
  busy,
  canDiagnose,
  onDiagnose,
  onSend,
}: {
  busy: boolean;
  canDiagnose: boolean;
  onDiagnose: () => void;
  onSend: (text: string) => void;
}) {
  const [text, setText] = useState('');
  const [voice, setVoice] = useState(false);
  const [listening, setListening] = useState(false);
  const [voiceError, setVoiceError] = useState<string | null>(null);
  const recRef = useRef<Recognition | null>(null);
  const heardRef = useRef('');
  const busyRef = useRef(busy);
  const sendRef = useRef(onSend);
  busyRef.current = busy;
  sendRef.current = onSend;

  useEffect(() => {
    setVoice(Boolean(getRecognition()));
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

  // Сообщение об ошибке голоса само исчезает
  useEffect(() => {
    if (!voiceError) return;
    const timer = setTimeout(() => setVoiceError(null), 6000);
    return () => clearTimeout(timer);
  }, [voiceError]);

  const submit = () => {
    if (busy || !text.trim()) return;
    onSend(text);
    setText('');
  };

  const toggleVoice = useCallback(() => {
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
    setVoiceError(null);
    setText('');
    rec.onresult = (e) => {
      let out = '';
      for (let i = 0; i < e.results.length; i++) out += e.results[i][0].transcript;
      heardRef.current = out;
      setText(out);
    };
    rec.onerror = (e) => {
      const message = voiceErrorText(e?.error);
      if (message) setVoiceError(message);
    };
    rec.onend = () => {
      recRef.current = null;
      setListening(false);
      const heard = heardRef.current.trim();
      heardRef.current = '';
      if (!heard) return;
      if (busyRef.current) return; // агент ещё отвечает: текст остаётся в поле
      sendRef.current(heard);
      setText('');
    };
    recRef.current = rec;
    setListening(true);
    try {
      rec.start();
    } catch {
      recRef.current = null;
      setListening(false);
      setVoiceError('Не получилось включить микрофон. Повторите.');
    }
  }, []);

  return (
    <div className={`ftr composer${voice ? ' has-voice' : ''}`}>
      {voiceError ? (
        <div className="verr" role="alert">
          <Icon name="microphone-off" size="s" />
          {voiceError}
        </div>
      ) : null}
      {/* В узкой колонке (открыто руководство) от кнопки остаётся значок: подпись дублируют title и aria-label */}
      <button
        type="button"
        className="btn pri diag"
        onClick={onDiagnose}
        disabled={busy || !canDiagnose}
        aria-label="Получить результат диагностики"
        title="Получить результат диагностики"
      >
        <Icon name="wave-sine" />
        <span className="lbl">Получить результат диагностики</span>
      </button>
      <form
        className="cgroup"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        {voice ? (
          <button
            type="button"
            className={`btn ic mic${listening ? ' live' : ''}`}
            onClick={toggleVoice}
            disabled={busy && !listening}
            aria-label={listening ? 'Закончить и отправить' : 'Сказать голосом'}
            aria-pressed={listening}
            title={listening ? 'Слушаю… нажмите, чтобы закончить и отправить' : 'Сказать голосом: фраза сама уйдёт агенту'}
          >
            <Icon name={listening ? 'player-stop' : 'microphone'} size="l" />
          </button>
        ) : null}
        <input
          className={`inp${listening ? ' live' : ''}`}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={listening ? 'Слушаю…' : voice ? 'Ваш вопрос' : 'Вопрос по руководству или команда'}
          aria-label="Вопрос агенту"
          enterKeyHint="send"
          readOnly={listening}
        />
        <button type="submit" className="btn ic" disabled={busy || listening || !text.trim()} aria-label="Отправить">
          <Icon name="arrow-up" />
        </button>
      </form>
    </div>
  );
}
