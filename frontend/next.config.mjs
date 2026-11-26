/** @type {import('next').NextConfig} */
const nextConfig = {
  // Самодостаточная сборка для Docker: .next/standalone/server.js
  output: 'standalone',
  // Запросы /api/* проксирует обработчик app/api/[...path]/route.ts.
  // Он читает BACKEND_URL при запуске, а не при сборке (rewrites фиксируются на сборке).
};

export default nextConfig;
