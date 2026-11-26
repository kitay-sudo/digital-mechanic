/** @type {import('next').NextConfig} */
const nextConfig = {
  // Самодостаточная сборка для Docker: .next/standalone/server.js
  output: 'standalone',
  // Запросы /api/* проксирует обработчик app/api/[...path]/route.ts.
  // Он читает BACKEND_URL при запуске, а не при сборке (rewrites фиксируются на сборке).

  // Сервис-воркер не должен залёживаться в кэше браузера: иначе телефоны не увидят новую версию
  async headers() {
    return [
      {
        source: '/sw.js',
        headers: [
          { key: 'Content-Type', value: 'application/javascript; charset=utf-8' },
          { key: 'Cache-Control', value: 'no-cache, no-store, must-revalidate' },
          { key: 'Service-Worker-Allowed', value: '/' },
        ],
      },
    ];
  },
};

export default nextConfig;
