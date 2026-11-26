'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import type { ManualPage, ManualTarget } from '@/lib/types';
import { Icon } from './Icon';

/** Страница руководства: картинка страницы PDF с подсветкой цитаты. */
export function ManualPanel({
  target,
  leaving = false,
  onNavigate,
  onClose,
}: {
  target: ManualTarget;
  /** Панель закрывается: проигрывается анимация ухода */
  leaving?: boolean;
  onNavigate: (t: ManualTarget) => void;
  onClose: () => void;
}) {
  const [page, setPage] = useState<ManualPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [imgState, setImgState] = useState<'loading' | 'ok' | 'error'>('loading');

  useEffect(() => {
    let alive = true;
    setError(null);
    setImgState('loading');
    api
      .manualPage(target.manual_id, target.page)
      .then((p) => {
        if (alive) setPage(p);
      })
      .catch((e: Error) => {
        if (alive) setError(e.message);
      });
    return () => {
      alive = false;
    };
  }, [target.manual_id, target.page]);

  const current = page && page.manual_id === target.manual_id && page.page === target.page ? page : null;
  const pageCount = current?.page_count ?? page?.page_count ?? null;
  const base = current?.image_url ?? `/api/manuals/${encodeURIComponent(target.manual_id)}/pages/${target.page}/image`;
  const src = target.quote ? `${base}?q=${encodeURIComponent(target.quote)}` : base;
  const go = (n: number) => onNavigate({ manual_id: target.manual_id, page: n, short: target.short });

  return (
    <aside className={`col manual open${leaving ? ' leaving' : ''}`}>
      <div className="handle">
        <i />
      </div>
      <div className="hdr">
        <Icon name="book-2" size="l" className="only-d" />
        <div className="grow">
          <div className="h1" style={{ fontSize: 18, lineHeight: '24px' }}>
            {current?.short ?? page?.short ?? target.short ?? 'Руководство'}
          </div>
          <div className="sub" title={current?.title ?? page?.title ?? ''}>
            {current?.designation ?? page?.designation ?? ''}
          </div>
        </div>
        <div className="rt">
          <span className="st m">
            стр. PDF {target.page}
            {pageCount ? ` / ${pageCount}` : ''}
          </span>
          <button type="button" className="hb" onClick={onClose} aria-label="Закрыть страницу">
            <Icon name="x" />
          </button>
        </div>
      </div>

      <div className="viewer">
        {error ? (
          <div className="alert">
            <Icon name="file-off" />
            <div>{error}</div>
          </div>
        ) : (
          <>
            {imgState === 'loading' ? (
              <div className="st" style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 8 }}>
                <Icon name="loader-2" size="s" className="spin" />
                Загружаю страницу…
              </div>
            ) : null}
            {imgState === 'error' ? (
              <div className="alert a-info">
                <Icon name="photo-off" />
                <div>Картинка страницы недоступна.{current?.text ? ' Ниже текст страницы.' : ''}</div>
              </div>
            ) : (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                key={src}
                // Пока картинка грузится, у неё нет высоты: рамка и фон дали бы тёмную полосу
                className={imgState === 'loading' ? 'pending' : undefined}
                src={src}
                alt={`Страница ${target.page} руководства`}
                onLoad={() => setImgState('ok')}
                onError={() => setImgState('error')}
              />
            )}
            {target.quote ? (
              <div className="quote">
                <span className="ql">Цитата со страницы, на которую ссылается агент</span>
                {target.quote}
              </div>
            ) : null}
            {imgState === 'error' && current?.text ? (
              <div className="quote" style={{ whiteSpace: 'pre-wrap', borderLeftColor: 'var(--line2)' }}>
                {current.text}
              </div>
            ) : null}
          </>
        )}
      </div>

      <div className="ftr">
        <button type="button" className="btn" onClick={() => go(target.page - 1)} disabled={target.page <= 1}>
          <Icon name="arrow-left" />
          стр. {Math.max(1, target.page - 1)}
        </button>
        <span className="st" style={{ flex: 1, textAlign: 'center' }}>
          <span className="only-d">{target.quote ? 'источник ответа' : 'просмотр'}</span>
        </span>
        <button type="button" className="btn" onClick={() => go(target.page + 1)} disabled={pageCount !== null && target.page >= pageCount}>
          стр. {target.page + 1}
          <Icon name="arrow-right" />
        </button>
      </div>
    </aside>
  );
}
