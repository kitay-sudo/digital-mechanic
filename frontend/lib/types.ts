// Типы по контракту docs/api.md

export type Status = 'normal' | 'anomaly' | 'check_failed';
export type Quality = 'good' | 'warning' | 'bad';
export type Priority = 'low' | 'medium' | 'high';
export type FleetStatus = 'ok' | 'attention' | 'quarantine';

export interface Config {
  llm: { provider: string; model: string; mock: boolean };
  /** Состояние базы знаний: каких руководств нет в индексе. У старого сервера поля нет */
  kb?: { ready: boolean; missing: string[]; pages: number };
  thresholds: { confidence_min: number };
  priority_actions: Record<Priority, string>;
  /** Уровни подачи: могут отсутствовать у старого сервера */
  levels?: { code: string; label: string; hint: string }[];
  /** Где распознаётся голос: server — запись уходит на сервер, иначе распознаёт браузер */
  stt?: { server: boolean; model: string | null };
}

/** Фото узла, приложенное механиком */
export interface Photo {
  id: string;
  url: string;
}

/** Случай для администратора: в руководстве нет ответа, не загружены руководства, ошибка модели диагностики */
export interface Gap {
  type: 'report' | 'no_answer' | 'kb_missing' | 'ml_mismatch';
  /** Короткая подпись для строки журнала */
  label: string;
  /** Полная формулировка: подсказка при наведении и текст уведомления */
  title?: string;
  reviewed_at: string | null;
}

/** Профиль механика, уходит с каждым сообщением в чат: уровень подачи и кто работает (смены) */
export interface Profile {
  level: string;
  name?: string;
}

/** Отметка «сделано» у шага: кто отметил и когда. Видна всем механикам, сменщик видит, на чём остановились */
export interface Mark {
  author: string | null;
  at: string;
}

/** Отметки по спискам шагов: ключ «id сообщения:checks» или «:repair», внутри номер шага */
export type Marks = Record<string, Record<string, Mark>>;

/** Сообщение механика в поддержку об ответе агента */
export interface Report {
  reason: string;
  text: string;
  author: string | null;
  created_at: string;
}

export interface AuditItem {
  id: string;
  created_at: string;
  vehicle_id: string;
  vehicle_title: string;
  session_id: string | null;
  question: string;
  kind: MessageKind;
  answer: string;
  sources: { manual_id: string; short: string; pdf_page: number }[];
  tools: string[];
  ticket_id: string | null;
  usage: Partial<Usage> | null;
  gap?: Gap | null;
  /** Кто из механиков задал вопрос */
  author?: string | null;
  /** Сколько фото было в вопросе */
  photos?: number;
  report?: Report | null;
}

export interface SessionBrief {
  session_id: string;
  checked_at: string;
  status: Status;
  anomaly_type: string | null;
  anomaly_title: string | null;
  anomaly_score: number | null;
  confidence: number | null;
  signal_quality: Quality;
}

export interface Session extends SessionBrief {
  description: string;
  ticket_id: string | null;
}

export interface TicketBrief {
  ticket_id: string;
  session_id: string;
  created_at: string;
}

export interface Ticket extends TicketBrief {
  vehicle_id: string;
  anomaly_type: string;
  conclusion: string;
  urgency: Priority;
  operations: string[];
  spare_parts: string[];
  references: { manual: string; pdf_page: number }[];
}

export interface VehicleBrief {
  vehicle_id: string;
  garage_no: string;
  make: string;
  model: string | null;
  title: string;
  vehicle_type: string;
  engine_model: string;
  fuel: string;
  fleet_status: FleetStatus;
  needs_recheck: boolean;
  priority: Priority | null;
  last_session: SessionBrief | null;
  sessions_count: number;
  tickets: TicketBrief[];
}

export interface Manual {
  manual_id: string;
  designation: string;
  title: string;
  short: string;
  pages: number;
}

export interface Trend {
  direction: 'rising' | 'falling' | 'stable' | 'none';
  text: string;
}

export interface VehicleDetail extends Omit<VehicleBrief, 'tickets'> {
  sessions: Session[];
  manuals: Manual[];
  trend: Trend;
  tickets: Ticket[];
}

export interface Fleet {
  summary: { total: number; ok: number; attention: number; quarantine: number; recheck: number };
  vehicles: VehicleBrief[];
}

export interface Ref {
  manual_id: string;
  designation: string;
  short: string;
  pdf_page: number;
  quote: string;
}

export interface AnswerItem {
  text: string;
  refs: Ref[];
  /** Шаг повторяет формулировку, по которой документы расходятся */
  disputed?: boolean;
}
export interface ConflictStatement {
  /** Пересказ одной фразой, может быть пустым: тогда показывается только цитата */
  text: string;
  ref: Ref;
}
/** Расхождение между страницами или документами по одному вопросу */
export interface Conflict {
  topic: string;
  statements: ConflictStatement[];
  recommendation: string;
  /** Расхождение подтверждено заказчиком и взято из реестра, а не найдено моделью */
  confirmed: boolean;
  resolution: string;
  resolution_source: string;
}

export interface Answer {
  summary: string;
  observations: string[];
  hypotheses: string[];
  checks: AnswerItem[];
  repair: AnswerItem[];
  limitations: string[];
  /** В старых сообщениях поля нет */
  conflicts?: Conflict[];
  not_found: boolean;
  recommendation_text: string | null;
}

export interface Assessment {
  outcome: Status;
  priority: Priority | null;
  priority_label: string | null;
  priority_action: string | null;
  basis: string[];
  flags: { check_failed: boolean; quality_warning: boolean; low_confidence: boolean; engine_mismatch: boolean };
  warnings: string[];
  ticket_allowed: boolean;
  ticket_block_reason: string | null;
  confidence_min: number;
}

export interface Diagnosis extends SessionBrief {
  vehicle_id: string;
  description: string;
  model_version: string;
}

export interface Draft {
  draft_id: string;
  vehicle_id: string;
  session_id: string;
  status: 'draft' | 'sent' | 'cancelled';
  anomaly_type: string;
  anomaly_title: string;
  conclusion: string;
  urgency: Priority;
  urgency_basis: string[];
  operations: AnswerItem[];
  spare_parts: AnswerItem[];
  references: { manual: string; manual_id: string; pdf_page: number }[];
  requires_warning_ack: boolean;
  warnings: string[];
  ticket_id: string | null;
}

export interface Step {
  id: string;
  tool: string;
  title: string;
  status: 'running' | 'done' | 'error';
  detail?: string | null;
}

export interface Usage {
  input_tokens: number;
  output_tokens: number;
  cost_rub: number;
  duration_ms: number;
  llm_calls: number;
  model: string;
  mock: boolean;
}

export type MessageKind = 'verdict' | 'answer' | 'ticket_draft' | 'ticket_created' | 'notice';

export interface Message {
  id: string;
  role: 'user' | 'assistant';
  created_at: string;
  session_id: string | null;
  text: string;
  /** Фото в сообщении механика */
  images?: Photo[];
  /** Кто из механиков написал сообщение */
  author?: string;
  kind?: MessageKind;
  diagnosis?: Diagnosis | null;
  assessment?: Assessment | null;
  answer?: Answer | null;
  draft?: Draft | null;
  ticket?: Ticket | null;
  steps?: Step[];
  usage?: Usage | null;
  /** Локальная ошибка, не с сервера */
  localError?: boolean;
}

/** Ход агента на сервере: ещё идёт или оборвался, а ошибку механик не видел */
export type TurnState = 'running' | 'failed';

export type StreamEvent =
  | { type: 'user'; message: Message }
  | ({ type: 'step' } & Step)
  | { type: 'message'; message: Message }
  | { type: 'error'; text: string }
  | { type: 'done'; usage?: Usage };

export interface ManualPage {
  manual_id: string;
  designation: string;
  title: string;
  short: string;
  engine: string;
  page: number;
  page_count: number;
  image_url: string;
  text: string;
}

/** Что открыть в панели руководства */
export interface ManualTarget {
  manual_id: string;
  page: number;
  quote?: string;
  short?: string;
}
