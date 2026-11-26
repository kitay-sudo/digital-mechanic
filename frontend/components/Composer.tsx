'use client';

import { useEffect, useRef, useState } from 'react';
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
  onerror: (() => void) | null;
  start: () => void;
  stop: () => void;
}
type RecognitionCtor = new () => Recognition;

function getRecognition(): RecognitionCtor | null {
  if (typeof window === 'undefined') return null;
  const w = window as unknown as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

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
  const recRef = useRef<Recognition | null>(null);

  useEffect(() => {
    setVoice(Boolean(getRecognition()));
    return () => recRef.current?.stop();
  }, []);

  const submit = () => {
    if (busy || !text.trim()) return;
    onSend(text);
    setText('');
  };

  const toggleVoice = () => {
    if (listening) {
      recRef.current?.stop();
      return;
    }
    const Ctor = getRecognition();
    if (!Ctor) return;
    const rec = new Ctor();
    rec.lang = 'ru-RU';
    rec.interimResults = true;
    rec.continuous = false;
    rec.onresult = (e) => {
      let out = '';
      for (let i = 0; i < e.results.length; i++) out += e.results[i][0].transcript;
      setText(out);
    };
    rec.onend = () => setListening(false);
    rec.onerror = () => setListening(false);
    recRef.current = rec;
    setListening(true);
    rec.start();
  };

  return (
    <div className="ftr composer">
      <button type="button" className="btn pri" onClick={onDiagnose} disabled={busy || !canDiagnose}>
        <Icon name="wave-sine" />
        Получить результат диагностики
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
            className={`btn ic${listening ? ' on' : ''}`}
            onClick={toggleVoice}
            disabled={busy}
            aria-label={listening ? 'Остановить запись голоса' : 'Задать вопрос голосом'}
            title={listening ? 'Слушаю… нажмите, чтобы остановить' : 'Задать вопрос голосом'}
          >
            <Icon name={listening ? 'player-stop' : 'microphone'} />
          </button>
        ) : null}
        <input
          className="inp"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={listening ? 'Слушаю…' : 'Вопрос по руководству или команда'}
          aria-label="Вопрос агенту"
          enterKeyHint="send"
        />
        <button type="submit" className="btn ic" disabled={busy || !text.trim()} aria-label="Отправить">
          <Icon name="arrow-up" />
        </button>
      </form>
    </div>
  );
}
