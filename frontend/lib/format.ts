import type { Priority, Quality, Status } from './types';

/** 0.76 → «0,76» */
export function num(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return value.toFixed(digits).replace('.', ',');
}

/** 61200 → «61 200» */
export function int(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—';
  return Math.round(value).toLocaleString('ru-RU').replace(/ /g, ' ');
}

const dtf = new Intl.DateTimeFormat('ru-RU', {
  timeZone: 'Europe/Moscow',
  day: '2-digit',
  month: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
});

/** ISO → «20.11 10:00» по Москве */
export function dateTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return dtf.format(d).replace(',', '');
}

/** ISO → «20.11» */
export function dateShort(iso: string | null | undefined): string {
  return dateTime(iso).split(' ')[0] ?? '—';
}

/** ISO → «10:00» */
export function timeShort(iso: string | null | undefined): string {
  return dateTime(iso).split(' ')[1] ?? '';
}

export function plural(n: number, one: string, few: string, many: string): string {
  const a = Math.abs(n) % 100;
  const b = a % 10;
  if (a > 10 && a < 20) return many;
  if (b === 1) return one;
  if (b >= 2 && b <= 4) return few;
  return many;
}

export const STATUS_LABEL: Record<Status, string> = {
  normal: 'Норма',
  anomaly: 'Отклонение',
  check_failed: 'Сбой записи',
};

export const STATUS_ICON: Record<Status, string> = {
  normal: 'circle-check',
  anomaly: 'alert-triangle',
  check_failed: 'microphone-off',
};

export const PRIORITY_LABEL: Record<Priority, string> = {
  high: 'высокий',
  medium: 'средний',
  low: 'низкий',
};

export const PRIORITY_ICON: Record<Priority, string> = {
  high: 'chevrons-up',
  medium: 'chevron-up',
  low: 'chevron-down',
};

export const QUALITY_LABEL: Record<Quality, string> = {
  good: 'хорошее',
  warning: 'с помехами',
  bad: 'плохое',
};

export function capitalize(text: string): string {
  return text ? text[0].toUpperCase() + text.slice(1) : text;
}

/** Значок машины по марке */
export function vehicleIcon(make: string | null | undefined): string {
  const m = (make || '').toLowerCase();
  if (m.includes('паз')) return 'bus';
  if (m.includes('уаз')) return 'car';
  return 'truck';
}
