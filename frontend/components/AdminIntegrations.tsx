'use client';

import { useCallback, useEffect, useState } from 'react';
import { LoginError, authApi, type IntegrationItem, type Integrations } from '@/lib/auth';
import { Icon } from './Icon';
import { ErrorState, Loading } from './States';

type Key = IntegrationItem['key'];

const HINT: Record<Key, string> = {
  ml_url: 'Куда агент обращается за результатом проверки: POST /diagnose',
  toir_url: 'Куда уходит подтверждённая заявка на дефектовку: POST /tickets',
  alert_webhook_url: 'Сюда сервер сообщает о вопросах без ответа в руководстве и о сообщениях механиков',
  ml_token: 'Если ML-сервис требует ключ: заголовок Authorization: Bearer',
  toir_token: 'Если ТОиР требует ключ: заголовок Authorization: Bearer',
};

/** Экран администратора: адреса и токены внешних сервисов. Значения отсюда важнее .env и действуют сразу */
export function AdminIntegrations() {
  const [data, setData] = useState<Integrations | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState<Partial<Record<Key, string>>>({});
  const [saveError, setSaveError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    setError(null);
    authApi
      .integrations()
      .then((d) => {
        setData(d);
        setDraft({});
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  useEffect(load, [load]);

  const save = (patch: Partial<Record<Key, string>>) => {
    setBusy(true);
    setSaveError(null);
    authApi
      .saveIntegrations(patch)
      .then((d) => {
        setData(d);
        setDraft({});
        setSavedAt(new Date().toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' }));
      })
      .catch((e: unknown) => setSaveError(e instanceof LoginError ? e.message : 'Не получилось сохранить'))
      .finally(() => setBusy(false));
  };

  if (error) return <ErrorState text={error} onRetry={load} />;
  if (!data) return <Loading text="Загружаю подключения…" />;

  const changed = Object.keys(draft).length > 0;

  return (
    <div className="body">
      <form
        className="intg"
        onSubmit={(e) => {
          e.preventDefault();
          if (changed) save(draft);
        }}
      >
        <div className="ftools">
          <div className="ft-t">
            <Icon name="plug-connected" size="s" />
            <b>Подключения</b>
          </div>
          {savedAt && !changed ? <span className="ft-hint">сохранено в {savedAt}</span> : null}
          <button type="button" className="btn sm" onClick={load} disabled={busy} aria-label="Проверить связь">
            <Icon name="refresh" size="s" />
            <span className="only-d">Проверить связь</span>
          </button>
        </div>
        <div className="box intg-b">
          {data.items.map((it) => (
            <div className="intg-r" key={it.key}>
              <div className="intg-l">
                <span className="sp-l">{it.label}</span>
                <span className={`intg-src${it.source === 'db' ? ' db' : ''}`}>{it.source === 'db' ? 'задано здесь' : 'из .env'}</span>
                {it.key === 'ml_url' && data.health ? <Health ok={data.health.ml} /> : null}
                {it.key === 'toir_url' && data.health ? <Health ok={data.health.toir} /> : null}
              </div>
              <div className="intg-in">
                <input
                  className="inp"
                  type={it.key.endsWith('_token') ? 'password' : 'url'}
                  // Секрет (токен, веб-хук с ключом в пути) не показывается: поле пустое, вписывается новое значение
                  value={draft[it.key] ?? (it.secret ? '' : (it.value ?? ''))}
                  onChange={(e) => setDraft((d) => ({ ...d, [it.key]: e.target.value }))}
                  placeholder={it.secret ? (it.value ? `Задан: ${it.value}` : 'Не задан') : 'https://'}
                  autoComplete="off"
                  spellCheck={false}
                  aria-label={it.label}
                />
                {it.source === 'db' ? (
                  <button type="button" className="btn" onClick={() => save({ [it.key]: '' })} disabled={busy} title="Вернуть значение из .env">
                    <Icon name="arrow-back-up" />
                    <span className="only-d">Как в .env</span>
                  </button>
                ) : null}
              </div>
              <div className="sp-s">{HINT[it.key]}</div>
            </div>
          ))}
          <div className="intg-r">
            <div className="intg-l">
              <span className="sp-l">API для внешних систем</span>
            </div>
            <div className="intg-api">
              {data.api.enabled ? (
                <span className="intg-ok">
                  <Icon name="circle-check" />
                  Включено, ключей: {data.api.keys}
                </span>
              ) : (
                <span className="intg-bad">
                  <Icon name="circle-off" />
                  Выключено: ключи задаются в INTEGRATION_API_KEYS на сервере
                </span>
              )}
              <a href={data.api.docs_url} target="_blank" rel="noreferrer" className="lg-link">
                <Icon name="book-2" size="s" />
                Документация API
              </a>
            </div>
            <div className="sp-s">Учётная система парка, НейроДВС, 1С и кадровая система подключаются по ключу в заголовке X-API-Key.</div>
          </div>
        </div>
        <div className="intg-f">
          <div className="al-err" role="alert">
            {saveError}
          </div>
          <div className="pop-f">
            <button type="button" className="btn" onClick={() => setDraft({})} disabled={!changed || busy}>
              Отменить правки
            </button>
            <button type="submit" className="btn pri" disabled={!changed || busy}>
              <Icon name={busy ? 'loader-2' : 'device-floppy'} className={busy ? 'spin' : ''} />
              Сохранить
            </button>
          </div>
        </div>
      </form>
    </div>
  );
}

function Health({ ok }: { ok: boolean }) {
  return (
    <span className={ok ? 'intg-ok' : 'intg-bad'}>
      <Icon name={ok ? 'plug-connected' : 'plug-connected-x'} size="s" />
      {ok ? 'связь есть' : 'нет связи'}
    </span>
  );
}
