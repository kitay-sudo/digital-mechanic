# Интерфейс «Цифровой механик»

Next.js (App Router, TypeScript), без UI-библиотек. Контракт с сервером: `../docs/api.md`.

## Запуск для разработки

```bash
pnpm install
```

```bash
BACKEND_URL=http://127.0.0.1:8000 pnpm dev
```

Интерфейс откроется на http://127.0.0.1:3000. Запросы `/api/*` проксирует обработчик `app/api/[...path]/route.ts`: адрес сервера он читает из `BACKEND_URL` при запуске, поток событий чата отдаёт без буферизации.

## Сборка

```bash
pnpm build
```

Самодостаточная сборка лежит в `.next/standalone` (так собирается `Dockerfile`).

## Без сервера

Для вёрстки есть мок по контракту, в продукт он не входит:

```bash
node dev/mock-api.mjs
```

```bash
BACKEND_URL=http://127.0.0.1:8100 pnpm dev
```

## Структура

- `app/page.tsx` — парк и сводка главного механика.
- `app/v/[id]/page.tsx` — рабочее место механика: машина, чат, страница руководства.
- `components/` — `FleetView`, `Workspace`, `VehiclePanel`, `MessageView` (вердикт, ответ, заявка), `ManualPanel`, `Composer`.
- `lib/` — типы по контракту, запросы и чтение потока NDJSON, форматирование.
- `app/globals.css` — токены светлой и тёмной темы и все стили.
