import type { ManualTarget } from '@/lib/types';
import { Icon } from './Icon';

/** Ссылка на страницу руководства: «РК ЯМЗ-236 · стр. 112». */
export function RefChip({
  target,
  label,
  active,
  onOpen,
}: {
  target: ManualTarget;
  label: string;
  active?: boolean;
  onOpen: (t: ManualTarget) => void;
}) {
  return (
    <button
      type="button"
      className={`src${active ? ' on' : ''}`}
      onClick={() => onOpen(target)}
      aria-pressed={Boolean(active)}
      title={active ? 'Закрыть страницу руководства' : target.quote ? `Открыть страницу. Цитата: ${target.quote}` : 'Открыть страницу руководства'}
    >
      <Icon name="file-text" size="s" />
      {label} · стр. {target.page}
    </button>
  );
}

export function sameTarget(a: ManualTarget | null, b: ManualTarget): boolean {
  return Boolean(a && a.manual_id === b.manual_id && a.page === b.page && (a.quote ?? '') === (b.quote ?? ''));
}
