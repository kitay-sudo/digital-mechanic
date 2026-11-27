'use client';

import { type RefObject, useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, api } from './api';
import { inAppShell } from './pwa';

/**
 * Голос через сервер: браузер записывает фразу, сервер распознаёт её (ProxyAPI или свой Whisper).
 *
 * Пока идёт запись, уровень звука пишется в CSS-переменную --lv (от 0 до 1) на элементе levelRef:
 * механик видит, что микрофон его слышит. Фраза заканчивается сама — после паузы в речи.
 */
export type VoiceState = 'idle' | 'starting' | 'listening' | 'transcribing';

const SILENCE_MS = 1600; // пауза после речи: фраза закончена, запись уходит на распознавание
const NO_SPEECH_MS = 7000; // столько ждём, что механик заговорит
const MAX_MS = 45_000; // самая длинная фраза
const MIN_SPEECH_MS = 250; // меньше речи — это шум, а не фраза
const TICK_MS = 50; // как часто меряем уровень звука

const MIME_TYPES = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus'];

export function serverVoiceSupported(): boolean {
  return (
    typeof window !== 'undefined' &&
    typeof MediaRecorder !== 'undefined' &&
    Boolean(navigator.mediaDevices?.getUserMedia)
  );
}

function pickMime(): string {
  return MIME_TYPES.find((t) => MediaRecorder.isTypeSupported?.(t)) ?? '';
}

function micError(e: unknown): string {
  switch ((e as { name?: string })?.name) {
    case 'NotAllowedError':
    case 'SecurityError':
      return inAppShell()
        ? 'Нет доступа к микрофону. Разрешите его приложению в настройках телефона.'
        : 'Нет доступа к микрофону. Разрешите его в настройках браузера.';
    case 'NotFoundError':
    case 'OverconstrainedError':
      return 'Микрофон не найден.';
    case 'NotReadableError':
      return 'Микрофон занят другим приложением.';
    default:
      return 'Не получилось включить микрофон. Повторите.';
  }
}

interface Run {
  stream: MediaStream;
  audio: AudioContext;
  rec: MediaRecorder;
  chunks: Blob[];
  timer: number;
  started: number;
  lastTick: number;
  lastVoice: number;
  speechMs: number;
  noise: number;
  hearing: boolean;
  second: number;
  stopping: boolean;
  send: boolean;
}

export function useServerVoice({
  onText,
  onError,
  levelRef,
}: {
  onText: (text: string) => void;
  onError: (message: string) => void;
  levelRef: RefObject<HTMLElement | null>;
}) {
  const [state, setState] = useState<VoiceState>('idle');
  /** Голос слышен прямо сейчас */
  const [hearing, setHearing] = useState(false);
  /** Речь в этой записи уже была */
  const [heard, setHeard] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const runRef = useRef<Run | null>(null);
  const onTextRef = useRef(onText);
  const onErrorRef = useRef(onError);
  onTextRef.current = onText;
  onErrorRef.current = onError;

  const setLevel = useCallback(
    (lv: number) => {
      levelRef.current?.style.setProperty('--lv', lv.toFixed(3));
    },
    [levelRef],
  );

  const release = useCallback(
    (run: Run) => {
      window.clearInterval(run.timer);
      run.stream.getTracks().forEach((t) => t.stop());
      void run.audio.close().catch(() => undefined);
      setLevel(0);
    },
    [setLevel],
  );

  /** Закончить запись: send — отправить на распознавание, иначе выбросить */
  const finish = useCallback((send: boolean) => {
    const run = runRef.current;
    if (!run || run.stopping) return;
    run.stopping = true;
    run.send = send;
    if (run.rec.state !== 'inactive') run.rec.stop();
  }, []);

  const start = useCallback(async () => {
    if (runRef.current) return;
    if (!window.isSecureContext) {
      onErrorRef.current('Голос работает только по защищённому адресу (https).');
      return;
    }
    setState('starting');
    setHeard(false);
    setHearing(false);
    setElapsed(0);
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
    } catch (e) {
      setState('idle');
      onErrorRef.current(micError(e));
      return;
    }
    const Ctx = window.AudioContext ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    const audio = new Ctx();
    void audio.resume().catch(() => undefined);
    const analyser = audio.createAnalyser();
    analyser.fftSize = 1024;
    audio.createMediaStreamSource(stream).connect(analyser);
    const samples = new Float32Array(analyser.fftSize);
    const mime = pickMime();
    let rec: MediaRecorder;
    try {
      rec = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream);
    } catch {
      stream.getTracks().forEach((t) => t.stop());
      void audio.close().catch(() => undefined);
      setState('idle');
      onErrorRef.current('Браузер не умеет записывать звук. Введите вопрос текстом.');
      return;
    }
    const now = performance.now();
    const run: Run = {
      stream, audio, rec, chunks: [], timer: 0, started: now, lastTick: now, lastVoice: now,
      speechMs: 0, noise: 0, hearing: false, second: 0, stopping: false, send: false,
    };
    runRef.current = run;

    rec.ondataavailable = (e) => {
      if (e.data.size) run.chunks.push(e.data);
    };
    rec.onstop = async () => {
      release(run);
      runRef.current = null;
      setHearing(false);
      if (!run.send) {
        setState('idle');
        return;
      }
      if (run.speechMs < MIN_SPEECH_MS) {
        setState('idle');
        onErrorRef.current('Не слышу вас. Говорите ближе к микрофону и повторите.');
        return;
      }
      setState('transcribing');
      try {
        const blob = new Blob(run.chunks, { type: rec.mimeType || mime || 'audio/webm' });
        const { text } = await api.stt(blob, (performance.now() - run.started) / 1000);
        setState('idle');
        if (text.trim()) onTextRef.current(text.trim());
        else onErrorRef.current('Не разобрал слова. Повторите чуть громче.');
      } catch (e) {
        setState('idle');
        onErrorRef.current(e instanceof ApiError ? e.message : 'Не получилось распознать речь. Повторите или введите текст.');
      }
    };

    const tick = () => {
      if (run.stopping) return;
      const t = performance.now();
      // В фоне таймер срабатывает реже: один замер не должен засчитать секунду речи
      const dt = Math.min(t - run.lastTick, TICK_MS * 2);
      run.lastTick = t;
      analyser.getFloatTimeDomainData(samples);
      let sum = 0;
      for (let i = 0; i < samples.length; i++) sum += samples[i] * samples[i];
      const rms = Math.sqrt(sum / samples.length);
      // Шум помещения: быстро опускается к тишине и медленно растёт, речь его не поднимает
      run.noise = run.noise === 0 ? rms : rms < run.noise ? rms : run.noise + (rms - run.noise) * 0.002;
      const voice = rms > Math.max(0.012, run.noise * 3);
      // Шкала для глаза: от -60 дБ (тишина) до -12 дБ (громкая речь у телефона)
      const db = 20 * Math.log10(rms + 1e-9);
      setLevel(Math.min(1, Math.max(0, (db + 60) / 48)));
      if (voice) {
        run.speechMs += dt;
        run.lastVoice = t;
        if (run.speechMs >= MIN_SPEECH_MS) setHeard(true);
      }
      if (voice !== run.hearing) {
        run.hearing = voice;
        setHearing(voice);
      }
      const second = Math.floor((t - run.started) / 1000);
      if (second !== run.second) {
        run.second = second;
        setElapsed(second);
      }
      const spoke = run.speechMs >= MIN_SPEECH_MS;
      if ((spoke && t - run.lastVoice > SILENCE_MS) || (!spoke && t - run.started > NO_SPEECH_MS) || t - run.started > MAX_MS) {
        finish(true);
      }
    };

    rec.start(250);
    setState('listening');
    // Таймер, а не кадры анимации: кадры не идут, когда экран погас или браузер свёрнут, а запись идёт
    run.timer = window.setInterval(tick, TICK_MS);
  }, [finish, release, setLevel]);

  // Уход со страницы: микрофон выключается, запись выбрасывается
  useEffect(() => () => finish(false), [finish]);

  return {
    state,
    hearing,
    heard,
    elapsed,
    start,
    /** Закончить и отправить сейчас */
    stop: useCallback(() => finish(true), [finish]),
    /** Выбросить запись */
    cancel: useCallback(() => finish(false), [finish]),
  };
}
