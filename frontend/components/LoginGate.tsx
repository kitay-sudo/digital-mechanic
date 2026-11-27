'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useEffect, type ReactNode } from 'react';
import { isAdminPath, listenAuth, loadMe, useAuth } from '@/lib/auth';
import { Icon } from './Icon';
import { LoginAdmin } from './LoginAdmin';
import { LoginMechanic } from './LoginMechanic';

/**
 * Без входа экраны не открываются: механику — список «Кто работает» и PIN, на разделах
 * администратора — вход по логину и паролю. Механику разделы администратора закрыты.
 * Если вход на сервере выключен (AUTH_REQUIRED=0), всё открыто, как раньше.
 */
export function LoginGate({ children }: { children: ReactNode }) {
  const { me, wantLogin } = useAuth();
  const pathname = usePathname();

  useEffect(() => {
    listenAuth();
    void loadMe();
  }, []);

  if (!me) return null; // доли секунды до ответа сервера: без мигания чужого экрана
  if (pathname === '/admin/login') return <>{children}</>;
  if (wantLogin || (me.required && !me.role)) {
    if (!wantLogin && isAdminPath(pathname)) return <LoginAdmin next={null} />;
    return <LoginMechanic hint={me.hint} canClose={!me.required} />;
  }
  if (me.required && me.role !== 'admin' && isAdminPath(pathname)) return <AdminOnly />;
  return <>{children}</>;
}

function AdminOnly() {
  return (
    <div className="body al-body">
      <div className="box al">
        <div className="al-t">
          <Icon name="lock" size="l" />
          Раздел администратора
        </div>
        <div className="al-s">Журнал, механики и подключения открывает администратор системы.</div>
        <div className="pop-f">
          <Link href="/" className="btn">
            <Icon name="arrow-left" />
            К парку
          </Link>
          <Link href="/admin/login" className="btn pri">
            <Icon name="shield-lock" />
            Войти
          </Link>
        </div>
      </div>
    </div>
  );
}
