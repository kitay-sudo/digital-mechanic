'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useCallback, useEffect, useState } from 'react';
import { GAPS_EVENT, api } from '@/lib/api';
import { canAdmin, useAuth } from '@/lib/auth';
import type { Config } from '@/lib/types';
import { Icon } from './Icon';
import { usePresence } from '@/lib/presence';
import { SettingsPanel } from './SettingsPanel';

/** Как часто шапка спрашивает число неразобранных случаев, мс */
const GAPS_MS = 30_000;

export function Header() {
  const pathname = usePathname();
  const [config, setConfig] = useState<Config | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  // Разделы по ролям: механику — парк, администратору ещё журнал, механики и подключения
  const { me } = useAuth();
  const admin = canAdmin(me);
  const signedIn = Boolean(me && (!me.required || me.role));

  useEffect(() => {
    api.config().then(setConfig).catch(() => setConfig(null));
  }, []);

  // Число у пункта «Журнал»: сколько случаев «новый» и «в работе» ждут разбора (группа повторов — один случай)
  const [gaps, setGaps] = useState(0);
  useEffect(() => {
    const load = () => {
      if (!admin) return;
      if (document.visibilityState === 'visible') api.auditGaps().then((d) => setGaps(d.open)).catch(() => undefined);
    };
    load();
    const timer = window.setInterval(load, GAPS_MS);
    document.addEventListener('visibilitychange', load);
    window.addEventListener(GAPS_EVENT, load);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', load);
      window.removeEventListener(GAPS_EVENT, load);
    };
  }, [pathname, admin]);

  const closeSettings = useCallback(() => setSettingsOpen(false), []);
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
        {signedIn ? (
          <Link href="/" className={pathname === '/' ? 'on' : ''}>
            <Icon name="list-details" size="s" />
            Парк
          </Link>
        ) : null}
        {admin ? (
        <Link href="/log" className={pathname === '/log' ? 'on' : ''}>
          <Icon name="history" size="s" />
          Журнал
          {gaps ? (
            <b className="nbadge m" title={`Случаев ждут разбора (новые и в работе): ${gaps}`}>
              {gaps}
            </b>
          ) : null}
        </Link>
        ) : null}
        {admin ? (
          // Сводка смены для главного механика: кто работал, что сделано, метрики пилота
          <Link href="/shift" className={pathname === '/shift' ? 'on' : ''}>
            <Icon name="calendar-stats" size="s" />
            Смена
          </Link>
        ) : null}
        {admin ? (
          <Link href="/admin/mechanics" className={pathname === '/admin/mechanics' ? 'on' : ''}>
            <Icon name="users" size="s" />
            Механики
          </Link>
        ) : null}
        {admin ? (
          // Руководства в базе знаний: загрузить PDF, проиндексировать, удалить устаревшее
          <Link href="/admin/manuals" className={pathname === '/admin/manuals' ? 'on' : ''}>
            <Icon name="books" size="s" />
            Руководства
          </Link>
        ) : null}
        {admin ? (
          <Link href="/admin/integrations" className={pathname === '/admin/integrations' ? 'on' : ''}>
            <Icon name="plug-connected" size="s" />
            Подключения
          </Link>
        ) : null}
      </nav>
      <div className="r">
        {/* Какая модель отвечает, написано в настройках. Здесь только предупреждение о заглушке */}
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
