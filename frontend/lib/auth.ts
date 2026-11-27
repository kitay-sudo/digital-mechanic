'use client';

import { useSyncExternalStore } from 'react';
import { AUTH_EVENT, ApiError } from './api';
import { setSettings } from './settings';

export type Role = 'admin' | 'mechanic';
export type Level = 'expert' | 'novice';
export type FontSize = 'normal' | 'large';

/** Механик, который вошёл: его ФИО подписывает вопросы, размер шрифта и подача применяются после входа */
export interface MechanicSelf {
  id: number;
  full_name: string;
  level: Level;
  font_size: FontSize;
}

/** Кто вошёл. required=false — вход выключен на сервере (разработка), все экраны открыты */
export interface Me {
  required: boolean;
  role: Role | null;
  mechanic: MechanicSelf | null;
  /** Подсказка для показа стенда, например «Демо: Иванов, PIN 1111» */
  hint: string | null;
}

export interface MechanicName {
  id: number;
  full_name: string;
}

/** Механик в списке администратора */
export interface Mechanic extends MechanicSelf {
  age: number | null;
  active: boolean;
  created_at: string;
  updated_at: string;
}

export interface MechanicInput {
  full_name?: string;
  age?: number | null;
  level?: Level;
  font_size?: FontSize;
  pin?: string;
  active?: boolean;
}

export interface IntegrationItem {
  key: 'ml_url' | 'toir_url' | 'alert_webhook_url' | 'ml_token' | 'toir_token';
  label: string;
  /** Показанное значение: секреты скрыты */
  value: string | null;
  set: boolean;
  secret: boolean;
  /** db — задано администратором, env — из .env */
  source: 'db' | 'env';
}

export interface Integrations {
  items: IntegrationItem[];
  ticket_sink: string;
  api: { enabled: boolean; keys: number; docs_url: string };
  health?: { ml: boolean; toir: boolean };
  changed?: string[];
}

/** Ошибка входа: сколько попыток осталось и сколько ждать после пяти неверных PIN */
export class LoginError extends ApiError {
  attemptsLeft: number | null;
  retryAfter: number | null;
  constructor(message: string, status: number, attemptsLeft: number | null, retryAfter: number | null) {
    super(message, status);
    this.attemptsLeft = attemptsLeft;
    this.retryAfter = retryAfter;
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, { cache: 'no-store', ...init });
  } catch {
    throw new LoginError('Нет связи с сервером', 0, null, null);
  }
  let data: Record<string, unknown> = {};
  try {
    data = (await res.json()) as Record<string, unknown>;
  } catch {
    /* тело не JSON */
  }
  if (!res.ok) {
    const text = typeof data.detail === 'string' ? data.detail : `Ошибка сервера (${res.status})`;
    throw new LoginError(
      text,
      res.status,
      typeof data.attempts_left === 'number' ? data.attempts_left : null,
      typeof data.retry_after === 'number' ? data.retry_after : null,
    );
  }
  return data as T;
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { 'content-type': 'application/json' },
  body: JSON.stringify(body),
});

export const authApi = {
  me: () => call<Me>('/api/auth/me'),
  mechanics: () => call<{ items: MechanicName[]; hint: string | null }>('/api/auth/mechanics'),
  loginMechanic: (mechanicId: number, pin: string) =>
    call<{ role: Role; mechanic: MechanicSelf }>('/api/auth/mechanic', json('POST', { mechanic_id: mechanicId, pin })),
  loginAdmin: (login: string, password: string) => call<{ role: Role }>('/api/auth/admin', json('POST', { login, password })),
  logout: () => call<unknown>('/api/auth/logout', { method: 'POST' }),
  // Экраны администратора
  listMechanics: () => call<{ items: Mechanic[]; total: number }>('/api/admin/mechanics'),
  createMechanic: (body: MechanicInput) => call<Mechanic>('/api/admin/mechanics', json('POST', body)),
  updateMechanic: (id: number, body: MechanicInput) => call<Mechanic>(`/api/admin/mechanics/${id}`, json('PUT', body)),
  integrations: () => call<Integrations>('/api/admin/integrations'),
  saveIntegrations: (body: Partial<Record<IntegrationItem['key'], string>>) =>
    call<Integrations>('/api/admin/integrations', json('PUT', body)),
};

/* ---------- Кто вошёл: общее состояние для шапки, чата, настроек и экрана входа ---------- */

interface AuthState {
  /** null — ещё не узнали */
  me: Me | null;
  /** Механик сам попросил экран входа (при выключенном входе — «Войти» в чате) */
  wantLogin: boolean;
}

const OPEN: Me = { required: false, role: null, mechanic: null, hint: null };
let state: AuthState = { me: null, wantLogin: false };
const listeners = new Set<() => void>();

function set(patch: Partial<AuthState>): void {
  state = { ...state, ...patch };
  listeners.forEach((l) => l());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useAuth(): AuthState {
  return useSyncExternalStore(
    subscribe,
    () => state,
    () => state,
  );
}

/** Настройки механика применяются при входе: ФИО — автор вопросов и отметок, его шрифт и подача */
function applyMechanic(m: MechanicSelf): void {
  setSettings({ mechanic: m.full_name, level: m.level, size: m.font_size });
}

let loading: Promise<void> | null = null;

/** Перечитать, кто вошёл. Старый сервер без входа — всё открыто, как раньше */
export function loadMe(): Promise<void> {
  if (loading) return loading;
  loading = authApi
    .me()
    .then((me) => {
      const prev = state.me;
      if (me.mechanic && prev?.mechanic?.id !== me.mechanic.id) applyMechanic(me.mechanic);
      if (prev?.mechanic && !me.mechanic && me.required) setSettings({ mechanic: '' });
      set({ me });
    })
    .catch(() => {
      // Сервер без маршрутов входа (старая версия) или нет связи — экран не держим: запросы к серверу
      // сами покажут ошибку, а ответ 401 снова вызовет проверку входа
      if (!state.me) set({ me: OPEN });
    })
    .finally(() => {
      loading = null;
    });
  return loading;
}

let listening = false;

/** Сервер ответил 401: сессия кончилась — показать вход */
export function listenAuth(): void {
  if (listening || typeof window === 'undefined') return;
  listening = true;
  window.addEventListener(AUTH_EVENT, () => void loadMe());
}

export async function loginMechanic(id: number, pin: string): Promise<void> {
  const r = await authApi.loginMechanic(id, pin);
  applyMechanic(r.mechanic);
  set({ wantLogin: false, me: { ...(state.me ?? OPEN), role: 'mechanic', mechanic: r.mechanic } });
  void loadMe();
}

export async function loginAdmin(login: string, password: string): Promise<void> {
  await authApi.loginAdmin(login, password);
  // Вход механика на этом устройстве закончился: его ФИО больше не подписывает сообщения
  setSettings({ mechanic: '' });
  set({ wantLogin: false, me: { ...(state.me ?? OPEN), role: 'admin', mechanic: null } });
  void loadMe();
}

/** Выход: смена механика или конец работы администратора. Экран возвращается к списку «Кто работает» */
export async function logout(): Promise<void> {
  try {
    await authApi.logout();
  } catch {
    /* кука всё равно истечёт; экран входа покажем сразу */
  }
  setSettings({ mechanic: '' });
  set({ me: { ...(state.me ?? OPEN), role: null, mechanic: null }, wantLogin: true });
}

/** Показать экран входа механика, даже если вход на сервере выключен */
export function openLogin(): void {
  set({ wantLogin: true });
}

export function closeLogin(): void {
  set({ wantLogin: false });
}

/** Экраны только для администратора: журнал, механики, подключения */
export function isAdminPath(path: string): boolean {
  return path === '/log' || path.startsWith('/log/') || path.startsWith('/admin');
}

/** Видит ли пользователь разделы администратора. Вход выключен — видны всем */
export function canAdmin(me: Me | null): boolean {
  return Boolean(me && (!me.required || me.role === 'admin'));
}
