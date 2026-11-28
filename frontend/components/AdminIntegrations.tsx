'use client';

import { useCallback, useEffect, useState } from 'react';
import { LoginError, authApi, type IntegrationItem, type Integrations, type ModelChoice, type ModelMode } from '@/lib/auth';
import { Icon } from './Icon';
import { ErrorState, Loading } from './States';

type Key = IntegrationItem['key'];

/** Порядок полей: сервис и его ключ рядом */
const ORDER: Key[] = ['ml_url', 'ml_token', 'toir_url', 'toir_token', 'alert_webhook_url'];

const TITLE: Record<Key, string> = {
  ml_url: 'Адрес ML-сервиса «НейроДВС»',
  ml_token: 'Ключ доступа к ML-сервису',
  toir_url: 'Адрес ТОиР',
  toir_token: 'Ключ доступа к ТОиР',
  alert_webhook_url: 'Уведомления администратору',
};

const HINT: Record<Key, string> = {
  ml_url: 'Отсюда агент берёт результат проверки двигателя (POST /diagnose). Для пилота — адрес вашего сервиса диагностики.',
  ml_token: 'Нужен, только если ML-сервис закрыт ключом: сервер передаёт его в заголовке Authorization: Bearer. Пусто — без ключа.',
  toir_url: 'Сюда уходит заявка на дефектовку после подтверждения механика (POST /tickets).',
  toir_token: 'Нужен, только если ТОиР закрыт ключом: передаётся в заголовке Authorization: Bearer. Пусто — без ключа.',
  alert_webhook_url:
    'Адрес входящего веб-хука вашего мессенджера (Mattermost, Slack, Rocket.Chat). Срочное приходит сразу: нет руководств, ошибка диагностики, сбой агента. Вопросы без ответа в руководстве и сообщения механиков — сводкой в 18:00. Пусто — только журнал.',
};

const MODES: { code: ModelMode; label: string }[] = [
  { code: 'cloud', label: 'Облако, ключ встроен' },
  { code: 'yandex', label: 'Yandex AI Studio' },
  { code: 'local', label: 'Локальная модель' },
];

const MODE_HINT: Record<ModelMode, string> = {
  cloud: '',
  yandex: 'Российское облако: данные обрабатываются в России.',
  local: 'Модель на сервере заказчика (Ollama, vLLM): данные не выходят из контура.',
};

/** Экран администратора: адреса и токены внешних сервисов. Значения отсюда важнее .env и действуют сразу */
export function AdminIntegrations() {
  const [data, setData] = useState<Integrations | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState<Partial<Record<string, string>>>({});
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

  const save = (patch: Partial<Record<string, string>>) => {
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
          {data.model ? <ModelBlock m={data.model} draft={draft} setDraft={setDraft} /> : null}
          {[...data.items].sort((a, b) => ORDER.indexOf(a.key) - ORDER.indexOf(b.key)).map((it) => (
            <div className="intg-r" key={it.key}>
              <div className="intg-l">
                <b className="intg-t">{TITLE[it.key] ?? it.label}</b>
                {it.key === 'ml_url' && data.health ? <Health ok={data.health.ml} /> : null}
                {it.key === 'toir_url' && data.health ? <Health ok={data.health.toir} /> : null}
              </div>
              <div className="intg-h">{HINT[it.key]}</div>
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
              </div>
              {/* Откуда сейчас значение: из файла настроек сервера или задано на этом экране */}
              <div className="intg-src">
                {it.source === 'db' ? (
                  <>
                    <Icon name="pencil" size="s" />
                    <span>Задано на этом экране</span>
                    <button type="button" className="lg-link" onClick={() => save({ [it.key]: '' })} disabled={busy}>
                      Вернуть из файла настроек
                    </button>
                  </>
                ) : (
                  <>
                    <Icon name="file-settings" size="s" />
                    <span>{it.set ? 'Значение из файла настроек сервера' : 'Не задано ни здесь, ни в файле настроек сервера'}</span>
                  </>
                )}
              </div>
            </div>
          ))}
          <div className="intg-r">
            <div className="intg-l">
              <b className="intg-t">API для внешних систем</b>
            </div>
            <div className="intg-h">
              Это обратное направление: внешние системы сами обращаются к нам по ключу в заголовке X-API-Key. Учётная система
              парка передаёт машины, кадровая — механиков, «НейроДВС» — сигнал «проверка готова».
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
          </div>
          {/* Сохранение — последней строкой того же блока, прилипает к низу экрана, пока есть правки */}
          <div className={`intg-f${changed ? ' on' : ''}`}>
            <span className="intg-fs">
              {saveError ? <span className="intg-bad">{saveError}</span> : changed ? 'Есть несохранённые правки' : 'Правок нет'}
            </span>
            <button type="button" className="btn" onClick={() => setDraft({})} disabled={!changed || busy}>
              Отменить
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

/** Какая модель отвечает механикам: облако со встроенным ключом, Yandex AI Studio или модель в контуре заказчика */
function ModelBlock({
  m,
  draft,
  setDraft,
}: {
  m: ModelChoice;
  draft: Partial<Record<string, string>>;
  setDraft: (f: (d: Partial<Record<string, string>>) => Partial<Record<string, string>>) => void;
}) {
  const mode = (draft.llm_mode ?? m.mode) as ModelMode;
  const set = (key: string, value: string) => setDraft((d) => ({ ...d, [key]: value }));
  const field = (key: string, label: string, value: string | null, placeholder: string, secret = false) => (
    <label className="intg-fl" key={key}>
      <span className="intg-fn">{label}</span>
      <input
        className="inp"
        type={secret ? 'password' : 'text'}
        value={draft[key] ?? (secret ? '' : (value ?? ''))}
        onChange={(e) => set(key, e.target.value)}
        placeholder={secret && value ? `Задан: ${value}` : placeholder}
        autoComplete="off"
        spellCheck={false}
        aria-label={label}
      />
    </label>
  );
  const cloud = m.cloud.key_builtin
    ? `${m.cloud.provider}${m.cloud.via_proxyapi ? ' через ProxyAPI' : ''}, ключ уже встроен. Оплата в рублях за токены.`
    : 'Модель из файла настроек сервера.';
  return (
    <div className="intg-r">
      <div className="intg-l">
        <b className="intg-t">Модель</b>
        <span className="intg-ok">
          <Icon name="cpu" size="s" />
          сейчас отвечает: <span className="m">{m.model || 'не задана'}</span>
        </span>
      </div>
      <div className="intg-h">
        Какая модель отвечает механикам. Меняется сразу, без перезапуска сервера.
      </div>
      <div className="seg full intg-seg" role="radiogroup" aria-label="Модель">
        {MODES.map((o) => (
          <button
            key={o.code}
            type="button"
            role="radio"
            aria-checked={mode === o.code}
            className={mode === o.code ? 'on' : ''}
            onClick={() => set('llm_mode', o.code)}
          >
            {o.label}
          </button>
        ))}
      </div>
      {mode === 'cloud' ? (
        <div className="intg-src">
          <Icon name="key" size="s" />
          <span>{cloud}</span>
        </div>
      ) : (
        <div className="intg-h">{MODE_HINT[mode]}</div>
      )}
      {mode === 'yandex' ? (
        <div className="intg-fields">
          {field('yandex_folder', 'Каталог', m.yandex.folder, 'b1g...')}
          {field('yandex_key', 'API-ключ', m.yandex.key, 'Не задан', true)}
          {field('yandex_model', 'Модель', m.yandex.model, 'yandexgpt/latest')}
        </div>
      ) : null}
      {mode === 'local' ? (
        <div className="intg-fields">
          {field('llm_local_url', 'Адрес сервера', m.local.url, 'http://сервер:11434/v1')}
          {field('llm_local_model', 'Модель', m.local.model, 'qwen2.5:7b')}
          {field('llm_local_key', 'Ключ, если нужен', m.local.key, 'Не нужен', true)}
        </div>
      ) : null}
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
