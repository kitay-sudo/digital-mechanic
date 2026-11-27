// Журнал обращений, разбор случаев, сводка смены и метрики пилота: типы и запросы (docs/api.md)

import { apiRequest } from './api';
import type { MessageKind, Report, Usage } from './types';

/** Статус разбора случая администратором */
export type CaseStatus = 'new' | 'in_work' | 'reviewed';
/** Тип случая: сообщение механика, нет в руководстве, нет руководств, ошибка диагностики, посторонний текст */
export type CaseType = 'report' | 'no_answer' | 'kb_missing' | 'ml_mismatch' | 'injection';
/** open — «Требуют внимания»: новые и в работе */
export type StatusFilter = 'all' | 'open' | 'new' | 'in_work' | 'reviewed';

export const STATUS_LABEL: Record<CaseStatus, string> = { new: 'Новый', in_work: 'В работе', reviewed: 'Разобрано' };
export const TYPE_LABEL: Record<CaseType, string> = {
  report: 'От механика',
  no_answer: 'Нет в руководстве',
  kb_missing: 'Нет руководств',
  ml_mismatch: 'Ошибка диагностики',
  injection: 'Посторонний текст',
};

export interface JournalGap {
  type: CaseType;
  label: string;
  title: string;
  status: CaseStatus | null;
  status_label: string | null;
  reviewed_at: string | null;
}

export interface JournalItem {
  /** m_12 — ответ агента, a_3 — вопрос механика администратору */
  id: string;
  source: 'answer' | 'admin';
  created_at: string;
  vehicle_id: string | null;
  vehicle_title: string;
  engine_model: string | null;
  session_id: string | null;
  question: string;
  /** Кто задал вопрос (у вопроса администратору — кто написал) */
  author: string | null;
  photos: number;
  kind: MessageKind | 'admin';
  answer: string;
  sources: { manual_id: string; short: string; pdf_page: number }[];
  tools: string[];
  ticket_id: string | null;
  usage: Partial<Usage> | null;
  /** Последнее сообщение механика об этом ответе */
  report: Report | null;
  reports_count: number;
  gap: JournalGap | null;
  status: CaseStatus | null;
  /** Сколько раз случай повторился: строка — группа повторов */
  repeats: number;
  /** В данных диагностики был посторонний текст */
  injection: boolean;
}

export interface JournalFacets {
  vehicles: { vehicle_id: string; title: string }[];
  mechanics: string[];
}

export interface JournalPage {
  items: JournalItem[];
  total: number;
  page: number;
  page_size: number;
  gaps_open: number;
  facets: JournalFacets;
}

export interface JournalFilters {
  /** Даты периода, YYYY-MM-DD или YYYY-MM-DDTHH:MM, конец включительно */
  from: string;
  to: string;
  vehicle_id: string;
  mechanic: string;
  type: CaseType | '';
  status: StatusFilter;
  q: string;
}

export const NO_FILTERS: JournalFilters = { from: '', to: '', vehicle_id: '', mechanic: '', type: '', status: 'all', q: '' };

export interface HistoryEntry {
  status: CaseStatus;
  status_label: string;
  comment: string;
  reviewer: string | null;
  at: string;
}

export interface CaseCard extends JournalItem {
  details: {
    summary: string;
    checks: string[];
    repair: string[];
    limitations: string[];
    recommendation_text: string | null;
    warnings: string[];
    anomaly_title: string | null;
  };
  reports: Report[];
  occurrences: { id: string; created_at: string; vehicle_id: string | null; author: string | null }[];
  history: HistoryEntry[];
  comment: string;
  reviewer: string | null;
  updated_at: string | null;
}

export interface ShiftMechanic {
  name: string | null;
  questions: number;
  marks: number;
  messages: number;
  first_at: string;
  last_at: string;
}

export interface ShiftMark {
  vehicle_id: string;
  vehicle_title: string;
  list: 'checks' | 'repair';
  index: number;
  step: string;
  author: string | null;
  at: string;
}

export interface ShiftTicket {
  ticket_id: string;
  vehicle_id: string;
  vehicle_title: string;
  session_id: string;
  created_at: string;
  urgency: 'low' | 'medium' | 'high' | null;
  anomaly_type: string | null;
  conclusion: string;
}

export interface ShiftSummary {
  from: string;
  to: string;
  totals: { questions: number; answers: number; vehicles: number; marks: number; tickets: number; open_cases: number; open_total: number };
  mechanics: ShiftMechanic[];
  marks: ShiftMark[];
  tickets: ShiftTicket[];
}

export interface PilotMetrics {
  from: string;
  to: string;
  verdicts: number;
  /** От первого вердикта по проверке до создания заявки */
  verdict_to_ticket: { count: number; avg_min: number | null; median_min: number | null };
  /** Честные отказы: ответы «в руководстве нет» среди ответов */
  refusals: { answers: number; not_found: number; share: number | null };
  /** Вердикты с предупреждением «Повтор после ремонта» */
  repeat_after_repair: number;
  response: { count: number; avg_ms: number | null };
  cost: { total_rub: number; per_answer_rub: number | null; speech_rub: number };
}

function query(params: Record<string, string | number | null | undefined>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== null && v !== undefined && v !== '') q.set(k, String(v));
  }
  const s = q.toString();
  return s ? `?${s}` : '';
}

const post = (body: unknown): RequestInit => ({
  method: 'POST',
  headers: { 'content-type': 'application/json' },
  body: JSON.stringify(body),
});

function filterParams(f: JournalFilters) {
  return { from: f.from, to: f.to, vehicle_id: f.vehicle_id, mechanic: f.mechanic, type: f.type, status: f.status, q: f.q.trim() };
}

export const journalApi = {
  page: (f: JournalFilters, page: number, pageSize: number) =>
    apiRequest<JournalPage>(`/api/audit${query({ ...filterParams(f), page, page_size: pageSize })}`),
  card: (id: string) => apiRequest<CaseCard>(`/api/audit/${encodeURIComponent(id)}`),
  /** Статус нескольких строк сразу: отмечается вся группа повторов каждой строки */
  setStatus: (body: { ids: string[]; status: CaseStatus; comment?: string | null; reviewer?: string | null }) =>
    apiRequest<{ updated: number; at: string; gaps_open: number }>('/api/audit/status', post(body)),
  shift: (from: string, to: string) => apiRequest<ShiftSummary>(`/api/shift-summary${query({ from, to })}`),
  metrics: (from: string, to: string) => apiRequest<PilotMetrics>(`/api/metrics${query({ from, to })}`),
};

/** Вопрос механика администратору напрямую, не к ответу агента: случай «От механика» в журнале */
export const adminMessage = (body: { vehicle_id?: string | null; text: string; author?: string | null }) =>
  apiRequest<{ id: string; created_at: string }>('/api/admin-messages', post(body));

/** Выгрузка журнала в xlsx с теми же фильтрами периода, машины и механика */
export function exportUrl(f: JournalFilters): string {
  return `/api/usage/export.xlsx${query({ from: f.from, to: f.to, vehicle_id: f.vehicle_id, mechanic: f.mechanic })}`;
}

/** Фильтры журнала из адреса страницы: на журнал можно сослаться со сводки смены */
export function filtersFromUrl(search: string): JournalFilters {
  const p = new URLSearchParams(search);
  const status = p.get('status');
  const type = p.get('type');
  return {
    from: p.get('from') ?? '',
    to: p.get('to') ?? '',
    vehicle_id: p.get('vehicle_id') ?? '',
    mechanic: p.get('mechanic') ?? '',
    type: type && type in TYPE_LABEL ? (type as CaseType) : '',
    status: status === 'open' || status === 'new' || status === 'in_work' || status === 'reviewed' ? status : 'all',
    q: p.get('q') ?? '',
  };
}

export function filtersToUrl(f: JournalFilters): string {
  return query({ from: f.from, to: f.to, vehicle_id: f.vehicle_id, mechanic: f.mechanic, type: f.type, status: f.status === 'all' ? '' : f.status, q: f.q });
}

/** Сколько фильтров выбрано в панели «Фильтры» (поиск и «Требуют внимания» стоят отдельно) */
export function activeFilters(f: JournalFilters): number {
  return [f.from || f.to, f.vehicle_id, f.mechanic, f.type, f.status !== 'all' && f.status !== 'open' ? f.status : ''].filter(Boolean).length;
}
