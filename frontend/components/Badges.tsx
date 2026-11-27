import type { Priority, Status } from '@/lib/types';
import { PRIORITY_ICON, PRIORITY_LABEL, STATUS_ICON, STATUS_LABEL, capitalize } from '@/lib/format';
import { Icon } from './Icon';

const STATUS_CLASS: Record<Status, string> = { anomaly: 'c-dev', check_failed: 'c-fail', normal: 'c-norm' };
const PRIORITY_CLASS: Record<Priority, string> = { high: 'c-h', medium: 'c-m', low: 'c-l' };

/** Статус проверки: значок, слово и цвет. */
export function StatusBadge({ status, code, mismatch }: { status: Status | null; code?: string | null; mismatch?: boolean }) {
  // Проверка пришла от «НейроДВС» веб-хуком, результата ещё нет: агент запросит его у ML-сервиса
  if (!status) {
    return (
      <span className="sev c-norm">
        <Icon name="clock" />
        Ждёт результата
      </span>
    );
  }
  // Результат модели не подходит двигателю машины: это ошибка данных, а не отклонение
  if (mismatch) {
    return (
      <span className="sev c-fail">
        <Icon name="alert-triangle" />
        Ошибка данных
        {code ? <span className="code">{code}</span> : null}
      </span>
    );
  }
  return (
    <span className={`sev ${STATUS_CLASS[status]}`}>
      <Icon name={STATUS_ICON[status]} />
      {STATUS_LABEL[status]}
      {code ? <span className="code">{code}</span> : null}
    </span>
  );
}

/** Приоритет: значок, слово и цвет. long добавляет слово «Приоритет». */
export function PriorityBadge({ priority, long }: { priority: Priority; long?: boolean }) {
  return (
    <span className={`sev ${PRIORITY_CLASS[priority]}`}>
      <Icon name={PRIORITY_ICON[priority]} />
      {long ? `Приоритет ${PRIORITY_LABEL[priority]}` : capitalize(PRIORITY_LABEL[priority])}
    </span>
  );
}
