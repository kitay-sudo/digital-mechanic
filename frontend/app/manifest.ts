import type { MetadataRoute } from 'next';

/** Манифест приложения: по нему браузер предлагает установить «Цифрового механика» на телефон и компьютер. */
export default function manifest(): MetadataRoute.Manifest {
  return {
    id: '/',
    name: 'Цифровой механик',
    short_name: 'Механик',
    description: 'AI-агент для диагностики ДВС: результат проверки, ответы по руководству со страницей, заявка на дефектовку',
    lang: 'ru',
    dir: 'ltr',
    start_url: '/',
    scope: '/',
    display: 'standalone',
    orientation: 'any',
    background_color: '#101215',
    theme_color: '#171a1e',
    categories: ['productivity', 'business'],
    icons: [
      { src: '/icons/icon-192.png', sizes: '192x192', type: 'image/png', purpose: 'any' },
      { src: '/icons/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any' },
      { src: '/icons/maskable-192.png', sizes: '192x192', type: 'image/png', purpose: 'maskable' },
      { src: '/icons/maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
    ],
    shortcuts: [
      { name: 'Парк', url: '/', icons: [{ src: '/icons/icon-192.png', sizes: '192x192', type: 'image/png' }] },
      { name: 'Журнал обращений', short_name: 'Журнал', url: '/log', icons: [{ src: '/icons/icon-192.png', sizes: '192x192', type: 'image/png' }] },
    ],
  };
}
