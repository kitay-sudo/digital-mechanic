'use client';

import { useSyncExternalStore } from 'react';

/**
 * Строка поиска по парку. Значение лежит вне экрана «Парк», чтобы поиск сохранялся,
 * когда механик открыл машину и вернулся к списку.
 */
let query = '';
const listeners = new Set<() => void>();

export function setFleetQuery(next: string): void {
  if (next === query) return;
  query = next;
  listeners.forEach((l) => l());
}

export function useFleetQuery(): string {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => query,
    () => '',
  );
}
