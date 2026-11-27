'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { LoginError, authApi, type FontSize, type Level, type Mechanic, type MechanicInput } from '@/lib/auth';
import { useFitRows, usePaged } from '@/lib/paging';
import { usePresence } from '@/lib/presence';
import { useSettings } from '@/lib/settings';
import { Icon } from './Icon';
import { Pager } from './Pager';
import { ErrorState, Loading } from './States';

const LEVEL_LABEL: Record<Level, string> = { expert: 'Опытный', novice: 'Новичок' };
const SIZE_LABEL: Record<FontSize, string> = { normal: 'Обычный', large: 'Крупный' };

/** Что открыто в панели: новый механик или правка существующего */
type Editing = { kind: 'new' } | { kind: 'edit'; mechanic: Mechanic };

/** Экран администратора: механики, которые входят в систему по PIN */
export function AdminMechanics() {
  const [items, setItems] = useState<Mechanic[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [editing, setEditing] = useState<Editing | null>(null);
  const sheet = usePresence(editing);
  const settings = useSettings();

  const load = useCallback(() => {
    setError(null);
    authApi
      .listMechanics()
      .then((r) => setItems(r.items))
      .catch((e: Error) => setError(e.message));
  }, []);

  useEffect(load, [load]);

  const rows = useMemo(() => {
    if (!items) return [];
    const q = query.trim().toLowerCase();
    return q ? items.filter((m) => m.full_name.toLowerCase().includes(q)) : items;
  }, [items, query]);

  const { areaRef, pageSize } = useFitRows([settings.size, items, rows.length === 0]);
  const paged = usePaged(rows, pageSize, query);

  const saved = useCallback((m: Mechanic) => {
    setItems((list) => {
      const rest = (list ?? []).filter((x) => x.id !== m.id);
      return [...rest, m].sort((a, b) => a.full_name.localeCompare(b.full_name, 'ru'));
    });
    setEditing(null);
  }, []);

  const deleted = useCallback((id: number) => {
    setItems((list) => (list ?? []).filter((x) => x.id !== id));
    setEditing(null);
  }, []);

  if (error) return <ErrorState text={error} onRetry={load} />;
  if (!items) return <Loading text="Загружаю механиков…" />;

  const active = items.filter((m) => m.active).length;

  return (
    <div className="body fit">
      <div className="ftools">
        <div className="ft-t">
          <Icon name="users" size="s" />
          <b>Механики</b>
          <span className="ft-n">{query.trim() ? `${rows.length} из ${items.length}` : items.length}</span>
          {active !== items.length ? <span className="ft-hint only-d">работают {active}</span> : null}
        </div>
        <button type="button" className="btn sm pri" onClick={() => setEditing({ kind: 'new' })}>
          <Icon name="user-plus" size="s" />
          Добавить
        </button>
        <label className="search">
          <Icon name="search" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Escape') setQuery('');
            }}
            placeholder="Фамилия"
            aria-label="Поиск механика"
          />
        </label>
      </div>
      {!items.length ? (
        <div className="box center">
          <Icon name="users" size="xl" />
          <div className="e1">Механиков пока нет</div>
          <div>Добавьте механика: он появится в списке «Кто работает» и войдёт своим PIN.</div>
        </div>
      ) : !rows.length ? (
        <div className="box center">
          <Icon name="search-off" size="xl" />
          <div className="e1">Никого не нашли</div>
          <div>Измените поиск</div>
        </div>
      ) : (
        <div className="fit-area" ref={areaRef}>
          <div className="ftable">
            <div className="mhead" data-head>
              <span>ФИО</span>
              <span>Возраст</span>
              <span>Подача</span>
              <span>Шрифт</span>
              <span>Статус</span>
            </div>
            {paged.rows.map((m) => (
              <button
                type="button"
                key={m.id}
                className={`mrow${m.active ? '' : ' off'}`}
                data-row
                onClick={() => setEditing({ kind: 'edit', mechanic: m })}
              >
                <span className="mn">{m.full_name}</span>
                <span className="d m">{m.age ?? '—'}</span>
                <span className="d">{LEVEL_LABEL[m.level]}</span>
                <span className="d">{SIZE_LABEL[m.font_size]}</span>
                <span className={`mst${m.active ? '' : ' off'}`}>
                  <Icon name={m.active ? 'circle-check' : 'circle-off'} size="s" />
                  {m.active ? 'Работает' : 'Отключён'}
                  {/* Строка открывается: правка, отключение входа, удаление */}
                  <Icon name="chevron-right" className="mchev" />
                </span>
                <span className="m2">
                  {LEVEL_LABEL[m.level]}, шрифт {SIZE_LABEL[m.font_size].toLowerCase()}
                  {m.age ? `, ${m.age} лет` : ''}
                </span>
              </button>
            ))}
          </div>
        </div>
      )}
      <Pager paged={paged} label="механики" />
      {sheet.shown ? (
        <MechanicSheet
          key={sheet.shown.kind === 'edit' ? sheet.shown.mechanic.id : 'new'}
          editing={sheet.shown}
          leaving={sheet.leaving}
          onClose={() => setEditing(null)}
          onSaved={saved}
          onDeleted={deleted}
        />
      ) : null}
    </div>
  );
}

function Seg<T extends string>({ label, value, options, onChange }: { label: string; value: T; options: [T, string][]; onChange: (v: T) => void }) {
  return (
    <div className="seg full" role="radiogroup" aria-label={label}>
      {options.map(([code, text]) => (
        <button key={code} type="button" role="radio" aria-checked={value === code} className={value === code ? 'on' : ''} onClick={() => onChange(code)}>
          {text}
        </button>
      ))}
    </div>
  );
}

/** Панель снизу: новый механик или правка. PIN хранится на сервере только хэшем, поэтому здесь его не видно */
function MechanicSheet({
  editing,
  leaving,
  onClose,
  onSaved,
  onDeleted,
}: {
  editing: Editing;
  leaving: boolean;
  onClose: () => void;
  onSaved: (m: Mechanic) => void;
  onDeleted: (id: number) => void;
}) {
  const current = editing.kind === 'edit' ? editing.mechanic : null;
  const [name, setName] = useState(current?.full_name ?? '');
  const [age, setAge] = useState(current?.age ? String(current.age) : '');
  const [level, setLevel] = useState<Level>(current?.level ?? 'expert');
  const [size, setSize] = useState<FontSize>(current?.font_size ?? 'normal');
  const [pin, setPin] = useState('');
  const [active, setActive] = useState(current?.active ?? true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  /** Удаление в два шага: сначала вопрос в самой панели */
  const [askDelete, setAskDelete] = useState(false);

  const remove = () => {
    if (!current) return;
    setBusy(true);
    setError(null);
    authApi
      .deleteMechanic(current.id)
      .then(() => onDeleted(current.id))
      .catch((e: unknown) => setError(e instanceof LoginError ? e.message : 'Не получилось удалить'))
      .finally(() => setBusy(false));
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const save = () => {
    if (name.trim().length < 2) return setError('Укажите ФИО');
    const years = age.trim() ? Number(age) : null;
    if (years !== null && (!Number.isInteger(years) || years < 16 || years > 90)) return setError('Возраст — число от 16 до 90');
    if (!current && !/^\d{4}$/.test(pin)) return setError('Задайте PIN из 4 цифр');
    if (current && pin && !/^\d{4}$/.test(pin)) return setError('PIN — ровно 4 цифры');
    const body: MechanicInput = { full_name: name.trim(), age: years, level, font_size: size };
    if (pin) body.pin = pin;
    if (current) body.active = active;
    setBusy(true);
    setError(null);
    (current ? authApi.updateMechanic(current.id, body) : authApi.createMechanic(body))
      .then(onSaved)
      .catch((e: unknown) => setError(e instanceof LoginError ? e.message : 'Не получилось сохранить'))
      .finally(() => setBusy(false));
  };

  return (
    <>
      <button type="button" className={`sp-dim${leaving ? ' leaving' : ''}`} aria-label="Закрыть" onClick={onClose} />
      <form
        className={`sp msheet${leaving ? ' leaving' : ''}`}
        role="dialog"
        aria-label={current ? 'Механик' : 'Новый механик'}
        onSubmit={(e) => {
          e.preventDefault();
          save();
        }}
      >
        <div className="handle">
          <i />
        </div>
        <div className="sp-h">
          <Icon name={current ? 'user-edit' : 'user-plus'} />
          <span>{current ? current.full_name : 'Новый механик'}</span>
          <button type="button" className="hb" onClick={onClose} aria-label="Закрыть">
            <Icon name="x" />
          </button>
        </div>
        <div className="sp-b">
          <label className="sp-g">
            <span className="sp-l">ФИО</span>
            <input className="inp sp-in" value={name} onChange={(e) => setName(e.target.value)} maxLength={80} autoFocus={!current} placeholder="Фамилия Имя Отчество" />
          </label>
          <label className="sp-g">
            <span className="sp-l">Возраст</span>
            <input className="inp sp-in" value={age} onChange={(e) => setAge(e.target.value.replace(/\D/g, '').slice(0, 2))} inputMode="numeric" placeholder="Не обязательно" />
          </label>
          <div className="sp-g">
            <div className="sp-l">Подача ответов</div>
            <Seg label="Подача ответов" value={level} options={[['expert', 'Опытный'], ['novice', 'Новичок']]} onChange={setLevel} />
            <div className="sp-s">{level === 'expert' ? 'Коротко, только суть' : 'С пояснениями и простыми словами'}</div>
          </div>
          <div className="sp-g">
            <div className="sp-l">Размер шрифта</div>
            <Seg label="Размер шрифта" value={size} options={[['normal', 'Обычный'], ['large', 'Крупный']]} onChange={setSize} />
            <div className="sp-s">Применяется после входа механика</div>
          </div>
          <label className="sp-g">
            <span className="sp-l">{current ? 'Новый PIN' : 'PIN'}</span>
            <input
              className="inp sp-in m"
              value={pin}
              onChange={(e) => setPin(e.target.value.replace(/\D/g, '').slice(0, 4))}
              inputMode="numeric"
              autoComplete="off"
              placeholder={current ? 'Оставьте пустым, чтобы не менять' : '4 цифры'}
            />
            <span className="sp-s">{current ? 'Новый PIN завершит вход механика на всех устройствах' : 'Сообщите PIN механику лично'}</span>
          </label>
          {current ? (
            <div className="sp-g">
              <div className="sp-l">Вход</div>
              <label className="msw">
                <span>
                  <b>Может входить</b>
                  <span className="sp-s">Выключите, и механика не будет в списке «Кто работает». Его подписи в чате и журнале останутся.</span>
                </span>
                <input type="checkbox" role="switch" className="switch" checked={active} onChange={(e) => setActive(e.target.checked)} />
              </label>
              {askDelete ? (
                <div className="mdel ask" role="alert">
                  <span>
                    Удалить механика насовсем? Вход пропадёт сразу, подписи в чате и журнале останутся текстом.
                  </span>
                  <div className="pop-f">
                    <button type="button" className="btn" onClick={() => setAskDelete(false)} disabled={busy}>
                      Не удалять
                    </button>
                    <button type="button" className="btn danger" onClick={remove} disabled={busy}>
                      <Icon name="trash" />
                      Удалить
                    </button>
                  </div>
                </div>
              ) : (
                <button type="button" className="mdel" onClick={() => setAskDelete(true)}>
                  <Icon name="trash" size="s" />
                  Удалить механика
                </button>
              )}
            </div>
          ) : null}
          <div className="msheet-f">
            <div className="al-err" role="alert">
              {error}
            </div>
            <div className="pop-f">
              <button type="button" className="btn" onClick={onClose}>
                Отмена
              </button>
              <button type="submit" className="btn pri" disabled={busy}>
                <Icon name={busy ? 'loader-2' : 'device-floppy'} className={busy ? 'spin' : ''} />
                Сохранить
              </button>
            </div>
          </div>
        </div>
      </form>
    </>
  );
}
