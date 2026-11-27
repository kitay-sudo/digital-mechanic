'use client';

import Link from 'next/link';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { LoginError, authApi, closeLogin, loginMechanic, type MechanicName } from '@/lib/auth';
import { useFitRows, usePaged } from '@/lib/paging';
import { useSettings } from '@/lib/settings';
import { Icon } from './Icon';
import { Blueprint } from './Blueprint';
import { Pager } from './Pager';
import { ErrorState, Loading } from './States';

/** Поиск появляется, когда механиков больше, чем помещается в один взгляд */
const SEARCH_FROM = 8;
const PIN_LENGTH = 4;

/**
 * Вход механика в одно касание: нажать свою фамилию, набрать PIN крупными кнопками.
 * Подходит для планшета в цеху и телефона: одним пальцем, без клавиатуры и меню.
 */
export function LoginMechanic({ hint, canClose = false }: { hint: string | null; canClose?: boolean }) {
  const [items, setItems] = useState<MechanicName[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [picked, setPicked] = useState<MechanicName | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(() => {
    setError(null);
    authApi
      .mechanics()
      .then((r) => setItems(r.items))
      .catch((e: Error) => setError(e.message));
  }, []);

  useEffect(load, [load]);

  const back = useCallback(
    (text: string | null = null) => {
      setPicked(null);
      setNotice(text);
      if (text) load();
    },
    [load],
  );

  return (
    <div className="body fit lg">
      {/* Чертёж двигателя тонкими линиями — фоном, под списком и PIN.
          Слой-обёртка обрезает всё, что выходит за экран: из-за чертежа не бывает прокрутки */}
      <div className="lg-bg">
        <Blueprint className="lg-art" grid />
      </div>
      {picked ? (
        <PinPad who={picked} onBack={back} />
      ) : error ? (
        <ErrorState text={error} onRetry={load} />
      ) : !items ? (
        <Loading text="Загружаю список механиков…" />
      ) : (
        <WhoList
          items={items}
          notice={notice}
          hint={hint}
          canClose={canClose}
          onPick={(m) => {
            setNotice(null);
            setPicked(m);
          }}
        />
      )}
    </div>
  );
}

function WhoList({
  items,
  notice,
  hint,
  canClose,
  onPick,
}: {
  items: MechanicName[];
  notice: string | null;
  /** Подсказка стенда (DEMO_LOGIN_HINT): нужна, только если PIN не пришли в строках */
  hint: string | null;
  canClose: boolean;
  onPick: (m: MechanicName) => void;
}) {
  const [query, setQuery] = useState('');
  const settings = useSettings();
  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? items.filter((m) => m.full_name.toLowerCase().includes(q)) : items;
  }, [items, query]);
  const { areaRef, pageSize } = useFitRows([settings.size, items, rows.length === 0]);
  const paged = usePaged(rows, pageSize, query);

  // Второй выход с экрана — отдельной строкой того же вида, что и список, сразу под ним.
  // data-head: расчёт строк на странице вычитает её высоту, как шапку таблицы
  const more = (
    <div className="lg-more" data-head>
      <div className="lg-more-box">
        {canClose ? (
          <button type="button" className="lg-row" onClick={closeLogin}>
            <Icon name="arrow-left" size="l" />
            <span>Вернуться к работе</span>
          </button>
        ) : (
          <Link href="/admin/login" className="lg-row">
            <Icon name="shield-lock" size="l" />
            <span>Администратор</span>
            <Icon name="chevron-right" />
          </Link>
        )}
      </div>
    </div>
  );

  return (
    <>
      <div className="lg-h">
        <h1>Кто работает?</h1>
        <p>Нажмите свою фамилию{hint && !items.some((m) => m.demo_pin) ? `. ${hint}` : ''}</p>
      </div>
      {notice ? (
        <div className="alert a-warn lg-note" role="alert">
          <Icon name="alert-triangle" />
          <span>{notice}</span>
        </div>
      ) : null}
      {items.length > SEARCH_FROM ? (
        <div className="ftools">
          <label className="search">
            <Icon name="search" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Escape') setQuery('');
              }}
              placeholder="Фамилия"
              aria-label="Поиск по фамилии"
              enterKeyHint="search"
            />
          </label>
        </div>
      ) : null}
      {!items.length ? (
        <div className="box center">
          <Icon name="users" size="xl" />
          <div className="e1">В списке пока никого нет</div>
          <div>Механиков заводит администратор в разделе «Механики».</div>
        </div>
      ) : !rows.length ? (
        <div className="box center">
          <Icon name="search-off" size="xl" />
          <div className="e1">Никого не нашли</div>
          <button type="button" className="btn" onClick={() => setQuery('')}>
            <Icon name="x" />
            Сбросить поиск
          </button>
        </div>
      ) : (
        <div className="fit-area" ref={areaRef}>
          <div className="ftable">
            {paged.rows.map((m) => (
              <button type="button" key={m.id} className="lg-row" data-row onClick={() => onPick(m)}>
                <Icon name="user" size="l" />
                <span>{m.full_name}</span>
                {/* Демо-стенд: PIN прямо в строке, чтобы проверяющему не искать его отдельно.
                    Ключ и двоеточие показывают, что это код для входа, а не часть имени */}
                {m.demo_pin ? (
                  <b className="lg-pin" title="PIN демо-механика для входа">
                    <Icon name="key" />
                    PIN: <span className="m">{m.demo_pin}</span>
                  </b>
                ) : null}
                <Icon name="chevron-right" />
              </button>
            ))}
          </div>
          {paged.pages > 1 ? null : more}
        </div>
      )}
      {paged.pages > 1 ? <Pager paged={paged} label="механики" /> : null}
      {paged.pages > 1 || !rows.length ? more : null}
    </>
  );
}

function PinPad({ who, onBack }: { who: MechanicName; onBack: (notice?: string | null) => void }) {
  const [pin, setPin] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  /** До какого времени вход закрыт после пяти неверных PIN, мс */
  const [lockedUntil, setLockedUntil] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());

  const locked = lockedUntil !== null && lockedUntil > now;
  const wait = locked ? Math.ceil((lockedUntil - now) / 1000) : 0;

  useEffect(() => {
    if (lockedUntil === null) return;
    const timer = window.setInterval(() => {
      const t = Date.now();
      setNow(t);
      if (t >= lockedUntil) {
        setLockedUntil(null);
        setError(null);
      }
    }, 1000);
    return () => window.clearInterval(timer);
  }, [lockedUntil]);

  const submit = useCallback(
    (value: string) => {
      setBusy(true);
      loginMechanic(who.id, value)
        .catch((e: unknown) => {
          setPin('');
          if (!(e instanceof LoginError)) {
            setError('Не получилось войти. Повторите.');
            return;
          }
          if (e.status === 404) {
            onBack(e.message);
            return;
          }
          if (e.retryAfter) {
            const until = Date.now() + e.retryAfter * 1000;
            setNow(Date.now());
            setLockedUntil(until);
          }
          setError(e.message);
        })
        .finally(() => setBusy(false));
    },
    [who.id, onBack],
  );

  const press = useCallback(
    (digit: string) => {
      if (busy || locked || pin.length >= PIN_LENGTH) return;
      setError(null);
      const next = pin + digit;
      setPin(next);
      // Четвёртая цифра — сразу проверка, без кнопки «Войти»
      if (next.length === PIN_LENGTH) submit(next);
    },
    [busy, locked, pin, submit],
  );

  const erase = useCallback(() => {
    if (busy) return;
    setPin((cur) => cur.slice(0, -1));
  }, [busy]);

  // С клавиатуры тоже можно: цифры, стереть, Esc — к списку
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (/^[0-9]$/.test(e.key)) press(e.key);
      else if (e.key === 'Backspace') erase();
      else if (e.key === 'Escape') onBack();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [press, erase, onBack]);

  return (
    <div className="pin">
      <div className="pin-who">{who.full_name}</div>
      <div className="pin-s">{locked ? `Вход закрыт, подождите ${wait} с` : 'Наберите свой PIN'}</div>
      <div className={`pin-dots${error && !locked ? ' bad' : ''}`} aria-label={`Набрано цифр: ${pin.length} из ${PIN_LENGTH}`}>
        {Array.from({ length: PIN_LENGTH }, (_, i) => (
          <i key={i} className={i < pin.length ? 'on' : ''} />
        ))}
      </div>
      <div className={`pin-err${error ? '' : ' wait'}`} role="alert">
        {error ?? (busy ? 'Проверяю…' : '')}
      </div>
      <div className="pin-pad">
        {['1', '2', '3', '4', '5', '6', '7', '8', '9'].map((d) => (
          <button type="button" key={d} onClick={() => press(d)} disabled={busy || locked}>
            {d}
          </button>
        ))}
        <button type="button" className="fn" onClick={() => onBack()}>
          <Icon name="arrow-left" />
          К списку
        </button>
        <button type="button" onClick={() => press('0')} disabled={busy || locked}>
          0
        </button>
        <button type="button" className="fn" onClick={erase} disabled={busy || !pin} aria-label="Стереть цифру">
          <Icon name="backspace" size="l" />
        </button>
      </div>
    </div>
  );
}
