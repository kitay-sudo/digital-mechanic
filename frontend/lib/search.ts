'use client';

import { useSyncExternalStore } from 'react';

/**
 * Строка поиска по парку. Поле ввода на компьютере стоит в верхней строке приложения,
 * а список машин рисует экран «Парк», поэтому значение лежит в общем хранилище.
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
