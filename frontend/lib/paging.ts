'use client';

import { useCallback, useEffect, useLayoutEffect, useRef, useState, type RefObject } from 'react';

/**
 * Сколько строк таблицы помещается в отведённую область без прокрутки страницы.
 * Область (areaRef) занимает всё свободное место экрана. Внутри неё ищутся шапка таблицы
 * (data-head) и первая строка (data-row): по их высоте считается число строк на странице.
 * Высота строки, при которой страница заполняет область целиком, отдаётся стилям в --fit-row-h.
 * Пересчёт идёт при изменении размера окна и при смене deps (например, размера текста).
 */
export function useFitRows(deps: readonly unknown[] = []): { areaRef: RefObject<HTMLDivElement | null>; pageSize: number } {
  const areaRef = useRef<HTMLDivElement | null>(null);
  const [pageSize, setPageSize] = useState(8);

  const measure = useCallback(() => {
    const area = areaRef.current;
    if (!area) return;
    const row = area.querySelector<HTMLElement>('[data-row]');
    if (!row) return;
    const head = area.querySelector<HTMLElement>('[data-head]');
    const table = row.parentElement;
    // Строки растянуты под высоту области (см. ниже). На время замера растяжение снимается,
    // иначе вместо собственной высоты строки измерилась бы уже растянутая
    area.setAttribute('data-measuring', '');
    const rowH = row.getBoundingClientRect().height;
    const headH = head ? head.getBoundingClientRect().height : 0;
    const frame = table ? table.offsetHeight - table.clientHeight : 0;
    area.removeAttribute('data-measuring');
    if (rowH < 1) return;
    const room = area.clientHeight - headH - frame;
    const fit = Math.max(1, Math.floor(room / rowH));
    // Остаток высоты меньше одной строки делится между строками поровну:
    // полная страница заполняет таблицу ровно до перелистывания, без пустой полосы и второй линии.
    // Если строк мало и каждая выросла бы больше чем на четверть, строки остаются своей высоты
    const stretched = room / fit;
    area.style.setProperty('--fit-row-h', `${stretched >= rowH && stretched <= rowH * 1.25 ? stretched : rowH}px`);
    area.setAttribute('data-fit', '');
    setPageSize((cur) => (cur === fit ? cur : fit));
  }, []);

  useLayoutEffect(() => {
    measure();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [measure, ...deps]);

  useEffect(() => {
    const area = areaRef.current;
    if (!area || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(() => measure());
    observer.observe(area);
    return () => observer.disconnect();
  }, [measure]);

  return { areaRef, pageSize };
}

export interface Paged<T> {
  page: number;
  pages: number;
  /** Строки текущей страницы */
  rows: T[];
  /** Номера первой и последней строки на странице, с единицы */
  from: number;
  to: number;
  total: number;
  setPage: (page: number) => void;
}

/** Постраничный вывод списка. resetKey: при его смене (фильтр, поиск, вкладка) показ возвращается на первую страницу. */
export function usePaged<T>(items: T[], pageSize: number, resetKey: string = ''): Paged<T> {
  const [page, setPageRaw] = useState(0);
  const [seenKey, setSeenKey] = useState(resetKey);
  if (seenKey !== resetKey) {
    setSeenKey(resetKey);
    setPageRaw(0);
  }

  const size = Math.max(1, pageSize);
  const pages = Math.max(1, Math.ceil(items.length / size));
  const cur = Math.min(page, pages - 1);
  const start = cur * size;
  const rows = items.slice(start, start + size);
  const setPage = useCallback((next: number) => setPageRaw(Math.max(0, next)), []);

  return { page: cur, pages, rows, from: items.length ? start + 1 : 0, to: start + rows.length, total: items.length, setPage };
}
