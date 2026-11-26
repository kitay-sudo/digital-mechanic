'use client';

import { useEffect, useState } from 'react';
import { setSettings, useSettings } from '@/lib/settings';
import { Icon } from './Icon';

/** Согласие на обработку данных при первом открытии (152-ФЗ). */
export function Consent() {
  const settings = useSettings();
  const [mounted, setMounted] = useState(false);
  const [checked, setChecked] = useState(false);

  // До чтения настроек из браузера блок не показываем, иначе он мигнёт у согласившихся
  useEffect(() => setMounted(true), []);

  if (!mounted || settings.consent) return null;

  return (
    <div className="consent-dim">
      <div className="consent" role="dialog" aria-modal="true" aria-labelledby="consent-title">
        <div className="consent-h" id="consent-title">
          <Icon name="shield-check" />
          Перед началом работы
        </div>
        <div className="consent-b">
          <p>
            Сервис хранит историю чата и заявок. Голосовой ввод обрабатывает служба распознавания речи вашего браузера. Данные машин
            синтетические.
          </p>
          <label className="ack">
            <input type="checkbox" checked={checked} onChange={(e) => setChecked(e.target.checked)} />
            Согласен на обработку данных
          </label>
        </div>
        <div className="consent-f">
          <button type="button" className="btn pri grow" disabled={!checked} onClick={() => setSettings({ consent: true })}>
            Продолжить
          </button>
        </div>
      </div>
    </div>
  );
}
