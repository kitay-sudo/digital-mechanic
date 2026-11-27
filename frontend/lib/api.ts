import type { AuditItem, Config, Draft, Fleet, ManualPage, Message, Profile, StreamEvent, TurnState, VehicleDetail } from './types';

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
    request<{ messages: Message[]; turn?: TurnState | null }>(`/api/conversations/${encodeURIComponent(id)}`),
  /** Ошибка хода показана механику: сервер перестаёт о ней напоминать */
  seenTurn: (id: string) =>
    request<unknown>(`/api/conversations/${encodeURIComponent(id)}/turn`, { method: 'DELETE' }),
  clearConversation: (id: string) =>
    request<unknown>(`/api/conversations/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  patchDraft: (id: string, patch: Partial<Pick<Draft, 'conclusion' | 'urgency'>>) =>
    request<Draft>(`/api/drafts/${encodeURIComponent(id)}`, { method: 'PATCH', ...json(patch) }),
  manualPage: (manualId: string, page: number) =>
    request<ManualPage>(`/api/manuals/${encodeURIComponent(manualId)}/pages/${page}`),
  audit: (limit = 100) => request<{ items: AuditItem[] }>(`/api/audit?limit=${limit}`),
};

/** Читает поток application/x-ndjson и отдаёт события по одному. */
async function stream(path: string, init: RequestInit, onEvent: (e: StreamEvent) => void, signal?: AbortSignal): Promise<void> {
  let res: Response;
  try {
    res = await fetch(path, { cache: 'no-store', signal, ...init });
  } catch {
    throw new ApiError('Нет связи с сервером', 0);
  }
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
  body: { vehicle_id: string; session_id: string | null; text: string; profile: Profile },
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
