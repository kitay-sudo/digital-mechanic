/**
 * Чертёж V-образного дизеля, вид спереди: блок с двумя рядами цилиндров под 90°, головки и крышки клапанов,
 * шкивы коленвала, вентилятора и генератора с ремнями, поддон, размерные линии. Штампа нет: надписи в нём лишние.
 * Нарисован с нуля, по общему устройству двигателя, а не по рисунку из руководства.
 * Линии цвета текста (currentColor): чертёж сам подстраивается под светлую и тёмную тему.
 */
export function Blueprint({ className, grid = false }: { className?: string; grid?: boolean }) {
  const bank = (angle: number) => (
    <g transform={`rotate(${angle} 300 290)`}>
      {/* Ряд цилиндров: стенки блока, головка, крышка клапанов */}
      <rect x="255" y="122" width="90" height="128" />
      <rect x="248" y="97" width="104" height="25" />
      <rect x="258" y="74" width="84" height="23" rx="6" />
      <path d="M268 84h64M268 89h64" className="bp-thin" />
      {/* Цилиндр и поршень */}
      <path d="M270 128v114M330 128v114" className="bp-dash" />
      <rect x="273" y="180" width="54" height="30" />
      <path d="M273 188h54M273 194h54" className="bp-thin" />
      <path d="M300 195V286" className="bp-dash" />
      {/* Форсунка и болты головки */}
      <path d="M300 97v-14M296 83h8" />
      <circle cx="262" cy="109" r="3" />
      <circle cx="338" cy="109" r="3" />
    </g>
  );

  return (
    <svg className={className} viewBox="0 0 600 410" fill="none" stroke="currentColor" aria-hidden="true" focusable="false">
      <defs>
        <pattern id="bp-grid" width="20" height="20" patternUnits="userSpaceOnUse">
          <path d="M20 0H0V20" className="bp-grid" />
        </pattern>
        <marker id="bp-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M0 0L10 5L0 10" fill="currentColor" stroke="none" />
        </marker>
      </defs>
      {grid ? <rect x="0" y="0" width="600" height="410" fill="url(#bp-grid)" stroke="none" /> : null}

      <g className="bp">
        {/* Осевые линии */}
        <path d="M300 30V400M170 290H440" className="bp-axis" />

        {bank(-45)}
        {bank(45)}

        {/* Картер и поддон */}
        <path d="M212 250H388L378 330H222Z" />
        <path d="M226 330H374L364 372H236Z" />
        <path d="M244 352H356" className="bp-thin" />
        <circle cx="300" cy="366" r="3" />

        {/* Впускной коллектор между рядами */}
        <path d="M284 150h32v26h-32z" />
        <path d="M290 150v-10h20v10" />

        {/* Шкив вентилятора и водяного насоса, круг вентилятора */}
        <circle cx="300" cy="168" r="30" />
        <circle cx="300" cy="168" r="9" />
        <circle cx="300" cy="168" r="96" className="bp-dash" />

        {/* Шкив коленвала */}
        <circle cx="300" cy="290" r="40" />
        <circle cx="300" cy="290" r="32" />
        <circle cx="300" cy="290" r="11" />

        {/* Генератор с ребрами */}
        <circle cx="438" cy="206" r="34" />
        <circle cx="438" cy="206" r="13" />
        <path d="M414 182l48 48M414 230l48-48" className="bp-thin" />
        <path d="M404 206h-14M472 206h14" />

        {/* Ремни */}
        <path d="M260 292L270 170M340 292L330 170" />
        <path d="M335 309L452 237M326 258L414 182" />

        {/* Угол развала */}
        <path d="M257.6 247.6A60 60 0 0 1 342.4 247.6" className="bp-thin" markerStart="url(#bp-arrow)" markerEnd="url(#bp-arrow)" />
        <text x="300" y="236" className="bp-t" textAnchor="middle">
          90°
        </text>

        {/* Размер по поддону */}
        <path d="M222 336V396M378 336V396" className="bp-thin" />
        <path d="M222 390H378" className="bp-thin" markerStart="url(#bp-arrow)" markerEnd="url(#bp-arrow)" />
        <text x="300" y="384" className="bp-t" textAnchor="middle">
          1010
        </text>

        {/* Выноска к шкиву */}
        <path d="M328 318L392 352H446" className="bp-thin" />
        <text x="398" y="347" className="bp-t">
          Ø 210
        </text>

        {/* Разрез */}
        <path d="M120 60H150M120 60V76" className="bp-thin" />
        <text x="122" y="54" className="bp-t">
          А-А
        </text>
      </g>
    </svg>
  );
}
