import type { NextRequest } from 'next/server';

// Прокси на сервер агента. Адрес берётся из BACKEND_URL при запуске,
// тело ответа отдаётся потоком без буферизации (нужно для событий чата).
export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

const PASS_HEADERS = ['content-type', 'cache-control', 'content-disposition'];

async function proxy(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  const base = (process.env.BACKEND_URL || 'http://127.0.0.1:8000').replace(/\/+$/, '');
  const url = `${base}/api/${path.map(encodeURIComponent).join('/')}${req.nextUrl.search}`;

  const headers = new Headers();
  const ct = req.headers.get('content-type');
  if (ct) headers.set('content-type', ct);
  const accept = req.headers.get('accept');
  if (accept) headers.set('accept', accept);
  // Вход: кука сессии механика или администратора; внешние системы — ключ X-API-Key (/api/docs)
  for (const h of ['cookie', 'x-api-key']) {
    const v = req.headers.get(h);
    if (v) headers.set(h, v);
  }
  // Кука сессии ставится с флагом Secure, если интерфейс открыт по HTTPS
  headers.set('x-forwarded-proto', req.headers.get('x-forwarded-proto') || req.nextUrl.protocol.replace(':', ''));

  const init: RequestInit = { method: req.method, headers, cache: 'no-store', redirect: 'manual' };
  if (req.method !== 'GET' && req.method !== 'HEAD') init.body = await req.arrayBuffer();

  try {
    const upstream = await fetch(url, init);
    const out = new Headers();
    for (const h of PASS_HEADERS) {
      const v = upstream.headers.get(h);
      if (v) out.set(h, v);
    }
    for (const c of upstream.headers.getSetCookie()) out.append('set-cookie', c);
    if (!out.has('cache-control')) out.set('cache-control', 'no-store');
    out.set('x-accel-buffering', 'no');
    return new Response(upstream.body, { status: upstream.status, headers: out });
  } catch {
    return Response.json({ detail: 'Сервер агента недоступен. Проверьте, что он запущен.' }, { status: 502 });
  }
}

export { proxy as GET, proxy as POST, proxy as PATCH, proxy as PUT, proxy as DELETE };
