import type { Config, Draft, Fleet, ManualPage, Message, StreamEvent, VehicleDetail } from './types';

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
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
    request<{ messages: Message[] }>(`/api/conversations/${encodeURIComponent(id)}`),
  clearConversation: (id: string) =>
    request<unknown>(`/api/conversations/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  patchDraft: (id: string, patch: Partial<Pick<Draft, 'conclusion' | 'urgency'>>) =>
    request<Draft>(`/api/drafts/${encodeURIComponent(id)}`, { method: 'PATCH', ...json(patch) }),
  manualPage: (manualId: string, page: number) =>
    request<ManualPage>(`/api/manuals/${encodeURIComponent(manualId)}/pages/${page}`),
};

/** Читает поток application/x-ndjson и отдаёт события по одному. */
async function stream(path: string, body: unknown, onEvent: (e: StreamEvent) => void): Promise<void> {
  let res: Response;
  try {
    res = await fetch(path, { method: 'POST', cache: 'no-store', ...json(body) });
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
    const { done, value } = await reader.read();
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
  body: { vehicle_id: string; session_id: string | null; text: string },
  onEvent: (e: StreamEvent) => void,
) => stream('/api/chat', body, onEvent);

export const confirmDraftStream = (
  draftId: string,
  body: { warning_ack: boolean },
  onEvent: (e: StreamEvent) => void,
) => stream(`/api/drafts/${encodeURIComponent(draftId)}/confirm`, body, onEvent);
