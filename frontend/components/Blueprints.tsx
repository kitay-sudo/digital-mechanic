import type { ReactNode } from 'react';

/**
 * Ещё два чертежа в том же стиле, что и двигатель (Blueprint.tsx): фон слайдов обучения.
 * Нарисованы с нуля по общему устройству узлов, не по рисункам из руководств.
 * Линии цвета текста (currentColor), поэтому подходят и светлой, и тёмной теме.
 */
function Sheet({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <svg className={className} viewBox="0 0 600 410" fill="none" stroke="currentColor" aria-hidden="true" focusable="false">
      <defs>
        <marker id="bp-arrow2" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M0 0L10 5L0 10" fill="currentColor" stroke="none" />
        </marker>
      </defs>
      <g className="bp">{children}</g>
    </svg>
  );
}

/** Поршень с шатуном, вид сбоку: кольца, палец, стержень шатуна, нижняя головка с крышкой и болтами */
export function PistonBlueprint({ className }: { className?: string }) {
  return (
    <Sheet className={className}>
      {/* Осевые линии */}
      <path d="M300 22V400M200 138H400M220 322H380" className="bp-axis" />
      {/* Поршень: днище с камерой сгорания, канавки колец, юбка */}
      <path d="M232 62H368V178H232Z" />
      <path d="M262 62Q300 84 338 62" className="bp-thin" />
      <path d="M232 76H368M232 86H368M232 96H368M232 106H368" className="bp-thin" />
      <path d="M246 178V200M354 178V200M246 200H354" className="bp-dash" />
      {/* Поршневой палец */}
      <circle cx="300" cy="138" r="17" />
      <circle cx="300" cy="138" r="8" />
      {/* Шатун: стержень двутаврового сечения расширяется к нижней головке */}
      <path d="M287 154L276 286M313 154L324 286" />
      <path d="M295 160L291 280M305 160L309 280" className="bp-thin" />
      {/* Нижняя головка: вкладыши, разъём, крышка и болты */}
      <circle cx="300" cy="322" r="52" />
      <circle cx="300" cy="322" r="38" />
      <circle cx="300" cy="322" r="34" className="bp-thin" />
      <path d="M240 322H360" className="bp-thin" />
      <path d="M236 300h14v46h-14zM350 300h14v46h-14z" />
      <path d="M243 296v-10M357 296v-10M243 350v10M357 350v10" className="bp-thin" />
      {/* Диаметр цилиндра */}
      <path d="M232 52V36M368 52V36" className="bp-thin" />
      <path d="M232 42H368" className="bp-thin" markerStart="url(#bp-arrow2)" markerEnd="url(#bp-arrow2)" />
      <text x="300" y="34" className="bp-t" textAnchor="middle">
        Ø 130
      </text>
      {/* Межцентровое расстояние */}
      <path d="M404 138H436M404 322H436" className="bp-thin" />
      <path d="M428 138V322" className="bp-thin" markerStart="url(#bp-arrow2)" markerEnd="url(#bp-arrow2)" />
      <text x="440" y="234" className="bp-t">
        L
      </text>
      {/* Выноска к кольцам и разрез */}
      <path d="M368 86L420 70H470" className="bp-thin" />
      <text x="424" y="64" className="bp-t">
        3 КОЛЬЦА
      </text>
      <path d="M150 300H180M150 300V316" className="bp-thin" />
      <text x="152" y="294" className="bp-t">
        Б-Б
      </text>
    </Sheet>
  );
}

/** Клапанный механизм: кулачок, толкатель, штанга, коромысло, клапан с пружиной и седлом; зазор у носка коромысла */
export function ValveBlueprint({ className }: { className?: string }) {
  // Витки пружины вокруг стержня клапана
  const coils = Array.from({ length: 7 }, (_, i) => {
    const y = 168 + i * 13;
    return `M352 ${y}L408 ${y + 6.5}L352 ${y + 13}`;
  }).join('');
  return (
    <Sheet className={className}>
      {/* Осевые линии */}
      <path d="M380 40V396M150 40V396M110 352H200" className="bp-axis" />
      {/* Головка цилиндра: стенки, седло клапана */}
      <path d="M300 250H460M300 250V340M460 250V340" />
      <path d="M300 340H350M410 340H460" />
      <path d="M350 340L362 326H398L410 340" className="bp-thin" />
      {/* Клапан: тарелка и стержень */}
      <path d="M346 352L362 338H398L414 352Z" />
      <path d="M375 338V120M385 338V120" />
      {/* Пружина и тарелка пружины с сухарями */}
      <path d={coils} className="bp-thin" />
      <path d="M344 150H416V162H344Z" />
      <path d="M368 150L372 140H388L392 150" className="bp-thin" />
      {/* Коромысло на оси, носок над стержнем клапана */}
      <path d="M150 104L372 92L374 108L152 120Z" />
      <circle cx="262" cy="104" r="12" />
      <circle cx="262" cy="104" r="5" />
      <path d="M368 108Q380 114 392 108" className="bp-thin" />
      {/* Штанга и толкатель */}
      <path d="M146 120V304M154 120V304" />
      <path d="M134 304H166V334H134Z" />
      {/* Распределительный вал: кулачок */}
      <circle cx="150" cy="370" r="22" />
      <path d="M128 366Q150 322 172 366" />
      <circle cx="150" cy="370" r="5" />
      {/* Тепловой зазор между носком коромысла и стержнем клапана */}
      <path d="M392 114L452 84H500" className="bp-thin" />
      <text x="456" y="78" className="bp-t">
        ЗАЗОР 0,25
      </text>
      {/* Ход клапана */}
      <path d="M470 326V356" className="bp-thin" markerStart="url(#bp-arrow2)" markerEnd="url(#bp-arrow2)" />
      <path d="M414 352H478M410 326H478" className="bp-thin" />
      <text x="484" y="345" className="bp-t">
        h
      </text>
      <path d="M520 220H550M520 220V236" className="bp-thin" />
      <text x="522" y="214" className="bp-t">
        В-В
      </text>
    </Sheet>
  );
}
