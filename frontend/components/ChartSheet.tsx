'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import type { Session } from '@/lib/types';
import { Icon } from './Icon';
import { ScoreChart } from './ScoreChart';

/** Насколько надо стянуть панель вниз, чтобы она закрылась */
const SWIPE_CLOSE = 72;
/** Запас на случай, если событие конца анимации не пришло */
const CLOSE_TIMEOUT = 400;

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
 * График оценки отклонения в выдвижной панели поверх размытого экрана.
 * На компьютере панель выезжает сверху, на телефоне снизу. Закрывается касанием пустого места,
 * клавишей Esc, кнопкой или движением вниз.
 */
export function ChartSheet({
  open,
  onClose,
  sessions,
  selected,
  trendIcon,
  trendText,
}: {
  open: boolean;
  onClose: () => void;
  sessions: Session[];
  selected: string | null;
  trendIcon: string;
  trendText: string;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const chartRef = useRef<HTMLDivElement>(null);
  const drag = useRef<{ id: number; y: number; dy: number } | null>(null);
  const width = useWidth(chartRef, open);

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

  const chartWidth = Math.max(280, Math.min(width || 340, 760));
  const chartHeight = Math.round(Math.max(150, Math.min(chartWidth * 0.36, 260)));

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
        <span className="cs-note">пунктир: порог 0,5</span>
        <button type="button" className="hb" onClick={requestClose} aria-label="Закрыть график" title="Закрыть">
          <Icon name="x" />
        </button>
      </div>
      <div className="cs-chart">
        {/* Ширину меряем у блока без отступов: график рисуется точно в свой размер */}
        <div ref={chartRef}>
          {open && width ? <ScoreChart sessions={sessions} selected={selected} width={chartWidth} height={chartHeight} /> : null}
        </div>
      </div>
      <div className="cs-cap">
        <Icon name={trendIcon} size="s" />
        <span>{trendText}</span>
      </div>
      <div className="cs-leg">
        <span>
          <i className="cs-dot cs-dot-a" />
          отклонение
        </span>
        <span>
          <i className="cs-dot" />
          норма
        </span>
        <span>
          <Icon name="x" size="s" />
          сбой записи
        </span>
        <span>
          <i className="cs-bar" />
          в чате
        </span>
      </div>
    </dialog>
  );
}
