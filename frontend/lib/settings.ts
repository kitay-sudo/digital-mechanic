'use client';

import { useSyncExternalStore } from 'react';
import type { Profile } from './types';

/** Настройки механика. Хранятся в браузере, на сервер уходит только профиль (подача и фамилия). */
export interface Settings {
  size: 'normal' | 'large';
  level: string;
  consent: boolean;
  /** Кто сейчас работает: фамилия механика. Видна в чате и журнале, при смене меняется */
  mechanic: string;
}

const KEY = 'dm-settings';
const DEFAULTS: Settings = { size: 'normal', level: 'expert', consent: false, mechanic: '' };

let state: Settings = DEFAULTS;
let loaded = false;
const listeners = new Set<() => void>();

function load(): void {
  if (loaded || typeof window === 'undefined') return;
  loaded = true;
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) state = { ...DEFAULTS, ...(JSON.parse(raw) as Partial<Settings>) };
  } catch {
    /* хранилище недоступно: настройки действуют до перезагрузки */
  }
}

function getSnapshot(): Settings {
  load();
  return state;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function setSettings(patch: Partial<Settings>): void {
  state = { ...getSnapshot(), ...patch };
  try {
    localStorage.setItem(KEY, JSON.stringify(state));
  } catch {
    /* см. выше */
  }
  document.documentElement.dataset.size = state.size;
  listeners.forEach((l) => l());
}

export function useSettings(): Settings {
  return useSyncExternalStore(subscribe, getSnapshot, () => DEFAULTS);
}

export function profileOf(s: Settings): Profile {
  const name = s.mechanic.trim();
  return name ? { level: s.level, name } : { level: s.level };
}

/* Запасной список, если сервер его не прислал */
export const FALLBACK_LEVELS = [
  { code: 'expert', label: 'Опытный', hint: 'Коротко, только суть' },
  { code: 'novice', label: 'Новичок', hint: 'С пояснениями и простыми словами' },
];
