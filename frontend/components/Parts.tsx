import type { ReactNode } from 'react';

/**
 * Несколько значений в одну строку, разделённых отступом — без точек-разделителей.
 * Пустые значения пропускаются. nowrap — для строк, которые обрезаются по ширине.
 */
export function Parts({ items, className, nowrap = false }: { items: ReactNode[]; className?: string; nowrap?: boolean }) {
  const shown = items.filter((x) => x !== null && x !== undefined && x !== false && x !== '');
  return (
    <span className={`parts${nowrap ? ' nowrap' : ''}${className ? ` ${className}` : ''}`}>
      {shown.map((x, i) => (
        <span key={i}>{x}</span>
      ))}
    </span>
  );
}
