'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useRef, useState } from 'react';
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
  const [copied, setCopied] = useState<'login' | 'password' | null>(null);
  const goRef = useRef<HTMLButtonElement>(null);
  // Демо-стенд: логин и пароль видны экспертам, их можно скопировать или сразу подставить в форму
  const access = me?.demo_admin ?? null;

  const copy = (what: 'login' | 'password', value: string) => {
    const done = () => {
      setCopied(what);
      window.setTimeout(() => setCopied((c) => (c === what ? null : c)), 1600);
    };
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(value).then(done, () => fallbackCopy(value) && done());
    } else if (fallbackCopy(value)) done();
  };

  const fill = () => {
    if (!access) return;
    setLogin(access.login);
    setPassword(access.password);
    setError(null);
    goRef.current?.focus();
  };

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
        {access ? (
          <div className="al-demo">
            <div className="sp-l">Доступ для экспертов</div>
            <div className="al-cred">
              <span className="al-k">Логин</span>
              <span className="m">{access.login}</span>
              <button type="button" className="hb" onClick={() => copy('login', access.login)} aria-label="Скопировать логин" title="Скопировать">
                <Icon name={copied === 'login' ? 'check' : 'copy'} />
              </button>
            </div>
            <div className="al-cred">
              <span className="al-k">Пароль</span>
              <span className="m">{access.password}</span>
              <button type="button" className="hb" onClick={() => copy('password', access.password)} aria-label="Скопировать пароль" title="Скопировать">
                <Icon name={copied === 'password' ? 'check' : 'copy'} />
              </button>
            </div>
            <button type="button" className="btn al-fill" onClick={fill}>
              <Icon name="arrow-down" />
              Подставить в форму
            </button>
          </div>
        ) : null}
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
        <button type="submit" className="btn pri al-go" disabled={busy} ref={goRef}>
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

/** Копирование без Clipboard API (старый браузер или страница не по HTTPS) */
function fallbackCopy(value: string): boolean {
  const area = document.createElement('textarea');
  area.value = value;
  area.setAttribute('readonly', '');
  area.style.position = 'fixed';
  area.style.opacity = '0';
  document.body.appendChild(area);
  area.select();
  let ok = false;
  try {
    ok = document.execCommand('copy');
  } catch {
    ok = false;
  }
  area.remove();
  return ok;
}
