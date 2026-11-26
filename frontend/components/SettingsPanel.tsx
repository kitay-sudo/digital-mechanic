'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { FALLBACK_LEVELS, setSettings, useSettings } from '@/lib/settings';
import type { Config } from '@/lib/types';
import { Icon } from './Icon';

function Choice<T extends string>({
  label,
  value,
  options,
  onChange,
  columns,
}: {
  label: string;
  value: T;
  options: { code: T; label: string }[];
  onChange: (v: T) => void;
  columns?: number;
}) {
  return (
    <div
      className="seg full"
      role="radiogroup"
      aria-label={label}
      style={columns ? { gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` } : undefined}
    >
      {options.map((o) => (
        <button
          key={o.code}
          type="button"
          role="radio"
          aria-checked={value === o.code}
          className={value === o.code ? 'on' : ''}
          onClick={() => onChange(o.code)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** Настройки механика: размер текста, подача, тема. */
export function SettingsPanel({ config, onClose }: { config: Config | null; onClose: () => void }) {
  const settings = useSettings();
  const [theme, setTheme] = useState<'light' | 'dark'>('light');

  useEffect(() => {
    setTheme(document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light');
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const applyTheme = (next: 'light' | 'dark') => {
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem('dm-theme', next);
    } catch {
      /* тема действует до перезагрузки */
    }
    setTheme(next);
  };

  const levels = config?.levels?.length ? config.levels : FALLBACK_LEVELS;
  const levelHint = levels.find((l) => l.code === settings.level)?.hint;

  return (
    <>
      <button type="button" className="sp-dim" aria-label="Закрыть настройки" onClick={onClose} />
      <aside className="sp" role="dialog" aria-label="Настройки">
        <div className="handle">
          <i />
        </div>
        <div className="sp-h">
          <Icon name="adjustments-horizontal" />
          <span>Настройки</span>
          <button type="button" className="hb" onClick={onClose} aria-label="Закрыть">
            <Icon name="x" />
          </button>
        </div>
        <div className="sp-b">
          <div className="sp-g">
            <div className="sp-l">Размер текста</div>
            <Choice
              label="Размер текста"
              value={settings.size}
              options={[
                { code: 'normal', label: 'Обычный' },
                { code: 'large', label: 'Крупный' },
              ]}
              onChange={(size) => setSettings({ size })}
            />
          </div>
          <div className="sp-g">
            <div className="sp-l">Подача</div>
            <Choice label="Подача" value={settings.level} options={levels} onChange={(level) => setSettings({ level })} />
            {levelHint ? <div className="sp-s">{levelHint}</div> : null}
          </div>
          <div className="sp-g">
            <div className="sp-l">Тема</div>
            <Choice
              label="Тема"
              value={theme}
              options={[
                { code: 'light', label: 'Светлая' },
                { code: 'dark', label: 'Тёмная' },
              ]}
              onChange={applyTheme}
            />
          </div>
          <Link href="/log" className="sp-link" onClick={onClose}>
            <Icon name="history" />
            <span>Журнал обращений</span>
            <Icon name="chevron-right" className="mut" />
          </Link>
        </div>
      </aside>
    </>
  );
}
