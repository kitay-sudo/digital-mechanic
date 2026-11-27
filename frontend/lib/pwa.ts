'use client';

import { useSyncExternalStore } from 'react';

/** Событие браузера с предложением установки. В lib.dom его нет, описываем нужное сами. */
interface InstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>;
}

export interface PwaState {
  /** Браузер готов показать своё окно установки (Chrome, Edge на Android и компьютере) */
  canInstall: boolean;
  /** Открыто как установленное приложение */
  installed: boolean;
  /** Страница открыта по https или с localhost: без этого установка недоступна */
  secure: boolean;
  /** iPhone и iPad: установка только через «Поделиться» в Safari */
  ios: boolean;
  /** Система открыта внутри приложения для Android (APK) */
  shell: boolean;
}

/** Что приложение для Android даёт странице: см. android/src/.../MainActivity.java, класс Bridge */
interface AppBridge {
  version: () => string;
  server: () => string;
  changeServer: () => void;
}

function bridge(): AppBridge | null {
  if (typeof window === 'undefined') return null;
  return (window as Window & { DigitalMechanicApp?: AppBridge }).DigitalMechanicApp ?? null;
}

/** Страница открыта внутри приложения для Android: разрешения там выдаются в настройках телефона, а не браузера */
export function inAppShell(): boolean {
  return bridge() !== null;
}

const SERVER: PwaState = { canInstall: false, installed: false, secure: true, ios: false, shell: false };

let state: PwaState = SERVER;
let deferred: InstallPromptEvent | null = null;
let started = false;
const listeners = new Set<() => void>();

function set(patch: Partial<PwaState>): void {
  state = { ...state, ...patch };
  listeners.forEach((l) => l());
}

/** Запускается один раз при загрузке: регистрирует сервис-воркер и ловит предложение установки. */
export function startPwa(): void {
  if (started || typeof window === 'undefined') return;
  started = true;

  const standalone =
    window.matchMedia('(display-mode: standalone)').matches || (navigator as Navigator & { standalone?: boolean }).standalone === true;
  const ios = /iphone|ipad|ipod/i.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  set({ installed: standalone, secure: window.isSecureContext, ios, shell: bridge() !== null });

  window.addEventListener('beforeinstallprompt', (event) => {
    // Своё окно браузера придержим: установка запускается кнопкой в настройках
    event.preventDefault();
    deferred = event as InstallPromptEvent;
    set({ canInstall: true });
  });
  window.addEventListener('appinstalled', () => {
    deferred = null;
    set({ canInstall: false, installed: true });
  });

  // В режиме разработки сервис-воркер не нужен: он держал бы в запасе старые файлы сборки
  if (process.env.NODE_ENV === 'production' && 'serviceWorker' in navigator && window.isSecureContext) {
    const register = () => {
      navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(() => undefined);
    };
    // К моменту запуска страница обычно уже загружена, и событие load второй раз не придёт
    if (document.readyState === 'complete') register();
    else window.addEventListener('load', register, { once: true });
  }
}

/** Показать окно установки браузера. Возвращает true, если пользователь согласился. */
export async function installApp(): Promise<boolean> {
  const event = deferred;
  if (!event) return false;
  await event.prompt();
  const choice = await event.userChoice;
  deferred = null;
  set({ canInstall: false });
  return choice.outcome === 'accepted';
}

/** В приложении для Android: открыть экран с адресом сервера. */
export function changeAppServer(): void {
  bridge()?.changeServer();
}

/** Версия приложения для Android, пустая строка в обычном браузере. */
export function appVersion(): string {
  try {
    return bridge()?.version() ?? '';
  } catch {
    return '';
  }
}

export function usePwa(): PwaState {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => state,
    () => SERVER,
  );
}
