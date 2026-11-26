'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import type { Config } from '@/lib/types';
import { Icon } from './Icon';

export function Header() {
  const pathname = usePathname();
  const [config, setConfig] = useState<Config | null>(null);
  const [theme, setTheme] = useState<'light' | 'dark' | null>(null);

  useEffect(() => {
    setTheme(document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light');
    api.config().then(setConfig).catch(() => setConfig(null));
  }, []);

  const toggleTheme = () => {
    const next = theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem('dm-theme', next);
    } catch {
      /* хранилище недоступно: тема действует до перезагрузки */
    }
    setTheme(next);
  };

  return (
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
      </nav>
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
          className="hb"
          onClick={toggleTheme}
          aria-label={theme === 'dark' ? 'Включить светлую тему' : 'Включить тёмную тему'}
          title={theme === 'dark' ? 'Светлая тема' : 'Тёмная тема'}
        >
          <Icon name={theme === 'dark' ? 'sun' : 'moon'} />
        </button>
      </div>
    </header>
  );
}
