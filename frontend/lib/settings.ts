'use client';

import { useSyncExternalStore } from 'react';
import type { Profile } from './types';

/** Настройки механика. Хранятся в браузере, на сервер уходит только профиль (язык и подача). */
export interface Settings {
  size: 'normal' | 'large';
  level: string;
  language: string;
  consent: boolean;
}

const KEY = 'dm-settings';
const DEFAULTS: Settings = { size: 'normal', level: 'expert', language: 'ru', consent: false };

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
  return { language: s.language, level: s.level };
}

/** Язык распознавания речи по языку ответов */
const SPEECH: Record<string, string> = { ru: 'ru-RU', uz: 'uz-UZ', tg: 'tg-TJ', hi: 'hi-IN' };
export const speechLang = (language: string): string => SPEECH[language] ?? 'ru-RU';

/* Запасные списки, если сервер их не прислал */
export const FALLBACK_LANGUAGES = [
  { code: 'ru', label: 'Русский' },
  { code: 'uz', label: 'Oʻzbekcha' },
  { code: 'tg', label: 'Тоҷикӣ' },
  { code: 'hi', label: 'हिन्दी' },
];
export const FALLBACK_LEVELS = [
  { code: 'expert', label: 'Опытный', hint: 'Коротко, только суть' },
  { code: 'novice', label: 'Новичок', hint: 'С пояснениями и простыми словами' },
];

/* ---------- Отметки выполненных шагов ---------- */

const STEPS_KEY = 'dm-steps';
type StepMap = Record<string, number[]>;
let steps: StepMap = {};
let stepsLoaded = false;
const stepListeners = new Set<() => void>();
const EMPTY: number[] = [];

function loadSteps(): void {
  if (stepsLoaded || typeof window === 'undefined') return;
  stepsLoaded = true;
  try {
    const raw = localStorage.getItem(STEPS_KEY);
    if (raw) steps = JSON.parse(raw) as StepMap;
  } catch {
    /* отметки действуют до перезагрузки */
  }
}

/** Какие шаги списка отмечены выполненными. key: «id сообщения:список». */
export function useDoneSteps(key: string): number[] {
  return useSyncExternalStore(
    (l) => {
      stepListeners.add(l);
      return () => stepListeners.delete(l);
    },
    () => {
      loadSteps();
      return steps[key] ?? EMPTY;
    },
    () => EMPTY,
  );
}

export function toggleStep(key: string, index: number): void {
  loadSteps();
  const cur = steps[key] ?? [];
  const next = cur.includes(index) ? cur.filter((i) => i !== index) : [...cur, index].sort((a, b) => a - b);
  steps = { ...steps, [key]: next };
  try {
    // Храним отметки только по последним спискам, чтобы хранилище не росло
    const keys = Object.keys(steps);
    if (keys.length > 200) for (const k of keys.slice(0, keys.length - 200)) delete steps[k];
    localStorage.setItem(STEPS_KEY, JSON.stringify(steps));
  } catch {
    /* см. выше */
  }
  stepListeners.forEach((l) => l());
}
