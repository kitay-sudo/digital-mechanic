// Мок сервера ТОЛЬКО для разработки интерфейса без backend. В продукт не входит.
// Запуск: node dev/mock-api.mjs  (порт 8100, можно задать PORT)
// Интерфейс: BACKEND_URL=http://127.0.0.1:8100 pnpm dev
import http from 'node:http';

const PORT = Number(process.env.PORT || 8100);
const iso = (d, h = 10, m = 0) => `2026-11-${String(d).padStart(2, '0')}T${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:00+03:00`;
const sess = (id, day, status, type, title, score, conf, q, desc) => ({
  session_id: id, checked_at: iso(day, 8 + (day % 9), (day * 7) % 60), status, anomaly_type: type, anomaly_title: title,
  anomaly_score: score, confidence: conf, signal_quality: q, description: desc, ticket_id: null,
});
const OK = 'Признаков неисправности в записи не найдено';
const MANUALS = {
  'ЯМЗ-236М2': [
    { manual_id: 'yamz236_re', designation: '236-3902150-Б РЭ', title: 'Руководство по эксплуатации двигателей ЯМЗ-236М2', short: 'РЭ ЯМЗ-236', pages: 172 },
    { manual_id: 'yamz236_rk', designation: '236.01.01 РК', title: 'Руководство по ремонту двигателей ЯМЗ-236М2', short: 'РК ЯМЗ-236', pages: 287 },
  ],
  'ЯМЗ-536': [
    { manual_id: 'yamz536_re', designation: '536.3902150 РЭ', title: 'Руководство по эксплуатации двигателей ЯМЗ-536', short: 'РЭ ЯМЗ-536', pages: 285 },
    { manual_id: 'yamz536_rk', designation: '536.01.02 РК', title: 'Руководство по ремонту двигателей ЯМЗ-536', short: 'РК ЯМЗ-536', pages: 603 },
  ],
  'ЗМЗ-5234.10': [{ manual_id: 'zmz5234_rk', designation: 'Двигатели ЗМЗ-5234.10 со сцеплением. Руководство по ремонту', title: 'Руководство по ремонту', short: 'РК ЗМЗ-5234', pages: 158 }],
  'ЗМЗ-40905.10': [{ manual_id: 'zmz409_rk', designation: 'Руководство по эксплуатации, техническому обслуживанию и ремонту двигателей ЗМЗ-40904.10 и ЗМЗ-40905.10', title: 'Руководство по эксплуатации, ТО и ремонту', short: 'РК ЗМЗ-409', pages: 238 }],
};
const V = [
  { vehicle_id: 'M333YK47', garage_no: 'Г-105', make: 'МАЗ', model: 'МАЗ-5337', vehicle_type: 'грузовой автомобиль', engine_model: 'ЯМЗ-236М2', fuel: 'дизель', fleet_status: 'quarantine', needs_recheck: false, priority: 'high',
    sessions: [sess('S-0011', 2, 'normal', null, null, 0.21, 0.84, 'good', OK), sess('S-0012', 9, 'normal', null, null, 0.38, 0.8, 'good', OK), sess('S-0013', 14, 'anomaly', 'F02', 'Низкое давление масла', 0.64, 0.79, 'good', 'Глухой стук в нижней части блока на холостом ходу'), sess('S-0014', 20, 'anomaly', 'F02', 'Низкое давление масла', 0.81, 0.86, 'good', 'Глухой стук в нижней части блока, усиливается при сбросе оборотов')],
    trend: { direction: 'rising', text: 'Оценка отклонения растёт три проверки подряд' } },
  { vehicle_id: 'P456AT178', garage_no: 'Г-101', make: 'ПАЗ', model: 'ПАЗ-3205', vehicle_type: 'автобус', engine_model: 'ЗМЗ-5234.10', fuel: 'бензин', fleet_status: 'attention', needs_recheck: true, priority: null,
    sessions: [sess('S-0001', 3, 'normal', null, null, 0.05, 0.81, 'good', OK), sess('S-0002', 11, 'normal', null, null, 0.13, 0.82, 'good', OK), sess('S-0003', 19, 'check_failed', null, null, null, null, 'bad', 'Запись непригодна: посторонний шум перекрывает двигатель')],
    trend: { direction: 'none', text: 'Последняя запись непригодна, динамику оценить нельзя' } },
  { vehicle_id: 'Y652CK98', garage_no: 'Г-132', make: 'ПАЗ', model: 'ПАЗ-3206', vehicle_type: 'автобус', engine_model: 'ЗМЗ-5234.10', fuel: 'бензин', fleet_status: 'attention', needs_recheck: false, priority: 'medium',
    sessions: [sess('S-0130', 4, 'normal', null, null, 0.18, 0.8, 'good', OK), sess('S-0131', 12, 'normal', null, null, 0.22, 0.78, 'good', OK), sess('S-0132', 21, 'anomaly', 'F08', 'Дизельная топливоподача', 0.7, 0.6, 'warning', 'Жёсткая работа с резким стуком в цилиндрах, дымный выхлоп')],
    trend: { direction: 'rising', text: 'Оценка выросла на последней проверке' } },
  { vehicle_id: 'K208OP54', garage_no: 'Г-118', make: 'МАЗ', model: null, vehicle_type: 'грузовой автомобиль', engine_model: 'ЯМЗ-536', fuel: 'дизель', fleet_status: 'attention', needs_recheck: false, priority: 'low',
    sessions: [sess('S-0071', 5, 'normal', null, null, 0.2, 0.83, 'good', OK), sess('S-0072', 13, 'normal', null, null, 0.25, 0.8, 'good', OK), sess('S-0073', 18, 'normal', null, null, 0.31, 0.81, 'good', OK), sess('S-0074', 22, 'anomaly', 'F04', 'Ремённый привод агрегатов', 0.55, 0.71, 'good', 'Свист в передней части двигателя при пуске')],
    trend: { direction: 'rising', text: 'Оценка медленно растёт' } },
  { vehicle_id: 'T901MX77', garage_no: 'Г-140', make: 'УАЗ', model: 'УАЗ Патриот', vehicle_type: 'легковой автомобиль', engine_model: 'ЗМЗ-40905.10', fuel: 'бензин', fleet_status: 'ok', needs_recheck: false, priority: null,
    sessions: [sess('S-0160', 6, 'normal', null, null, 0.11, 0.85, 'good', OK), sess('S-0161', 15, 'normal', null, null, 0.09, 0.86, 'good', OK), sess('S-0162', 23, 'normal', null, null, 0.12, 0.84, 'good', OK)],
    trend: { direction: 'stable', text: 'Оценка стабильна, отклонений нет' } },
  { vehicle_id: 'A114BC52', garage_no: 'Г-109', make: 'Урал', model: 'Урал-4320-10', vehicle_type: 'грузовой автомобиль', engine_model: 'ЯМЗ-236М2', fuel: 'дизель', fleet_status: 'ok', needs_recheck: false, priority: null,
    sessions: [sess('S-0040', 7, 'normal', null, null, 0.15, 0.82, 'good', OK), sess('S-0041', 16, 'normal', null, null, 0.17, 0.83, 'good', OK), sess('S-0042', 24, 'normal', null, null, 0.14, 0.8, 'good', OK)],
    trend: { direction: 'stable', text: 'Оценка стабильна, отклонений нет' } },
];
V.forEach((v) => { v.title = v.model || v.make; v.tickets = []; });

const conversations = new Map();
const drafts = new Map();
let seq = 0;
let ticketNo = 0;
const now = () => new Date().toISOString();
const usage = (n) => ({ input_tokens: 12400 * n, output_tokens: 820 * n, cost_rub: 3.2 * n, duration_ms: 2100 * n, llm_calls: n, model: 'mock-llm', mock: true });
const last = (v) => v.sessions[v.sessions.length - 1];
const brief = (v) => {
  const s = last(v);
  const { description, ticket_id, ...ls } = s;
  const { sessions, trend, ...rest } = v;
  return { ...rest, last_session: ls, sessions_count: v.sessions.length, tickets: v.tickets.map((t) => ({ ticket_id: t.ticket_id, session_id: t.session_id, created_at: t.created_at })) };
};
const detail = (v) => ({ ...brief(v), sessions: v.sessions, manuals: MANUALS[v.engine_model] || [], trend: v.trend, tickets: v.tickets });
const ref = (v, page, quote) => { const m = (MANUALS[v.engine_model] || [])[MANUALS[v.engine_model].length - 1]; return { manual_id: m.manual_id, designation: m.designation, short: m.short, pdf_page: page, quote }; };

const ACTIONS = { high: 'На дефектовку до выпуска в рейс', medium: 'Дефектовка на ближайшее ТО, работа под наблюдением', low: 'Машина работает, узел проверяется на следующей проверке' };
const LABELS = { high: 'высокий', medium: 'средний', low: 'низкий' };

function verdict(v, s, steps) {
  const base = { id: `m_${++seq}`, role: 'assistant', created_at: now(), session_id: s.session_id, kind: 'verdict', steps, usage: usage(3) };
  const diagnosis = { vehicle_id: v.vehicle_id, ...s, model_version: 'mock-v1' };
  delete diagnosis.ticket_id;
  if (s.status === 'check_failed') {
    return { ...base, text: 'О двигателе выводов не делаю. Повторите запись, после этого разберу результат.', diagnosis,
      assessment: { outcome: 'check_failed', priority: null, priority_label: null, priority_action: null, basis: [], flags: { check_failed: true, quality_warning: false, low_confidence: false, engine_mismatch: false }, warnings: [], ticket_allowed: false, ticket_block_reason: 'При сбое записи диагноз не ставится и заявка не оформляется.', confidence_min: 0.5 }, answer: null };
  }
  if (s.status === 'normal') {
    return { ...base, text: 'Значимых отклонений нет, машину можно эксплуатировать. Следующая проверка по графику.', diagnosis,
      assessment: { outcome: 'normal', priority: null, priority_label: null, priority_action: null, basis: [], flags: { check_failed: false, quality_warning: false, low_confidence: false, engine_mismatch: false }, warnings: [], ticket_allowed: false, ticket_block_reason: 'Проверка в норме, заявка не нужна.', confidence_min: 0.5 }, answer: null };
  }
  const mismatch = s.anomaly_type === 'F08' && v.fuel === 'бензин';
  const pr = v.priority || 'medium';
  if (mismatch) {
    return { ...base, text: 'Тип неисправности не подходит этому двигателю: он бензиновый. В руководстве инструкции нет.', diagnosis,
      assessment: { outcome: 'anomaly', priority: pr, priority_label: LABELS[pr], priority_action: ACTIONS[pr], basis: ['Базовая критичность типа F08: средняя', 'Оценка отклонения 0,70: без поправки', 'Запись с помехами: приоритет не выше среднего'], flags: { check_failed: false, quality_warning: true, low_confidence: false, engine_mismatch: true }, warnings: ['Запись с помехами: вывод предварительный, лучше повторить запись', 'Тип «Дизельная топливоподача» не соответствует бензиновому двигателю ЗМЗ-5234.10. Проверьте данные проверки'], ticket_allowed: false, ticket_block_reason: 'В руководстве на двигатель ЗМЗ-5234.10 нет инструкции по найденной неисправности.', confidence_min: 0.5 },
      answer: { summary: '', observations: ['ML-сервис сообщил о жёсткой работе со стуком в цилиндрах и дымном выхлопе'], hypotheses: ['Возможна ошибка в карточке машины или в данных проверки'], checks: [], repair: [], limitations: ['Данные руководств других двигателей не используются'], not_found: true, recommendation_text: `Рекомендация на дефектовку\nМашина: ${v.title} ${v.vehicle_id}, двигатель ${v.engine_model}\nПроверка: ${s.session_id}\nРезультат: отклонение F08 «Дизельная топливоподача», оценка 0,70, уверенность 0,60, запись с помехами\nВ руководстве на этот двигатель инструкции нет. Нужна дефектовка по порядку автопарка.` } };
  }
  return { ...base, text: 'Вероятно, давление масла ниже нормы. Оценка растёт третью проверку подряд, поэтому приоритет высокий.', diagnosis,
    assessment: { outcome: 'anomaly', priority: pr, priority_label: LABELS[pr], priority_action: ACTIONS[pr], basis: [`Базовая критичность типа ${s.anomaly_type}: ${pr === 'high' ? 'высокая' : pr === 'low' ? 'низкая' : 'средняя'}`, `Оценка отклонения ${String(s.anomaly_score).replace('.', ',')}: без поправки`, 'Оценка растёт три проверки подряд'], flags: { check_failed: false, quality_warning: false, low_confidence: false, engine_mismatch: false }, warnings: [], ticket_allowed: true, ticket_block_reason: null, confidence_min: 0.5 },
    answer: { summary: '', observations: [s.description, 'Прошлая проверка S-0013 показала тот же тип с оценкой 0,64'],
      hypotheses: ['Износ вкладышей коренных или шатунных подшипников', 'Неисправность редукционного клапана масляного насоса'],
      checks: [{ text: 'Проверить давление масла контрольным манометром на прогретом двигателе', refs: [ref(v, 112, 'Давление масла проверять контрольным манометром на прогретом двигателе')] }, { text: 'Сравнить с нормой давления при номинальной и минимальной частоте вращения', refs: [ref(v, 113, 'Давление масла в системе при номинальной частоте вращения'), ref(v, 40, 'Измерение производить в четырёх точках')] }],
      repair: [{ text: 'При давлении ниже нормы проверить редукционный клапан и масляный насос', refs: [ref(v, 118, 'Проверить редукционный клапан масляного насоса')] }],
      limitations: ['Числа норм смотрите на указанных страницах: в мок-данных они не приводятся'], not_found: false, recommendation_text: null } };
}

function answerMsg(v, s, text, steps) {
  const base = { id: `m_${++seq}`, role: 'assistant', created_at: now(), session_id: s?.session_id ?? null, kind: 'answer', text: '', steps, usage: usage(2) };
  if (/ресурс|гарант|цена|стоит/i.test(text)) {
    return { ...base, answer: { summary: '', observations: [], hypotheses: [], checks: [], repair: [], limitations: ['Проверены руководства этого двигателя, раздела с такими данными нет', 'Рекомендую дефектовку: решение примет мастер'], not_found: true, recommendation_text: null } };
  }
  return { ...base, answer: { summary: 'По руководству перегонять машину с этим признаком не рекомендуется: сначала проверьте давление масла.', observations: [], hypotheses: ['При низком давлении масла возможен ускоренный износ подшипников коленчатого вала'],
    checks: [{ text: 'Перед выездом убедиться, что давление масла в норме на прогретом двигателе', refs: [ref(v, 113, 'Давление масла в системе при номинальной частоте вращения')] }], repair: [], limitations: ['Прямого запрета эксплуатации в руководстве не найдено, это рекомендация'], not_found: false, recommendation_text: null } };
}

function draftMsg(v, s, steps) {
  const id = `d_${++seq}`;
  const warn = s.signal_quality === 'warning';
  const draft = { draft_id: id, vehicle_id: v.vehicle_id, session_id: s.session_id, status: 'draft', anomaly_type: s.anomaly_type, anomaly_title: s.anomaly_title,
    conclusion: `Вероятно ${String(s.anomaly_title).toLowerCase()}. Требуется дефектовка узла по руководству.`, urgency: v.priority || 'medium', urgency_basis: ['базовая критичность типа', `оценка отклонения ${String(s.anomaly_score).replace('.', ',')}`],
    operations: [{ text: 'Проверить давление масла контрольным манометром на прогретом двигателе', refs: [ref(v, 112, 'Давление масла проверять контрольным манометром на прогретом двигателе')] }, { text: 'Проверить редукционный клапан масляного насоса', refs: [ref(v, 118, 'Проверить редукционный клапан масляного насоса')] }],
    spare_parts: [], references: [], requires_warning_ack: warn, warnings: warn ? ['Запись с помехами: вывод предварительный'] : [], ticket_id: null };
  const m = (MANUALS[v.engine_model] || []).slice(-1)[0];
  draft.references = [112, 118].map((p) => ({ manual: m.designation, manual_id: m.manual_id, pdf_page: p }));
  drafts.set(id, draft);
  return { id: `m_${++seq}`, role: 'assistant', created_at: now(), session_id: s.session_id, kind: 'ticket_draft', text: 'Черновик заявки готов. Проверьте состав и подтвердите.', draft, steps, usage: usage(2) };
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const send = (res, obj) => res.write(JSON.stringify(obj) + '\n');
const jsonRes = (res, code, obj) => { res.writeHead(code, { 'content-type': 'application/json; charset=utf-8' }); res.end(JSON.stringify(obj)); };
const readBody = (req) => new Promise((resolve) => { let b = ''; req.on('data', (c) => (b += c)); req.on('end', () => { try { resolve(b ? JSON.parse(b) : {}); } catch { resolve({}); } }); });

async function runSteps(res, list) {
  const done = [];
  for (const [i, st] of list.entries()) {
    const step = { id: `s${i + 1}`, tool: st[0], title: st[1], status: 'running', detail: null };
    send(res, { type: 'step', ...step });
    await sleep(500);
    step.status = 'done';
    step.detail = st[2];
    send(res, { type: 'step', ...step });
    done.push(step);
  }
  return done;
}

async function chat(req, res) {
  const body = await readBody(req);
  const v = V.find((x) => x.vehicle_id === body.vehicle_id);
  if (!v) return jsonRes(res, 404, { detail: 'Машина не найдена' });
  const s = v.sessions.find((x) => x.session_id === body.session_id) || last(v);
  const conv = conversations.get(v.vehicle_id) || [];
  conversations.set(v.vehicle_id, conv);
  res.writeHead(200, { 'content-type': 'application/x-ndjson; charset=utf-8', 'cache-control': 'no-store' });
  const user = { id: `m_${++seq}`, role: 'user', created_at: now(), session_id: s.session_id, text: body.text };
  conv.push(user);
  send(res, { type: 'user', message: user });
  let msg;
  if (/диагност/i.test(body.text)) {
    const steps = await runSteps(res, [['get_diagnosis', 'Получаю результат проверки', 'POST /diagnose → 200'], ['get_vehicle_history', 'Смотрю историю машины', `${v.sessions.length} проверки, заявок ${v.tickets.length}`], ['search_manuals', 'Ищу в руководстве', 'найдено 6 фрагментов'], ['verify', 'Сверяю ссылки со страницами PDF', 'все цитаты найдены']]);
    msg = verdict(v, s, s.status === 'anomaly' ? steps : steps.slice(0, 2));
  } else if (/заявк/i.test(body.text)) {
    if (s.status !== 'anomaly') {
      msg = { id: `m_${++seq}`, role: 'assistant', created_at: now(), session_id: s.session_id, kind: 'notice', text: 'По этой проверке заявка не оформляется: отклонения нет или запись непригодна.', steps: [], usage: usage(1) };
    } else {
      const steps = await runSteps(res, [['search_manuals', 'Ищу порядок работ в руководстве', 'найдено 4 фрагмента'], ['draft_ticket', 'Собираю черновик заявки', 'работ: 2, источников: 2']]);
      msg = draftMsg(v, s, steps);
    }
  } else if (/ошибк/i.test(body.text)) {
    send(res, { type: 'error', text: 'Модель не ответила вовремя. Повторите вопрос.' });
    send(res, { type: 'done', usage: usage(0) });
    return res.end();
  } else {
    const steps = await runSteps(res, [['search_manuals', 'Ищу в руководстве', 'найдено 5 фрагментов'], ['verify', 'Сверяю ссылки со страницами PDF', 'все цитаты найдены']]);
    msg = answerMsg(v, s, body.text, steps);
  }
  conv.push(msg);
  send(res, { type: 'message', message: msg });
  send(res, { type: 'done', usage: msg.usage });
  res.end();
}

async function confirm(req, res, id) {
  const body = await readBody(req);
  const d = drafts.get(id);
  if (!d) return jsonRes(res, 404, { detail: 'Черновик не найден' });
  if (d.status !== 'draft') return jsonRes(res, 409, { detail: 'Заявка уже отправлена' });
  if (d.requires_warning_ack && !body.warning_ack) return jsonRes(res, 422, { detail: 'Нужно подтвердить, что запись с помехами' });
  const v = V.find((x) => x.vehicle_id === d.vehicle_id);
  res.writeHead(200, { 'content-type': 'application/x-ndjson; charset=utf-8', 'cache-control': 'no-store' });
  const steps = await runSteps(res, [['submit_ticket', 'Отправляю заявку в ТОиР', 'POST /tickets → 201']]);
  const ticket = { ticket_id: `TKT-${String(++ticketNo).padStart(4, '0')}`, vehicle_id: d.vehicle_id, session_id: d.session_id, created_at: now(), anomaly_type: d.anomaly_type, conclusion: d.conclusion, urgency: d.urgency, operations: d.operations.map((o) => o.text), spare_parts: d.spare_parts.map((o) => o.text), references: d.references.map((r) => ({ manual: r.manual, pdf_page: r.pdf_page })) };
  d.status = 'sent';
  d.ticket_id = ticket.ticket_id;
  v.tickets.push(ticket);
  const s = v.sessions.find((x) => x.session_id === d.session_id);
  if (s) s.ticket_id = ticket.ticket_id;
  const msg = { id: `m_${++seq}`, role: 'assistant', created_at: now(), session_id: d.session_id, kind: 'ticket_created', text: `Заявка ${ticket.ticket_id} создана.`, ticket, steps, usage: usage(1) };
  conversations.get(v.vehicle_id)?.push(msg);
  send(res, { type: 'message', message: msg });
  send(res, { type: 'done', usage: msg.usage });
  res.end();
}

function pageSvg(manualId, page, q) {
  const lines = Array.from({ length: 16 }, (_, i) => `<rect x="90" y="${210 + i * 34}" width="${700 + ((i * 53) % 260)}" height="12" fill="#d5d0c5"/>`).join('');
  const hl = q ? `<rect x="80" y="780" width="1040" height="120" fill="rgba(255,196,0,.28)" stroke="#e0a100" stroke-width="5"/><text x="100" y="850" font-family="Times New Roman" font-size="30" fill="#23211d">${q.replace(/[<&>]/g, '').slice(0, 64)}</text>` : '';
  return `<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="1700" viewBox="0 0 1200 1700"><rect width="1200" height="1700" fill="#fbfaf5"/><text x="90" y="120" font-family="Times New Roman" font-size="26" font-style="italic" fill="#6b665c">Мок страницы: ${manualId}</text><text x="90" y="180" font-family="Times New Roman" font-weight="bold" font-size="36" fill="#23211d">Раздел руководства, стр. PDF ${page}</text>${lines}${hl}<text x="600" y="1640" text-anchor="middle" font-family="Times New Roman" font-size="26" fill="#4b473f">${page}</text></svg>`;
}

http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://x');
  const p = url.pathname;
  let m;
  if (p === '/api/health') return jsonRes(res, 200, { status: 'ok', ml: true, toir: true, kb: { manuals: 6, pages: 1743, chunks: 0 } });
  if (p === '/api/config') return jsonRes(res, 200, {
    llm: { provider: 'mock', model: 'mock-llm', mock: true }, thresholds: { confidence_min: 0.5 }, priority_actions: ACTIONS,
    languages: [{ code: 'ru', label: 'Русский' }, { code: 'uz', label: 'Oʻzbekcha' }, { code: 'tg', label: 'Тоҷикӣ' }, { code: 'hi', label: 'हिन्दी' }],
    levels: [{ code: 'expert', label: 'Опытный', hint: 'Коротко, только суть' }, { code: 'novice', label: 'Новичок', hint: 'С пояснениями и простыми словами' }],
  });
  if (p === '/api/audit') {
    // Журнал обращений: вопрос механика и следующий за ним ответ агента
    const items = [];
    for (const [vehicleId, list] of conversations) {
      const v = V.find((x) => x.vehicle_id === vehicleId);
      list.forEach((msg, i) => {
        if (msg.role !== 'assistant') return;
        const question = [...list.slice(0, i)].reverse().find((x) => x.role === 'user');
        const refs = [...(msg.answer?.checks || []), ...(msg.answer?.repair || []), ...(msg.draft?.operations || [])].flatMap((it) => it.refs || []);
        const seen = new Set();
        const sources = refs.filter((r) => { const k = r.manual_id + ':' + r.pdf_page; if (seen.has(k)) return false; seen.add(k); return true; })
          .map((r) => ({ manual_id: r.manual_id, short: r.short, pdf_page: r.pdf_page }));
        items.push({
          id: msg.id, created_at: msg.created_at, vehicle_id: vehicleId, vehicle_title: v ? v.title : vehicleId, session_id: msg.session_id,
          question: question ? question.text : '', kind: msg.kind, answer: msg.text || '', sources,
          tools: (msg.steps || []).map((st) => st.tool), ticket_id: msg.ticket ? msg.ticket.ticket_id : null, usage: msg.usage || null,
        });
      });
    }
    items.sort((a, b) => (a.created_at < b.created_at ? 1 : -1));
    const limit = Number(url.searchParams.get('limit') || 100);
    return jsonRes(res, 200, { items: items.slice(0, limit) });
  }
  if (p === '/api/fleet') {
    const order = { quarantine: 0, attention: 1, ok: 2 };
    const list = V.map(brief).sort((a, b) => order[a.fleet_status] - order[b.fleet_status]);
    return jsonRes(res, 200, { summary: { total: 50, ok: 30, attention: 15, quarantine: 5, recheck: 4 }, vehicles: list });
  }
  if ((m = p.match(/^\/api\/vehicles\/([^/]+)$/))) {
    const v = V.find((x) => x.vehicle_id === decodeURIComponent(m[1]));
    return v ? jsonRes(res, 200, detail(v)) : jsonRes(res, 404, { detail: 'Машина не найдена' });
  }
  if ((m = p.match(/^\/api\/conversations\/([^/]+)$/))) {
    const id = decodeURIComponent(m[1]);
    if (req.method === 'DELETE') { conversations.set(id, []); return jsonRes(res, 200, { ok: true }); }
    return jsonRes(res, 200, { messages: conversations.get(id) || [] });
  }
  if (p === '/api/chat' && req.method === 'POST') return chat(req, res);
  if ((m = p.match(/^\/api\/drafts\/([^/]+)\/confirm$/)) && req.method === 'POST') return confirm(req, res, m[1]);
  if ((m = p.match(/^\/api\/drafts\/([^/]+)$/)) && req.method === 'PATCH') {
    const d = drafts.get(m[1]);
    if (!d) return jsonRes(res, 404, { detail: 'Черновик не найден' });
    if (d.status !== 'draft') return jsonRes(res, 409, { detail: 'Заявка уже отправлена' });
    const body = await readBody(req);
    if (typeof body.conclusion === 'string') d.conclusion = body.conclusion;
    if (body.urgency) d.urgency = body.urgency;
    return jsonRes(res, 200, d);
  }
  if ((m = p.match(/^\/api\/manuals\/([^/]+)\/pages\/(\d+)\/image$/))) {
    res.writeHead(200, { 'content-type': 'image/svg+xml; charset=utf-8', 'cache-control': 'no-store' });
    return res.end(pageSvg(m[1], Number(m[2]), url.searchParams.get('q')));
  }
  if ((m = p.match(/^\/api\/manuals\/([^/]+)\/pages\/(\d+)$/))) {
    const all = Object.entries(MANUALS).flatMap(([engine, list]) => list.map((x) => ({ ...x, engine })));
    const man = all.find((x) => x.manual_id === m[1]);
    if (!man) return jsonRes(res, 404, { detail: 'Руководство не найдено' });
    const page = Number(m[2]);
    if (page < 1 || page > man.pages) return jsonRes(res, 404, { detail: 'Такой страницы нет' });
    return jsonRes(res, 200, { manual_id: man.manual_id, designation: man.designation, title: man.title, short: man.short, engine: man.engine, page, page_count: man.pages, image_url: `/api/manuals/${man.manual_id}/pages/${page}/image`, text: `Текст страницы ${page} (мок).` });
  }
  jsonRes(res, 404, { detail: 'Не найдено' });
}).listen(PORT, '127.0.0.1', () => console.log(`mock api: http://127.0.0.1:${PORT}`));
