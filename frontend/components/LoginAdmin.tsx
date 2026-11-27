'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { LoginError, loginAdmin, useAuth } from '@/lib/auth';
import { Icon } from './Icon';

/** Вход администратора по логину и паролю: журнал, механики, подключения */
export function LoginAdmin({ next = '/admin/mechanics' }: { next?: string | null }) {
  const router = useRouter();
  const { me } = useAuth();
  const [login, setLogin] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Отдельный экран входа: вошедший администратор сразу попадает в свои разделы
  useEffect(() => {
    if (next && me?.role === 'admin') router.replace(next);
  }, [me, next, router]);

  const submit = () => {
    if (!login.trim() || !password) {
      setError('Введите логин и пароль');
      return;
    }
    setBusy(true);
    setError(null);
    loginAdmin(login.trim(), password)
      .catch((e: unknown) => {
        setPassword('');
        setError(e instanceof LoginError ? e.message : 'Не получилось войти. Повторите.');
      })
      .finally(() => setBusy(false));
  };

  return (
    <div className="body al-body">
      <form
        className="box al"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <div className="al-t">
          <Icon name="shield-lock" size="l" />
          Вход администратора
        </div>
        {me?.role === 'mechanic' && me.mechanic ? (
          <div className="al-s">Сейчас вошёл механик {me.mechanic.full_name}. После входа администратора его вход закончится.</div>
        ) : (
          <div className="al-s">Журнал обращений, механики и подключения к внешним системам.</div>
        )}
        <label className="al-f">
          <span className="sp-l">Логин</span>
          <input
            className="inp"
            value={login}
            onChange={(e) => setLogin(e.target.value)}
            autoComplete="username"
            autoCapitalize="none"
            autoFocus
            maxLength={80}
          />
        </label>
        <label className="al-f">
          <span className="sp-l">Пароль</span>
          <input
            className="inp"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            maxLength={200}
          />
        </label>
        <div className="al-err" role="alert">
          {error}
        </div>
        <button type="submit" className="btn pri al-go" disabled={busy}>
          <Icon name={busy ? 'loader-2' : 'login-2'} className={busy ? 'spin' : ''} />
          Войти
        </button>
        <Link href="/" className="lg-link al-back">
          <Icon name="arrow-left" size="s" />
          {me?.role === 'mechanic' ? 'К парку' : 'Вход механика'}
        </Link>
      </form>
    </div>
  );
}
