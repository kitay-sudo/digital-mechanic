'use client';

import Link from 'next/link';
import { useCallback, useEffect, useRef, useState } from 'react';
import type { Session } from '@/lib/types';
import { Icon } from './Icon';
import { ScoreChart } from './ScoreChart';

/** Насколько надо стянуть панель вниз, чтобы она закрылась */
const SWIPE_CLOSE = 72;
/** Запас на случай, если событие конца анимации не пришло */
const CLOSE_TIMEOUT = 400;

/** Что показывает график и куда из него можно уйти. Общее для панели на телефоне и блока под строкой на компьютере. */
interface ChartProps {
  sessions: Session[];
  /** Проверка, строку которой нажали: она выделена на графике */
  selected: string;
  trendIcon: string;
  trendText: string;
  /** Адрес чата с этой проверкой */
  chatHref: string;
}

/** Ширина блока под график: график рисуется в настоящих пикселях, подписи не мельчают и не раздуваются. */
function useWidth(ref: React.RefObject<HTMLDivElement | null>, active: boolean): number {
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!active || !el) return;
    const measure = () => setWidth(Math.round(el.clientWidth));
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, [ref, active]);
  return width;
}

/**
 * Тенденция двумя строками: вывод крупно, цифры под ним.
 * Сервер присылает её одной фразой «…: с 0,39 до 0,92», делим по двоеточию.
 */
function Trend({ icon, text }: { icon: string; text: string }) {
  const cut = text.indexOf(': ');
  const head = cut > 0 ? text.slice(0, cut) : text;
  const tail = cut > 0 ? text.slice(cut + 2) : '';
  const tone = icon.includes('up') ? ' up' : icon.includes('down') ? ' down' : '';
  return (
    <div className={`cs-trend${tone}`}>
      <Icon name={icon} />
      <div>
        <div className="cs-th">{head}</div>
        {tail ? <div className="cs-tt m">{tail}</div> : null}
      </div>
    </div>
  );
}

function Legend() {
  return (
    <div className="cs-leg">
      <span>
        <b className="cs-mk">
          <i className="cs-dot cs-dot-a" />
        </b>
        отклонение
      </span>
      <span>
        <b className="cs-mk">
          <i className="cs-dot" />
        </b>
        норма
      </span>
      <span>
        <b className="cs-mk">
          <Icon name="x" size="s" />
        </b>
        сбой записи
      </span>
      <span>
        <b className="cs-mk">
          <i className="cs-bar" />
        </b>
        эта проверка
      </span>
      <span>
        <b className="cs-mk">
          <i className="cs-dash" />
        </b>
        порог 0,5
      </span>
    </div>
  );
}

function Chart({ sessions, selected, active, max }: { sessions: Session[]; selected: string; active: boolean; max: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const width = useWidth(ref, active);
  const w = Math.max(280, Math.min(width || 340, max));
  const h = Math.round(Math.max(150, Math.min(w * 0.36, 240)));
  return (
    // Ширину меряем у блока без отступов: график рисуется точно в свой размер
    <div ref={ref}>{active && width ? <ScoreChart sessions={sessions} selected={selected} width={w} height={h} /> : null}</div>
  );
}

/**
 * Компьютер: график выпадает под строкой проверки, без затемнения и без модального окна.
 * closing включается на время сворачивания, чтобы блок ушёл плавно.
 */
export function ChartDrop({ sessions, selected, trendIcon, trendText, chatHref, closing }: ChartProps & { closing: boolean }) {
  return (
    <div className={`cdrop${closing ? ' closing' : ''}`} role="region" aria-label={`График оценки отклонения, проверка ${selected}`}>
      <div className="cdrop-clip">
        <div className="cdrop-in">
          <Chart sessions={sessions} selected={selected} active max={760} />
          {/* Справа от графика: вывод по тенденции, что значат знаки на графике, переход в чат */}
          <div className="cd-side">
            <div className="cd-blk box">
              <div className="cd-l">Тенденция</div>
              <Trend icon={trendIcon} text={trendText} />
            </div>
            <div className="cd-blk">
              <div className="cd-l">Обозначения</div>
              <Legend />
            </div>
            <Link href={chatHref} className="btn pri cd-go" tabIndex={closing ? -1 : undefined}>
              <Icon name="message-2" />
              Разобрать {selected} в чате
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}

/**
 * Телефон и планшет: график в панели, которая выезжает снизу поверх размытого экрана.
 * Закрывается касанием пустого места, кнопкой, клавишей Esc или движением вниз.
 */
export function ChartSheet({
  open,
  onClose,
  sessions,
  selected,
  trendIcon,
  trendText,
  chatHref,
}: ChartProps & { open: boolean; onClose: () => void }) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const drag = useRef<{ id: number; y: number; dy: number } | null>(null);

  /** Плавное закрытие: сначала уезжает панель, потом диалог закрывается на самом деле. */
  const requestClose = useCallback(() => {
    const dialog = dialogRef.current;
    if (!dialog || !dialog.open || dialog.hasAttribute('data-closing')) return;
    dialog.setAttribute('data-closing', '');
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      dialog.removeAttribute('data-closing');
      // Сдвиг от движения пальцем держим до конца: панель уезжает с того места, где её отпустили
      dialog.style.translate = '';
      if (dialog.open) dialog.close();
    };
    const animations = dialog.getAnimations({ subtree: true });
    if (animations.length) void Promise.allSettled(animations.map((a) => a.finished)).then(finish);
    window.setTimeout(finish, animations.length ? CLOSE_TIMEOUT : 0);
  }, []);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) requestClose();
  }, [open, requestClose]);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    // Esc и касание фона идут через то же плавное закрытие
    const onCancel = (event: Event) => {
      event.preventDefault();
      requestClose();
    };
    const onClosed = () => onClose();
    // Запасной путь для браузеров без closedby: касание мимо панели попадает в сам диалог
    const onClick = (event: MouseEvent) => {
      if ('closedBy' in HTMLDialogElement.prototype || event.target !== dialog) return;
      const rect = dialog.getBoundingClientRect();
      const inside =
        rect.top <= event.clientY && event.clientY <= rect.bottom && rect.left <= event.clientX && event.clientX <= rect.right;
      if (!inside) requestClose();
    };
    dialog.addEventListener('cancel', onCancel);
    dialog.addEventListener('close', onClosed);
    dialog.addEventListener('click', onClick);
    return () => {
      dialog.removeEventListener('cancel', onCancel);
      dialog.removeEventListener('close', onClosed);
      dialog.removeEventListener('click', onClick);
    };
  }, [onClose, requestClose]);

  /* Движение вниз: панель едет за пальцем, после порога закрывается, иначе возвращается */
  const onPointerDown = (event: React.PointerEvent<HTMLDialogElement>) => {
    if ((event.target as HTMLElement).closest('button, a')) return;
    drag.current = { id: event.pointerId, y: event.clientY, dy: 0 };
  };
  const onPointerMove = (event: React.PointerEvent<HTMLDialogElement>) => {
    const d = drag.current;
    const dialog = dialogRef.current;
    if (!d || !dialog || d.id !== event.pointerId) return;
    d.dy = Math.max(0, event.clientY - d.y);
    if (d.dy > 4 && !dialog.hasPointerCapture(d.id)) dialog.setPointerCapture(d.id);
    dialog.style.transition = 'none';
    dialog.style.translate = `0 ${d.dy}px`;
  };
  const onPointerEnd = (event: React.PointerEvent<HTMLDialogElement>) => {
    const d = drag.current;
    const dialog = dialogRef.current;
    if (!d || !dialog || d.id !== event.pointerId) return;
    drag.current = null;
    dialog.style.transition = '';
    if (d.dy >= SWIPE_CLOSE) requestClose();
    else dialog.style.translate = '';
  };

  return (
    <dialog
      ref={dialogRef}
      className="csheet"
      aria-labelledby="csheet-title"
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerEnd}
      onPointerCancel={onPointerEnd}
      {...({ closedby: 'any' } as object)}
    >
      <div className="cs-grab" aria-hidden="true" />
      <div className="cs-h">
        <b id="csheet-title">Оценка отклонения</b>
        <span className="cs-note m">{selected}</span>
        <button type="button" className="hb" onClick={requestClose} aria-label="Закрыть график" title="Закрыть">
          <Icon name="x" />
        </button>
      </div>
      <div className="cs-chart">
        <Chart sessions={sessions} selected={selected} active={open} max={760} />
      </div>
      <div className="cs-cap">
        <Trend icon={trendIcon} text={trendText} />
      </div>
      <Legend />
      <div className="cs-foot">
        <Link href={chatHref} className="btn pri">
          <Icon name="message-2" />
          Разобрать {selected} в чате
        </Link>
      </div>
    </dialog>
  );
}
