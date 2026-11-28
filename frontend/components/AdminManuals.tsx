'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { LoginError, authApi, type Library, type LibraryManual } from '@/lib/auth';
import { usePresence } from '@/lib/presence';
import { Icon } from './Icon';
import { ErrorState, Loading } from './States';

/** Что открыто в панели: загрузка нового PDF или карточка руководства */
type Open = { kind: 'upload' } | { kind: 'manual'; id: string };

const plural = (n: number, one: string, few: string, many: string) => {
  const a = n % 100;
  const b = n % 10;
  if (a >= 11 && a <= 14) return many;
  if (b === 1) return one;
  if (b >= 2 && b <= 4) return few;
  return many;
};

/** Состояние руководства в индексе: идёт индексация, готово, ошибка или ещё не проиндексировано */
function IndexState({ m }: { m: LibraryManual }) {
  if (m.job?.state === 'running') {
    const pct = m.job.total ? Math.round((m.job.done / m.job.total) * 100) : 0;
    return (
      <span className="kst run">
        <span className="kbar" aria-hidden="true">
          <i style={{ width: `${pct}%` }} />
        </span>
        <span className="m">
          {m.job.done} из {m.job.total}
        </span>
      </span>
    );
  }
  if (m.job?.state === 'error') {
    return (
      <span className="kst bad">
        <Icon name="alert-triangle" size="s" />
        Ошибка индексации
      </span>
    );
  }
  if (!m.file) {
    return (
      <span className="kst bad">
        <Icon name="file-off" size="s" />
        Нет файла на сервере
      </span>
    );
  }
  if (!m.indexed_pages) {
    return (
      <span className="kst warn">
        <Icon name="clock" size="s" />
        Не проиндексировано
      </span>
    );
  }
  return (
    <span className="kst ok">
      <Icon name="circle-check" size="s" />
      <span className="m">{m.chunks}</span> {plural(m.chunks, 'фрагмент', 'фрагмента', 'фрагментов')}
    </span>
  );
}

/** Экран администратора: руководства в базе знаний. Загрузить PDF, проиндексировать, удалить устаревшее */
export function AdminManuals() {
  const [data, setData] = useState<Library | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<Open | null>(null);
  const sheet = usePresence(open);

  const load = useCallback(() => {
    setError(null);
    authApi
      .manuals()
      .then(setData)
      .catch((e: Error) => setError(e.message));
  }, []);

  useEffect(load, [load]);

  // Пока идёт индексация, ход обновляется сам
  const running = Boolean(data?.manuals.some((m) => m.job?.state === 'running'));
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => {
      authApi.manuals().then(setData).catch(() => undefined);
    }, 1500);
    return () => window.clearInterval(timer);
  }, [running]);

  const totals = useMemo(() => {
    const list = data?.manuals ?? [];
    return { pages: list.reduce((s, m) => s + m.indexed_pages, 0), chunks: list.reduce((s, m) => s + m.chunks, 0) };
  }, [data]);

  if (error) return <ErrorState text={error} onRetry={load} />;
  if (!data) return <Loading text="Загружаю руководства…" />;

  const current = sheet.shown?.kind === 'manual' ? data.manuals.find((m) => m.manual_id === (sheet.shown as { id: string }).id) : null;

  return (
    <div className="body fit">
      <div className="ftools">
        <div className="ft-t">
          <Icon name="books" size="s" />
          <b>Руководства</b>
          <span className="ft-n">{data.manuals.length}</span>
          <span className="ft-hint only-d">
            в поиске {totals.pages} {plural(totals.pages, 'страница', 'страницы', 'страниц')}
          </span>
        </div>
        <button type="button" className="btn sm pri" onClick={() => setOpen({ kind: 'upload' })}>
          <Icon name="file-upload" size="s" />
          Загрузить PDF
        </button>
      </div>
      {!data.manuals.length ? (
        <div className="box center">
          <Icon name="books" size="xl" />
          <div className="e1">Руководств пока нет</div>
          <div>Загрузите PDF руководства и укажите, к каким двигателям оно относится.</div>
        </div>
      ) : (
        <div className="fit-area">
          <div className="ftable">
            <div className="khead" data-head>
              <span>Документ</span>
              <span>Двигатели</span>
              <span>Страниц</span>
              <span>В поиске</span>
              <span>Откуда</span>
            </div>
            {data.manuals.map((m) => (
              <button type="button" key={m.manual_id} className="krow" data-row onClick={() => setOpen({ kind: 'manual', id: m.manual_id })}>
                <span className="kn">
                  <b>{m.short}</b>
                  <span className="kt">{m.title}</span>
                </span>
                <span className="d">{m.engines.join(', ')}</span>
                <span className="d m">{m.pages}</span>
                <IndexState m={m} />
                <span className="ksrc">
                  {m.source === 'upload' ? 'Загружено' : 'Материалы заказчика'}
                  <Icon name="chevron-right" className="mchev" />
                </span>
              </button>
            ))}
          </div>
        </div>
      )}
      {sheet.shown?.kind === 'upload' ? (
        <UploadSheet
          engines={data.engines}
          ocr={data.ocr}
          leaving={sheet.leaving}
          onClose={() => setOpen(null)}
          onDone={(d) => {
            setData(d);
            setOpen(null);
          }}
        />
      ) : null}
      {sheet.shown?.kind === 'manual' && current ? (
        <ManualSheet
          key={current.manual_id}
          manual={current}
          leaving={sheet.leaving}
          onClose={() => setOpen(null)}
          onData={setData}
          onDeleted={(d) => {
            setData(d);
            setOpen(null);
          }}
        />
      ) : null}
    </div>
  );
}

function useEscape(onClose: () => void) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);
}

/** Загрузка PDF: файл, названия и двигатели. После загрузки индексация начинается сама */
function UploadSheet({
  engines,
  ocr,
  leaving,
  onClose,
  onDone,
}: {
  engines: string[];
  ocr: boolean;
  leaving: boolean;
  onClose: () => void;
  onDone: (d: Library) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState('');
  const [short, setShort] = useState('');
  const [designation, setDesignation] = useState('');
  const [year, setYear] = useState('');
  const [chosen, setChosen] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEscape(onClose);

  const toggle = (e: string) => setChosen((list) => (list.includes(e) ? list.filter((x) => x !== e) : [...list, e]));

  const save = () => {
    if (!file) return setError('Выберите PDF руководства');
    if (title.trim().length < 3) return setError('Укажите название руководства');
    if (short.trim().length < 2) return setError('Укажите короткое название: его механик видит в ссылках');
    if (!chosen.length) return setError('Отметьте двигатели, к которым относится руководство');
    const y = year.trim() ? Number(year) : undefined;
    if (y !== undefined && (!Number.isInteger(y) || y < 1950 || y > 2100)) return setError('Год — четыре цифры');
    setBusy(true);
    setError(null);
    authApi
      .uploadManual(file, { title: title.trim(), short: short.trim(), designation: designation.trim(), year: y, engines: chosen })
      .then(onDone)
      .catch((e: unknown) => setError(e instanceof LoginError ? e.message : 'Не получилось загрузить'))
      .finally(() => setBusy(false));
  };

  return (
    <>
      <button type="button" className={`sp-dim${leaving ? ' leaving' : ''}`} aria-label="Закрыть" onClick={onClose} />
      <form
        className={`sp msheet${leaving ? ' leaving' : ''}`}
        role="dialog"
        aria-label="Загрузка руководства"
        onSubmit={(e) => {
          e.preventDefault();
          save();
        }}
      >
        <div className="handle">
          <i />
        </div>
        <div className="sp-h">
          <Icon name="file-upload" />
          <span>Новое руководство</span>
          <button type="button" className="hb" onClick={onClose} aria-label="Закрыть">
            <Icon name="x" />
          </button>
        </div>
        <div className="sp-b">
          <label className="sp-g kfile">
            <span className="sp-l">PDF</span>
            <input className="inp sp-in" type="file" accept="application/pdf,.pdf" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            <span className="sp-s">
              {file ? `${file.name}, ${(file.size / 1024 / 1024).toFixed(1)} МБ` : 'До 300 МБ'}
              {ocr ? '. Сканы без текста распознаются автоматически' : ''}
            </span>
          </label>
          <label className="sp-g">
            <span className="sp-l">Название</span>
            <input className="inp sp-in" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} placeholder="Двигатели ЯМЗ-536. Руководство по ремонту" />
          </label>
          <label className="sp-g">
            <span className="sp-l">Короткое название</span>
            <input className="inp sp-in" value={short} onChange={(e) => setShort(e.target.value)} maxLength={60} placeholder="РК ЯМЗ-536" />
            <span className="sp-s">Так документ подписан в ссылках у механика</span>
          </label>
          <label className="sp-g">
            <span className="sp-l">Обозначение и год</span>
            <span className="kpair">
              <input className="inp sp-in" value={designation} onChange={(e) => setDesignation(e.target.value)} maxLength={200} placeholder="536.01.02 РК" />
              <input className="inp sp-in m" value={year} onChange={(e) => setYear(e.target.value.replace(/\D/g, '').slice(0, 4))} inputMode="numeric" placeholder="Год" />
            </span>
          </label>
          <div className="sp-g keng">
            <div className="sp-l">Двигатели</div>
            <div className="kchips">
              {engines.map((e) => (
                <button key={e} type="button" className={`kchip${chosen.includes(e) ? ' on' : ''}`} aria-pressed={chosen.includes(e)} onClick={() => toggle(e)}>
                  <Icon name={chosen.includes(e) ? 'square-check' : 'square'} size="s" />
                  {e}
                </button>
              ))}
            </div>
            <span className="sp-s">Агент ищет ответ только в руководствах двигателя машины</span>
          </div>
          <div className="msheet-f">
            <div className="al-err" role="alert">
              {error}
            </div>
            <div className="pop-f">
              <button type="button" className="btn" onClick={onClose} disabled={busy}>
                Отмена
              </button>
              <button type="submit" className="btn pri" disabled={busy}>
                <Icon name={busy ? 'loader-2' : 'file-upload'} className={busy ? 'spin' : ''} />
                {busy ? 'Загружаю…' : 'Загрузить и проиндексировать'}
              </button>
            </div>
          </div>
        </div>
      </form>
    </>
  );
}

/** Карточка руководства: что в индексе, переиндексировать, удалить (в два шага) */
function ManualSheet({
  manual,
  leaving,
  onClose,
  onData,
  onDeleted,
}: {
  manual: LibraryManual;
  leaving: boolean;
  onClose: () => void;
  onData: (d: Library) => void;
  onDeleted: (d: Library) => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [askDelete, setAskDelete] = useState(false);
  useEscape(onClose);
  const running = manual.job?.state === 'running';

  const reindex = () => {
    setBusy(true);
    setError(null);
    authApi
      .indexManual(manual.manual_id)
      .then(onData)
      .catch((e: unknown) => setError(e instanceof LoginError ? e.message : 'Не получилось запустить индексацию'))
      .finally(() => setBusy(false));
  };
  const remove = () => {
    setBusy(true);
    setError(null);
    authApi
      .deleteManual(manual.manual_id)
      .then(onDeleted)
      .catch((e: unknown) => setError(e instanceof LoginError ? e.message : 'Не получилось удалить'))
      .finally(() => setBusy(false));
  };

  return (
    <>
      <button type="button" className={`sp-dim${leaving ? ' leaving' : ''}`} aria-label="Закрыть" onClick={onClose} />
      <div className={`sp msheet${leaving ? ' leaving' : ''}`} role="dialog" aria-label={manual.short}>
        <div className="handle">
          <i />
        </div>
        <div className="sp-h">
          <Icon name="book-2" />
          <span>{manual.short}</span>
          <button type="button" className="hb" onClick={onClose} aria-label="Закрыть">
            <Icon name="x" />
          </button>
        </div>
        <div className="sp-b">
          <div className="sp-g kfull">
            <div className="sp-l">Документ</div>
            <div className="kv">{manual.title}</div>
            <div className="sp-s">
              {[manual.designation, manual.year ? `${manual.year} г.` : null, manual.source === 'upload' ? 'загружено администратором' : 'из материалов заказчика']
                .filter(Boolean)
                .join(', ')}
            </div>
          </div>
          <div className="sp-g">
            <div className="sp-l">Двигатели</div>
            <div className="kv">{manual.engines.join(', ')}</div>
          </div>
          <div className="sp-g">
            <div className="sp-l">В поиске</div>
            <div className="kv">
              <IndexState m={manual} />
            </div>
            <div className="sp-s">
              {running ? 'Идёт индексация, можно закрыть панель' : `${manual.indexed_pages} из ${manual.pages} стр.`}
              {!running && manual.ocr_pages ? `, распознано сканов ${manual.ocr_pages}` : ''}
              {manual.job?.state === 'error' && manual.job.error ? `. ${manual.job.error}` : ''}
            </div>
          </div>
          <div className="sp-g kfull">
            {askDelete ? (
              <div className="mdel ask" role="alert">
                <span>
                  Удалить «{manual.short}»? Агент перестанет на него ссылаться.
                  {manual.source === 'upload' ? ' Файл будет удалён с сервера.' : ' Файл из материалов заказчика останется на сервере.'}
                </span>
                <div className="pop-f">
                  <button type="button" className="btn" onClick={() => setAskDelete(false)} disabled={busy}>
                    Не удалять
                  </button>
                  <button type="button" className="btn danger" onClick={remove} disabled={busy}>
                    Удалить
                  </button>
                </div>
              </div>
            ) : (
              <button type="button" className="mdel" onClick={() => setAskDelete(true)} disabled={running}>
                <Icon name="trash" size="s" />
                Удалить руководство
              </button>
            )}
          </div>
          <div className="msheet-f">
            <div className="al-err" role="alert">
              {error}
            </div>
            <div className="pop-f">
              <button type="button" className="btn" onClick={onClose}>
                Закрыть
              </button>
              <button type="button" className="btn pri" onClick={reindex} disabled={busy || running || !manual.file}>
                <Icon name={running ? 'loader-2' : 'refresh'} className={running ? 'spin' : ''} />
                {running ? 'Индексирую…' : 'Проиндексировать заново'}
              </button>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
