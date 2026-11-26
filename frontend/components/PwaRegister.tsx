'use client';

import { useEffect } from 'react';
import { startPwa } from '@/lib/pwa';

/** Подключает установку приложения: сервис-воркер и предложение «Установить». Ничего не рисует. */
export function PwaRegister() {
  useEffect(() => startPwa(), []);
  return null;
}
