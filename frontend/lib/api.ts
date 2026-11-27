import type { AuditItem, Config, Draft, Fleet, ManualPage, Marks, Message, Profile, Report, StreamEvent, TurnState, VehicleDetail } from './types';

/** Событие страницы: число неразобранных случаев без ответа изменилось, шапка перечитывает его */
export const GAPS_EVENT = 'mechanic:gaps';

/** Событие страницы: сервер ответил «войдите» (сессия истекла или механику сменили PIN), экран входа перечитывает её */
export const AUTH_EVENT = 'mechanic:auth';

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

/** Поток оборвался на середине. Ход на сервере продолжается, к нему можно подключиться заново. */
export class StreamLostError extends ApiError {
  constructor() {
    super('Связь с сервером прервалась', 0);
  }
}

async function readError(res: Response): Promise<string> {
  try {
    const data = await res.json();
    if (typeof data?.detail === 'string') return data.detail;
  } catch {
    /* тело не JSON */
  }
  return `Ошибка сервера (${res.status})`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, { cache: 'no-store', ...init });
  } catch {
    throw new ApiError('Нет связи с сервером', 0);
  }
  if (res.status === 401) window.dispatchEvent(new Event(AUTH_EVENT));
  if (!res.ok) throw new ApiError(await readError(res), res.status);
  return (await res.json()) as T;
}

const json = (body: unknown): RequestInit => ({
  headers: { 'content-type': 'application/json' },
  body: JSON.stringify(body),
});

export const api = {
  config: () => request<Config>('/api/config'),
  fleet: () => request<Fleet>('/api/fleet'),
  vehicle: (id: string) => request<VehicleDetail>(`/api/vehicles/${encodeURIComponent(id)}`),
  conversation: (id: string) =>
    request<{ messages: Message[]; turn?: TurnState | null; marks?: Marks; reports?: Record<string, Report> }>(
      `/api/conversations/${encodeURIComponent(id)}`,
    ),
  /** Отметка шага «сделано» с фамилией механика: видна сменщику */
  mark: (vehicleId: string, body: { key: string; index: number; done: boolean; author: string | null }) =>
    request<{ marks: Marks }>(`/api/conversations/${encodeURIComponent(vehicleId)}/marks`, { method: 'PUT', ...json(body) }),
  /** Сообщение механика в поддержку об ответе агента: попадает в журнал администратору */
  report: (body: { message_id: string; reason: string; text: string; author: string | null }) =>
    request<{ report: Report }>('/api/reports', { method: 'POST', ...json(body) }),
  /** Ошибка хода показана механику: сервер перестаёт о ней напоминать */
  seenTurn: (id: string) =>
    request<unknown>(`/api/conversations/${encodeURIComponent(id)}/turn`, { method: 'DELETE' }),
  clearConversation: (id: string) =>
    request<unknown>(`/api/conversations/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  patchDraft: (id: string, patch: Partial<Pick<Draft, 'conclusion' | 'urgency'>>) =>
    request<Draft>(`/api/drafts/${encodeURIComponent(id)}`, { method: 'PATCH', ...json(patch) }),
  manualPage: (manualId: string, page: number) =>
    request<ManualPage>(`/api/manuals/${encodeURIComponent(manualId)}/pages/${page}`),
  audit: (limit = 100) => request<{ items: AuditItem[]; gaps_open?: number }>(`/api/audit?limit=${limit}`),
  /** Сколько случаев без ответа администратор ещё не разобрал */
  auditGaps: () => request<{ open: number }>('/api/audit/gaps'),
  reviewGap: (id: string, reviewed: boolean) =>
    request<{ id: string; reviewed_at: string | null }>(`/api/audit/${encodeURIComponent(id)}/review`, {
      method: 'POST',
      ...json({ reviewed }),
    }),
  /** Распознавание фразы механика на сервере. seconds — длина записи, для журнала стоимости */
  stt: (audio: Blob, seconds: number) =>
    request<{ text: string }>(`/api/stt?seconds=${Math.round(seconds * 10) / 10}`, {
      method: 'POST',
      headers: { 'content-type': audio.type || 'audio/webm' },
      body: audio,
    }),
};

/** Читает поток application/x-ndjson и отдаёт события по одному. */
async function stream(path: string, init: RequestInit, onEvent: (e: StreamEvent) => void, signal?: AbortSignal): Promise<void> {
  let res: Response;
  try {
    res = await fetch(path, { cache: 'no-store', signal, ...init });
  } catch {
    throw new ApiError('Нет связи с сервером', 0);
  }
  if (res.status === 401) window.dispatchEvent(new Event(AUTH_EVENT));
  if (!res.ok || !res.body) throw new ApiError(await readError(res), res.status);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  const flush = (line: string) => {
    const text = line.trim();
    if (!text) return;
    try {
      onEvent(JSON.parse(text) as StreamEvent);
    } catch {
      /* битая строка потока: пропускаем */
    }
  };
  for (;;) {
    let chunk: ReadableStreamReadResult<Uint8Array>;
    try {
      chunk = await reader.read();
    } catch {
      throw new StreamLostError();
    }
    const { done, value } = chunk;
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let nl = buffer.indexOf('\n');
    while (nl >= 0) {
      flush(buffer.slice(0, nl));
      buffer = buffer.slice(nl + 1);
      nl = buffer.indexOf('\n');
    }
  }
  flush(buffer + decoder.decode());
}

export const chatStream = (
  body: { vehicle_id: string; session_id: string | null; text: string; images?: string[]; profile: Profile },
  onEvent: (e: StreamEvent) => void,
  signal?: AbortSignal,
) => stream('/api/chat', { method: 'POST', ...json(body) }, onEvent, signal);

export const confirmDraftStream = (
  draftId: string,
  body: { warning_ack: boolean; profile: Profile },
  onEvent: (e: StreamEvent) => void,
  signal?: AbortSignal,
) => stream(`/api/drafts/${encodeURIComponent(draftId)}/confirm`, { method: 'POST', ...json(body) }, onEvent, signal);

/** Подключение к ходу, который уже идёт на сервере: события приходят с начала хода. */
export const turnStream = (vehicleId: string, onEvent: (e: StreamEvent) => void, signal?: AbortSignal) =>
  stream(`/api/conversations/${encodeURIComponent(vehicleId)}/turn`, {}, onEvent, signal);
