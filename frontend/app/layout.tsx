import type { Metadata, Viewport } from 'next';
import type { ReactNode } from 'react';
import '@fontsource/ibm-plex-sans/cyrillic-400.css';
import '@fontsource/ibm-plex-sans/cyrillic-500.css';
import '@fontsource/ibm-plex-sans/cyrillic-600.css';
import '@fontsource/ibm-plex-sans/latin-400.css';
import '@fontsource/ibm-plex-sans/latin-500.css';
import '@fontsource/ibm-plex-sans/latin-600.css';
import '@fontsource/ibm-plex-mono/cyrillic-400.css';
import '@fontsource/ibm-plex-mono/cyrillic-500.css';
import '@fontsource/ibm-plex-mono/cyrillic-600.css';
import '@fontsource/ibm-plex-mono/latin-400.css';
import '@fontsource/ibm-plex-mono/latin-500.css';
import '@fontsource/ibm-plex-mono/latin-600.css';
import '@tabler/icons-webfont/dist/tabler-icons.min.css';
import './globals.css';
import './auth.css';
import './journal.css';
import { DemoLock } from '@/components/DemoLock';
import { Onboarding } from '@/components/Onboarding';
import { PwaRegister } from '@/components/PwaRegister';
import { Header } from '@/components/Header';
import { LoginGate } from '@/components/LoginGate';

export const metadata: Metadata = {
  title: 'Цифровой механик',
  applicationName: 'Цифровой механик',
  // Установка на iPhone: имя под значком и работа без рамки браузера
  appleWebApp: { capable: true, title: 'Механик', statusBarStyle: 'black-translucent' },
  description: 'AI-агент для диагностики ДВС: результат проверки, ответы по руководству со страницей, заявка на дефектовку',
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  themeColor: [
    { media: '(prefers-color-scheme: light)', color: '#ffffff' },
    { media: '(prefers-color-scheme: dark)', color: '#171a1e' },
  ],
};

// Тема и размер текста ставятся до отрисовки, чтобы не было вспышки.
const themeScript = `(function(){try{var t=localStorage.getItem('dm-theme');if(t!=='light'&&t!=='dark'){t=window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'}document.documentElement.dataset.theme=t}catch(e){document.documentElement.dataset.theme='light'}try{var s=JSON.parse(localStorage.getItem('dm-settings')||'{}');document.documentElement.dataset.size=s.size==='large'?'large':'normal'}catch(e){}})()`;

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ru" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body>
        <div className="shell">
          <Header />
          <main className="page">
            <LoginGate>{children}</LoginGate>
          </main>
        </div>
        <Onboarding />
        <DemoLock />
        <PwaRegister />
      </body>
    </html>
  );
}
