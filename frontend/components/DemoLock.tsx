'use client';

import { useEffect, useState } from 'react';
import { DEMO_LOCK_EVENT } from '@/lib/auth';
import { usePresence } from '@/lib/presence';
import { Icon } from './Icon';

/**
 * Демо-стенд: эксперт попробовал то, что сломало бы стенд другим (удалить руководство заказчика,
 * сменить модель, PIN демо-механика). Сервер отказал, а здесь своя панель снизу объясняет почему.
 */
export function DemoLock() {
  const [text, setText] = useState<string | null>(null);
  const { shown, leaving } = usePresence(text);

  useEffect(() => {
    const onLock = (e: Event) => setText((e as CustomEvent<string>).detail || 'На демо-стенде это изменение запрещено системой.');
    window.addEventListener(DEMO_LOCK_EVENT, onLock);
    return () => window.removeEventListener(DEMO_LOCK_EVENT, onLock);
  }, []);

  useEffect(() => {
    if (text === null) return;
    // Esc закрывает только эту панель: панель админки под ней остаётся открытой
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      e.stopPropagation();
      setText(null);
    };
    window.addEventListener('keydown', onKey, true);
    return () => window.removeEventListener('keydown', onKey, true);
  }, [text]);

  if (shown === null) return null;
  const close = () => setText(null);

  return (
    <>
      <button type="button" className={`veil dl-veil${leaving ? ' leaving' : ''}`} aria-label="Закрыть" onClick={close} />
      <div className={`pop dl${leaving ? ' leaving' : ''}`} role="alertdialog" aria-labelledby="dl-t" aria-describedby="dl-s">
        <div className="dl-h">
          <Icon name="lock" size="l" />
          <div className="pop-t" id="dl-t">
            Изменение на демо-стенде запрещено системой
          </div>
        </div>
        <div className="pop-s" id="dl-s">
          {shown}
        </div>
        <div className="pop-f one">
          <button type="button" className="btn pri" onClick={close} autoFocus>
            Понятно
          </button>
        </div>
      </div>
    </>
  );
}
