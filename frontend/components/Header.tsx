'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useCallback, useEffect, useState } from 'react';
import { api } from '@/lib/api';
import type { Config } from '@/lib/types';
import { Icon } from './Icon';
import { usePresence } from '@/lib/presence';
import { setFleetQuery, useFleetQuery } from '@/lib/search';
import { SettingsPanel } from './SettingsPanel';

export function Header() {
  const pathname = usePathname();
  const [config, setConfig] = useState<Config | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);

  useEffect(() => {
    api.config().then(setConfig).catch(() => setConfig(null));
  }, []);

  const closeSettings = useCallback(() => setSettingsOpen(false), []);
  const fleetQuery = useFleetQuery();
  // Адрес страницы на сервере и в браузере может не совпасть при первой отрисовке,
  // поэтому поиск появляется после загрузки: так разметка сервера и браузера одинаковая
  const [ready, setReady] = useState(false);
  useEffect(() => setReady(true), []);
  // Плавное закрытие: панель остаётся на экране, пока уезжает
  const settingsView = usePresence(settingsOpen ? true : null);

  return (
    <>
    <header className="top">
      <Link href="/" className="logo">
        <Icon name="engine" size="l" />
        Цифровой механик
      </Link>
      <nav className="nav only-d">
        <Link href="/" className={pathname === '/' ? 'on' : ''}>
          <Icon name="list-details" size="s" />
          Парк
        </Link>
        <Link href="/log" className={pathname === '/log' ? 'on' : ''}>
          <Icon name="history" size="s" />
          Журнал
        </Link>
      </nav>
      {/* Поиск по парку на компьютере стоит здесь, на всю свободную ширину. На телефоне он под шапкой */}
      {ready && pathname === '/' ? (
        <label className="search only-d">
          <Icon name="search" />
          <input
            value={fleetQuery}
            onChange={(e) => setFleetQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Escape') setFleetQuery('');
            }}
            placeholder="Госномер, гаражный номер или модель"
            aria-label="Поиск машины"
          />
        </label>
      ) : null}
      <div className="r">
        {config ? (
          <span className="only-d" title="Модель, которая отвечает механику">
            <Icon name="cpu" size="s" />
            модель: <span className="m">{config.llm.model}</span>
          </span>
        ) : null}
        {config?.llm.mock ? (
          <span className="mockbadge" title="Вместо настоящей модели работает заглушка. Ответы собираются из найденных фрагментов дословно.">
            заглушка<span className="only-d">&nbsp;модели</span>
          </span>
        ) : null}
        <button
          type="button"
          className={`hb${settingsOpen ? ' on' : ''}`}
          onClick={() => setSettingsOpen((v) => !v)}
          aria-label="Настройки: размер текста, подача, тема"
          aria-expanded={settingsOpen}
          title="Настройки"
        >
          <Icon name="adjustments-horizontal" />
        </button>
      </div>
      {settingsView.shown ? <SettingsPanel config={config} leaving={settingsView.leaving} onClose={closeSettings} /> : null}
    </header>
    {config?.kb && !config.kb.ready ? (
      <div className="kbwarn" role="alert">
        <Icon name="alert-triangle" />
        <span>
          <b>Руководства не загружены в базу знаний:</b> {config.kb.missing.join(', ')}. Ответы по ним недоступны. Положите PDF в
          папку knowledge/pdf и постройте индекс, как описано в README.
        </span>
      </div>
    ) : null}
    </>
  );
}
