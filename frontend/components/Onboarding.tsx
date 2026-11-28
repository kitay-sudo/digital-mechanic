'use client';

import { useCallback, useEffect, useRef, useState, useSyncExternalStore, type ReactNode, type TouchEvent as ReactTouchEvent } from 'react';
import { usePresence } from '@/lib/presence';
import { setSettings, useSettings } from '@/lib/settings';
import { PriorityBadge, StatusBadge } from './Badges';
import { Icon } from './Icon';
import { CylinderBlueprint, InjectorBlueprint, RodBlueprint } from './Blueprints';

/* ---------- Повторный показ из настроек ---------- */

let replay = false;
const replayListeners = new Set<() => void>();

function setReplay(next: boolean): void {
  replay = next;
  replayListeners.forEach((l) => l());
}

/** Открыть обучение ещё раз, например из настроек. Согласие повторно не спрашивается. */
export function openTour(): void {
  setReplay(true);
}

function useReplay(): boolean {
  return useSyncExternalStore(
    (l) => {
      replayListeners.add(l);
      return () => replayListeners.delete(l);
    },
    () => replay,
    () => false,
  );
}

/* ---------- Слайды ---------- */

interface Slide {
  kicker: string;
  title: string;
  text: string;
  points?: string[];
  visual: ReactNode;
}

/** Картинки слайдов собраны из настоящих элементов интерфейса: механик потом увидит их же. */
const SLIDES: Slide[] = [
  {
    kicker: 'Что это',
    title: 'Помощник механика по двигателю',
    text: 'Система разбирает результат проверки двигателя по звуку, отвечает на вопросы по руководству и помогает оформить заявку на дефектовку.',
    visual: (
      <div className="tv-list">
        <div className="tv-feat">
          <Icon name="wave-sine" size="l" />
          <div>
            <b>Результат проверки</b>
            <span>Понятными словами: что найдено и что делать</span>
          </div>
        </div>
        <div className="tv-feat">
          <Icon name="book-2" size="l" />
          <div>
            <b>Ответ по руководству</b>
            <span>Со ссылкой на страницу, цифры только из документа</span>
          </div>
        </div>
        <div className="tv-feat">
          <Icon name="clipboard-check" size="l" />
          <div>
            <b>Заявка в ТОиР</b>
            <span>Оформляется только после вашего подтверждения</span>
          </div>
        </div>
      </div>
    ),
  },
  {
    kicker: 'Шаг 1',
    title: 'Выберите машину',
    text: 'В разделе «Парк» собраны все машины. Сверху те, кому нужна дефектовка. Нажмите строку, чтобы открыть машину.',
    visual: (
      <div className="tv-rows">
        <div className="tv-row hot">
          <span className="m">A001MC178</span>
          <span className="nm">УАЗ Патриот</span>
          <StatusBadge status="anomaly" code="F01" />
        </div>
        <div className="tv-row warn pick">
          <span className="m">T792HO98</span>
          <span className="nm">Урал-5557</span>
          <StatusBadge status="anomaly" code="F02" />
          <Icon name="hand-click" className="tv-tap" />
        </div>
        <div className="tv-row">
          <span className="m">K208OP54</span>
          <span className="nm">МАЗ-5337</span>
          <StatusBadge status="normal" />
        </div>
      </div>
    ),
  },
  {
    kicker: 'Шаг 2',
    title: 'Получите результат диагностики',
    text: 'Одна кнопка внизу экрана. Система покажет один из трёх исходов и скажет, что делать дальше.',
    visual: (
      <div className="tv-col">
        <span className="btn pri tv-btn">
          <Icon name="wave-sine" />
          Получить результат диагностики
        </span>
        <div className="tv-out">
          <div>
            <StatusBadge status="normal" />
            <span>Можно работать дальше</span>
          </div>
          <div>
            <StatusBadge status="anomaly" code="F02" />
            <span>Что проверить и насколько срочно</span>
          </div>
          <div>
            <StatusBadge status="check_failed" />
            <span>Запись нужно повторить</span>
          </div>
        </div>
      </div>
    ),
  },
  {
    kicker: 'Шаг 3',
    title: 'Спросите голосом или текстом',
    text: 'Нажмите микрофон и скажите вопрос: он сам уйдёт агенту. В ответе будет ссылка на страницу руководства. Нажмите её, и страница откроется.',
    visual: (
      <div className="tv-col">
        <div className="tv-ask">
          <span className="btn ic mic tv-btn">
            <Icon name="microphone" size="l" />
          </span>
          <span className="inp tv-inp">Какой момент затяжки головки?</span>
        </div>
        <div className="tv-ans">
          <span>Затянуть в два этапа, порядок по рисунку.</span>
          <span className="src">
            <Icon name="file-text" size="s" />
            РЭ ЗМЗ-409
            <span className="pg">стр. 180</span>
          </span>
        </div>
      </div>
    ),
  },
  {
    kicker: 'Шаг 4',
    title: 'Отмечайте шаги и оформляйте заявку',
    text: 'Сделали шаг, отметьте его. Кнопка «Создать заявку» стоит рядом с диагностикой и включается, когда заявку можно оформить. Состав и приоритет вы проверяете и подтверждаете сами.',
    visual: (
      <div className="tv-col">
        <div className="tv-steps">
          <div className="tv-step done">
            <span className="chk">
              <Icon name="check" />
            </span>
            <span>Замерить давление масла манометром</span>
          </div>
          <div className="tv-step">
            <span className="chk">2</span>
            <span>Проверить заборник масляного насоса</span>
          </div>
        </div>
        <div className="tv-ticket">
          <PriorityBadge priority="high" long />
          <span className="btn pri tv-btn">
            <Icon name="clipboard-plus" />
            Создать заявку
          </span>
        </div>
      </div>
    ),
  },
];

const CONSENT_TEXT =
  'Сервис хранит историю чата и заявок. Голос записывается, только пока горит кнопка микрофона. Запись уходит на распознавание речи, звук система не сохраняет. Данные машин синтетические.';

/**
 * Обучение при первом открытии: что система умеет и как с ней работать.
 * Пропустить нельзя, последний слайд — согласие на обработку данных (152-ФЗ).
 * Повторный показ из настроек идёт без согласия и закрывается в любой момент.
 */
export function Onboarding() {
  const settings = useSettings();
  const again = useReplay();
  const [mounted, setMounted] = useState(false);
  const [index, setIndex] = useState(0);
  const [back, setBack] = useState(false);
  const [checked, setChecked] = useState(false);
  const touchX = useRef<number | null>(null);

  // До чтения настроек из браузера экран не показываем, иначе он мигнёт у согласившихся
  useEffect(() => setMounted(true), []);

  const first = mounted && !settings.consent;
  const view = usePresence(first || again ? true : null);
  const shown = Boolean(view.shown);
  // Согласие спрашиваем только при первом показе
  const withConsent = first || (view.leaving && !again && checked);
  const total = SLIDES.length + (withConsent ? 1 : 0);
  const last = index >= total - 1;
  const onConsent = withConsent && last;

  // Каждый новый показ начинается с первого слайда
  useEffect(() => {
    if (shown) return;
    setIndex(0);
    setBack(false);
  }, [shown]);

  // Пока идёт обучение, остальной интерфейс недоступен ни мышью, ни клавиатурой
  useEffect(() => {
    if (!shown) return;
    const shell = document.querySelector('.shell');
    shell?.setAttribute('inert', '');
    return () => shell?.removeAttribute('inert');
  }, [shown]);

  const finish = useCallback(() => {
    if (first) {
      if (!checked) return;
      setSettings({ consent: true });
    }
    setReplay(false);
  }, [first, checked]);

  const next = useCallback(() => {
    if (last) {
      finish();
      return;
    }
    setBack(false);
    setIndex((i) => Math.min(i + 1, total - 1));
  }, [last, finish, total]);

  const prev = useCallback(() => {
    setBack(true);
    setIndex((i) => Math.max(i - 1, 0));
  }, []);

  useEffect(() => {
    if (!shown || view.leaving) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'ArrowRight') next();
      else if (e.key === 'ArrowLeft') prev();
      else if (e.key === 'Escape' && !first) setReplay(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [shown, view.leaving, next, prev, first]);

  if (!shown) return null;

  const slide = index < SLIDES.length ? SLIDES[index] : null;

  // Листание пальцем на телефоне. Закончить обучение можно только кнопкой
  const onTouchStart = (e: ReactTouchEvent) => {
    touchX.current = e.touches[0]?.clientX ?? null;
  };
  const onTouchEnd = (e: ReactTouchEvent) => {
    const start = touchX.current;
    touchX.current = null;
    if (start === null) return;
    const dx = (e.changedTouches[0]?.clientX ?? start) - start;
    if (dx < -60 && !last) next();
    else if (dx > 60) prev();
  };

  return (
    <div
      className={`tour${view.leaving ? ' leaving' : ''}`}
      role="dialog"
      aria-modal="true"
      aria-label="Знакомство с системой"
      onTouchStart={onTouchStart}
      onTouchEnd={onTouchEnd}
    >
      {/* Чертёж во всю высоту слева от текста: у слайдов по очереди разрез цилиндра, поршень с шатуном и форсунка */}
      <div className="tour-art" aria-hidden="true" key={`art-${index % 3}`}>
        {index % 3 === 0 ? (
          <CylinderBlueprint className="tour-bp" />
        ) : index % 3 === 1 ? (
          <RodBlueprint className="tour-bp" />
        ) : (
          <InjectorBlueprint className="tour-bp" />
        )}
      </div>
      <div className="tour-top">
        <span className="logo">
          <Icon name="engine" size="l" />
          Цифровой механик
        </span>
        {!first ? (
          <button type="button" className="hb" onClick={() => setReplay(false)} aria-label="Закрыть обучение" title="Закрыть">
            <Icon name="x" />
          </button>
        ) : null}
      </div>

      <div className={`tour-main${back ? ' back' : ''}`} key={index}>
        <div className="tour-text">
          <div className="tour-kick">{slide ? slide.kicker : 'Последний шаг'}</div>
          <h1>{slide ? slide.title : 'Согласие на обработку данных'}</h1>
          <p>{slide ? slide.text : CONSENT_TEXT}</p>
          {onConsent ? (
            <label className="tour-ack">
              <span>Согласен на обработку данных</span>
              <input type="checkbox" role="switch" className="switch" checked={checked} onChange={(e) => setChecked(e.target.checked)} />
            </label>
          ) : null}
        </div>
        <div className="tour-vis" aria-hidden="true">
          {slide ? (
            slide.visual
          ) : (
            <div className="tv-list">
              <div className="tv-feat">
                <Icon name="shield-check" size="l" />
                <div>
                  <b>Что хранится</b>
                  <span>История чата и заявок по машинам</span>
                </div>
              </div>
              <div className="tv-feat">
                <Icon name="microphone" size="l" />
                <div>
                  <b>Голос</b>
                  <span>Только пока горит микрофон, звук не хранится</span>
                </div>
              </div>
              <div className="tv-feat">
                <Icon name="database" size="l" />
                <div>
                  <b>Данные машин</b>
                  <span>Синтетические, настоящих сведений нет</span>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="tour-bot">
        {/* Индикатор шагов: короткие метки, текущая длиннее, рядом счётчик */}
        <div className="tour-prog">
          <span className="tour-dots" aria-hidden="true">
            {Array.from({ length: total }, (_, i) => (
              <i key={i} className={i < index ? 'done' : i === index ? 'on' : ''} />
            ))}
          </span>
          <span className="tour-count m" aria-live="polite">
            {index + 1} из {total}
          </span>
        </div>
        {/* Кнопки одного размера и стоят рядом */}
        <div className="tour-nav">
          <button type="button" className="btn" onClick={prev} disabled={index === 0}>
            <Icon name="arrow-left" />
            Назад
          </button>
          <button type="button" className="btn pri" onClick={next} disabled={onConsent && !checked}>
            {last ? (first ? 'Начать работу' : 'Понятно') : 'Далее'}
            {last ? null : <Icon name="arrow-right" />}
          </button>
        </div>
      </div>
    </div>
  );
}
