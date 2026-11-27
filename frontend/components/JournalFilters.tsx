'use client';

import { useEffect } from 'react';
import { TYPE_LABEL, activeFilters, type CaseType, type JournalFacets, type JournalFilters, type StatusFilter } from '@/lib/journal';
import { Icon } from './Icon';

const STATUS_OPTIONS: { code: StatusFilter; label: string }[] = [
  { code: 'all', label: 'Все' },
  { code: 'open', label: 'Требуют внимания' },
  { code: 'new', label: 'Новые' },
  { code: 'in_work', label: 'В работе' },
  { code: 'reviewed', label: 'Разобранные' },
];

function Chips<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: { code: T; label: string }[];
  onChange: (v: T) => void;
}) {
  return (
    <div className="rsn jchips" role="radiogroup" aria-label={label}>
      {options.map((o) => (
        <button key={o.code} type="button" role="radio" aria-checked={value === o.code} className={value === o.code ? 'on' : ''} onClick={() => onChange(o.code)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** Фильтры журнала: панель снизу по центру экрана. Применяются сразу, без кнопки «Показать». */
export function FilterSheet({
  filters,
  facets,
  leaving,
  onChange,
  onReset,
  onClose,
}: {
  filters: JournalFilters;
  facets: JournalFacets;
  leaving: boolean;
  onChange: (patch: Partial<JournalFilters>) => void;
  onReset: () => void;
  onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  // Выбранного механика или машины может уже не быть в журнале: в списке он всё равно остаётся
  const mechanics = filters.mechanic && !facets.mechanics.includes(filters.mechanic) ? [filters.mechanic, ...facets.mechanics] : facets.mechanics;
  const vehicles =
    filters.vehicle_id && !facets.vehicles.some((v) => v.vehicle_id === filters.vehicle_id)
      ? [{ vehicle_id: filters.vehicle_id, title: '' }, ...facets.vehicles]
      : facets.vehicles;
  const types: { code: CaseType | ''; label: string }[] = [
    { code: '', label: 'Все обращения' },
    ...(Object.keys(TYPE_LABEL) as CaseType[]).map((code) => ({ code, label: TYPE_LABEL[code] })),
  ];
  const count = activeFilters(filters) + (filters.status === 'open' ? 1 : 0);

  return (
    <>
      <button type="button" className={`sp-dim${leaving ? ' leaving' : ''}`} aria-label="Закрыть фильтры" onClick={onClose} />
      <aside className={`sp jsheet${leaving ? ' leaving' : ''}`} role="dialog" aria-label="Фильтры журнала">
        <div className="handle">
          <i />
        </div>
        <div className="sp-h">
          <Icon name="filter" />
          <span>Фильтры</span>
          <button type="button" className="hb" onClick={onClose} aria-label="Закрыть">
            <Icon name="x" />
          </button>
        </div>
        <div className="sp-b jf-b">
          <div className="sp-g">
            <div className="sp-l">Период</div>
            <div className="jdates">
              <label>
                <span>с</span>
                <input
                  type="date"
                  className="inp"
                  value={filters.from.slice(0, 10)}
                  max={filters.to.slice(0, 10) || undefined}
                  onChange={(e) => onChange({ from: e.target.value })}
                  aria-label="Начало периода"
                />
              </label>
              <label>
                <span>по</span>
                <input
                  type="date"
                  className="inp"
                  value={filters.to.slice(0, 10)}
                  min={filters.from.slice(0, 10) || undefined}
                  onChange={(e) => onChange({ to: e.target.value })}
                  aria-label="Конец периода"
                />
              </label>
            </div>
          </div>
          <div className="jf-two">
            <div className="sp-g">
              <div className="sp-l">Машина</div>
              <select className="inp" value={filters.vehicle_id} onChange={(e) => onChange({ vehicle_id: e.target.value })} aria-label="Машина">
                <option value="">Все машины</option>
                {vehicles.map((v) => (
                  <option key={v.vehicle_id} value={v.vehicle_id}>
                    {v.title && v.title !== v.vehicle_id ? `${v.vehicle_id}  ${v.title}` : v.vehicle_id}
                  </option>
                ))}
              </select>
            </div>
            <div className="sp-g">
              <div className="sp-l">Механик</div>
              <select className="inp" value={filters.mechanic} onChange={(e) => onChange({ mechanic: e.target.value })} aria-label="Механик">
                <option value="">Все механики</option>
                {mechanics.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div className="sp-g">
            <div className="sp-l">Тип случая</div>
            <Chips label="Тип случая" value={filters.type} options={types} onChange={(type) => onChange({ type })} />
          </div>
          <div className="sp-g">
            <div className="sp-l">Статус разбора</div>
            <Chips label="Статус разбора" value={filters.status} options={STATUS_OPTIONS} onChange={(status) => onChange({ status })} />
          </div>
        </div>
        <div className="jf-f">
          <button type="button" className="btn" onClick={onReset} disabled={!count && !filters.q}>
            <Icon name="x" />
            Сбросить
          </button>
          <button type="button" className="btn pri" onClick={onClose}>
            Готово
          </button>
        </div>
      </aside>
    </>
  );
}
