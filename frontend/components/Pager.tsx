import type { Paged } from '@/lib/paging';
import { Icon } from './Icon';

/** Какие номера страниц показывать: первая, последняя и соседние с текущей, остальное — многоточие. */
function pageList(page: number, pages: number): (number | null)[] {
  if (pages <= 7) return Array.from({ length: pages }, (_, i) => i);
  const keep = new Set([0, pages - 1, page - 1, page, page + 1].filter((n) => n >= 0 && n < pages));
  if (page <= 2) [1, 2, 3].forEach((n) => keep.add(n));
  if (page >= pages - 3) [pages - 2, pages - 3, pages - 4].forEach((n) => keep.add(n));
  const sorted = [...keep].sort((a, b) => a - b);
  const out: (number | null)[] = [];
  sorted.forEach((n, i) => {
    if (i > 0 && n - sorted[i - 1] > 1) out.push(null);
    out.push(n);
  });
  return out;
}

/**
 * Перелистывание страниц таблицы. Страница экрана не прокручивается:
 * в таблице ровно столько строк, сколько помещается, остальное на следующих страницах.
 */
export function Pager<T>({ paged, label }: { paged: Paged<T>; label: string }) {
  const { page, pages, from, to, total, setPage } = paged;
  if (!total) return null;
  return (
    <nav className="pager" aria-label={`Страницы: ${label}`}>
      <span className="pg-info">
        <span className="m">
          {from}–{to}
        </span>{' '}
        из <span className="m">{total}</span>
      </span>
      {pages > 1 ? (
        <div className="pg-nav">
          <button type="button" className="hb" onClick={() => setPage(page - 1)} disabled={page === 0} aria-label="Предыдущая страница" title="Предыдущая страница">
            <Icon name="arrow-left" />
          </button>
          <span className="pg-nums only-d">
            {pageList(page, pages).map((n, i) =>
              n === null ? (
                <span className="pg-gap" key={`gap${i}`}>
                  …
                </span>
              ) : (
                <button
                  type="button"
                  key={n}
                  className={`pg-n${n === page ? ' on' : ''}`}
                  onClick={() => setPage(n)}
                  aria-label={`Страница ${n + 1}`}
                  aria-current={n === page ? 'page' : undefined}
                >
                  {n + 1}
                </button>
              ),
            )}
          </span>
          <span className="pg-cur only-m m">
            {page + 1} / {pages}
          </span>
          <button type="button" className="hb" onClick={() => setPage(page + 1)} disabled={page >= pages - 1} aria-label="Следующая страница" title="Следующая страница">
            <Icon name="arrow-right" />
          </button>
        </div>
      ) : null}
    </nav>
  );
}
