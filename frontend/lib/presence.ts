'use client';

import { useEffect, useState } from 'react';

/** Время плавного закрытия, мс. Совпадает с --mo в globals.css */
export const LEAVE_MS = 280;

/**
 * Плавное закрытие: держит панель на экране, пока она уезжает.
 * value — то, что панель показывает (null — закрыта). Пока value не null, shown равен ему.
 * Когда value стал null, shown ещё LEAVE_MS хранит прежнее значение, а leaving равен true:
 * панель остаётся в разметке с классом «leaving» и успевает проиграть анимацию ухода.
 * Признак ухода вычисляется в том же рендере, где value стал null, иначе панель успела бы исчезнуть.
 */
export function usePresence<T>(value: T | null, ms: number = LEAVE_MS): { shown: T | null; leaving: boolean } {
  const [kept, setKept] = useState<T | null>(value);

  useEffect(() => {
    if (value !== null) {
      setKept(value);
      return;
    }
    const timer = window.setTimeout(() => setKept(null), ms);
    return () => window.clearTimeout(timer);
  }, [value, ms]);

  return { shown: value ?? kept, leaving: value === null && kept !== null };
}
