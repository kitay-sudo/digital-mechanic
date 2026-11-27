'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { FALLBACK_LEVELS, setSettings, useSettings } from '@/lib/settings';
import type { Config } from '@/lib/types';
import { Icon } from './Icon';
import { openTour } from './Onboarding';
import { appVersion, changeAppServer, usePwa } from '@/lib/pwa';

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

/** Настройки механика: фамилия, размер текста, тема, подача, какая модель отвечает. */
export function SettingsPanel({ config, leaving = false, onClose }: { config: Config | null; leaving?: boolean; onClose: () => void }) {
  const settings = useSettings();
  const pwa = usePwa();
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
      <button type="button" className={`sp-dim${leaving ? ' leaving' : ''}`} aria-label="Закрыть настройки" onClick={onClose} />
      <aside className={`sp${leaving ? ' leaving' : ''}`} role="dialog" aria-label="Настройки">
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
            <div className="sp-l">Механик</div>
            {/* Фамилия подписывает вопросы и отметки шагов: при смене сменщик видит, кто что сделал */}
            <input
              className="inp sp-in"
              value={settings.mechanic}
              onChange={(e) => setSettings({ mechanic: e.target.value })}
              placeholder="Фамилия"
              aria-label="Фамилия механика"
              maxLength={60}
            />
            <div className="sp-s">Видна в чате и журнале. При смене впишите свою.</div>
          </div>
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
          <div className="sp-g">
            <div className="sp-l">Подача</div>
            <Choice label="Подача" value={settings.level} options={levels} onChange={(level) => setSettings({ level })} />
            {levelHint ? <div className="sp-s">{levelHint}</div> : null}
          </div>
          {/* Пока работаем только как веб-версия: установку приложения и APK в интерфейсе не показываем.
              Код PWA и оболочки Android остаётся, включается возвратом этого блока. Внутри оболочки
              (если её всё же поставили) остаётся смена адреса сервера, иначе из неё не выйти на другой стенд */}
          {pwa.shell ? (
            <div className="sp-g">
              <div className="sp-l">Приложение</div>
              <div className="sp-ok">
                <Icon name="circle-check" />
                Приложение для Android{appVersion() ? `, версия ${appVersion()}` : ''}
              </div>
              <button type="button" className="sp-link" onClick={changeAppServer}>
                <Icon name="server-2" />
                <span>Сменить адрес сервера</span>
                <Icon name="chevron-right" className="mut" />
              </button>
            </div>
          ) : null}
          <button
            type="button"
            className="sp-link"
            onClick={() => {
              onClose();
              openTour();
            }}
          >
            <Icon name="help-circle" />
            <span>Как работать с системой</span>
            <Icon name="chevron-right" className="mut" />
          </button>
          <Link href="/log" className="sp-link" onClick={onClose}>
            <Icon name="history" />
            <span>Журнал обращений</span>
            <Icon name="chevron-right" className="mut" />
          </Link>
          {config ? (
            <div className="sp-model" title="Модель, которая отвечает механику">
              <Icon name="cpu" />
              <span>Модель</span>
              <span className="m">{config.llm.model}</span>
            </div>
          ) : null}
        </div>
      </aside>
    </>
  );
}
