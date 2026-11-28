import type { ReactNode } from 'react';

/**
 * Вертикальные чертежи узлов для фона слайдов обучения: во всю высоту окна, целиком в поле слева от текста.
 * Нарисованы с нуля по общему устройству дизеля, не по рисункам из руководств.
 * Линии цвета текста (currentColor), поэтому подходят и светлой, и тёмной теме.
 */
function Sheet({ className, width, children }: { className?: string; width: number; children: ReactNode }) {
  return (
    <svg className={className} viewBox={`0 0 ${width} 900`} fill="none" stroke="currentColor" aria-hidden="true" focusable="false">
      <defs>
        <marker id="bp-arrow2" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M0 0L10 5L0 10" fill="currentColor" stroke="none" />
        </marker>
      </defs>
      <g className="bp">{children}</g>
    </svg>
  );
}

/** Витки пружины: зигзаг между x1 и x2 от y на n витков высотой h */
const coil = (x1: number, x2: number, y: number, n: number, h: number) =>
  Array.from({ length: n }, (_, i) => `M${x1} ${y + i * h}L${x2} ${y + i * h + h / 2}L${x1} ${y + (i + 1) * h}`).join('');

/** Разрез цилиндра: головка с клапанами и форсункой, гильза в рубашке охлаждения, поршень, шатун, коленвал, поддон */
export function CylinderBlueprint({ className }: { className?: string }) {
  return (
    <Sheet className={className} width={400}>
      <path d="M200 14V886M120 700H280" className="bp-axis" />
      {/* Головка цилиндра и каналы */}
      <path d="M64 70H336V190H64Z" />
      <path d="M64 98Q122 98 140 150V176M64 150Q104 150 120 176" className="bp-thin" />
      <path d="M336 98Q278 98 260 150V176M336 150Q296 150 280 176" className="bp-thin" />
      {/* Клапаны с пружинами и тарелками */}
      <path d="M146 26V176M154 26V176M246 26V176M254 26V176" />
      <path d="M124 190L142 176H158L176 190ZM224 190L242 176H258L276 190Z" />
      <path d={coil(132, 168, 40, 5, 12) + coil(232, 268, 40, 5, 12)} className="bp-thin" />
      <path d="M126 36H174M226 36H274" />
      {/* Форсунка по оси цилиндра */}
      <path d="M193 8V184M207 8V184M195 184L200 196L205 184" />
      <path d="M186 40H214M186 52H214" className="bp-thin" />
      {/* Прокладка, стенки блока, гильза и рубашка охлаждения */}
      <path d="M58 192H342" className="bp-thin" />
      <path d="M72 194V520M328 194V520M108 194V504M292 194V504" />
      <path d="M90 212V486M310 212V486" className="bp-dash" />
      {/* Поршень: камера сгорания в днище, кольца, палец */}
      <path d="M110 252H290V374H110Z" />
      <path d="M156 252Q200 282 244 252" className="bp-thin" />
      <path d="M110 264H290M110 274H290M110 284H290" className="bp-thin" />
      <circle cx="200" cy="332" r="19" />
      <circle cx="200" cy="332" r="9" />
      {/* Шатун к шатунной шейке */}
      <path d="M187 349L219 604M213 349L257 600" />
      <circle cx="238" cy="640" r="40" />
      <circle cx="238" cy="640" r="26" />
      {/* Коленвал: коренная шейка и противовес */}
      <circle cx="200" cy="700" r="32" />
      <circle cx="200" cy="700" r="12" />
      <path d="M128 716A76 76 0 0 0 272 716L244 700M156 700L128 716" />
      {/* Картер и поддон */}
      <path d="M72 520L50 600V782M328 520L350 600V782" />
      <path d="M50 782H350L322 862H78Z" />
      <path d="M94 838H306" className="bp-thin" />
      {/* Размеры: диаметр цилиндра и ход поршня */}
      <path d="M110 230H290" className="bp-thin" markerStart="url(#bp-arrow2)" markerEnd="url(#bp-arrow2)" />
      <text x="200" y="224" className="bp-t" textAnchor="middle">
        Ø 130
      </text>
      <path d="M296 252H384M296 374H384" className="bp-thin" />
      <path d="M376 252V374" className="bp-thin" markerStart="url(#bp-arrow2)" markerEnd="url(#bp-arrow2)" />
      <text x="362" y="318" className="bp-t" textAnchor="end">
        S
      </text>
      <path d="M18 54H48M18 54V70" className="bp-thin" />
      <text x="20" y="46" className="bp-t">
        А-А
      </text>
    </Sheet>
  );
}

/** Поршень с длинным шатуном: кольца, палец, стержень двутаврового сечения, нижняя головка с крышкой и болтами */
export function RodBlueprint({ className }: { className?: string }) {
  return (
    <Sheet className={className} width={360}>
      <path d="M180 30V880M90 180H270M80 690H280" className="bp-axis" />
      {/* Поршень */}
      <path d="M102 70H258V236H102Z" />
      <path d="M140 70Q180 98 220 70" className="bp-thin" />
      <path d="M102 84H258M102 95H258M102 106H258M102 117H258" className="bp-thin" />
      <path d="M116 236V262M244 236V262M116 262H244" className="bp-dash" />
      <circle cx="180" cy="180" r="22" />
      <circle cx="180" cy="180" r="11" />
      {/* Верхняя головка шатуна и стержень */}
      <path d="M160 204Q180 214 200 204" className="bp-thin" />
      <path d="M166 202L152 612M194 202L208 612" />
      <path d="M174 214L168 604M186 214L192 604" className="bp-thin" />
      {/* Нижняя головка: вкладыши, разъём, крышка, болты */}
      <circle cx="180" cy="690" r="78" />
      <circle cx="180" cy="690" r="56" />
      <circle cx="180" cy="690" r="50" className="bp-thin" />
      <path d="M96 690H264" className="bp-thin" />
      <path d="M94 650h20v84h-20zM246 650h20v84h-20z" />
      <path d="M104 640v-12M256 640v-12M104 744v14M256 744v14" className="bp-thin" />
      <path d="M118 770Q180 806 242 770" />
      {/* Диаметр поршня и межцентровое расстояние */}
      <path d="M102 58V40M258 58V40" className="bp-thin" />
      <path d="M102 46H258" className="bp-thin" markerStart="url(#bp-arrow2)" markerEnd="url(#bp-arrow2)" />
      <text x="180" y="38" className="bp-t" textAnchor="middle">
        Ø 130
      </text>
      <path d="M272 180H336M272 690H336" className="bp-thin" />
      <path d="M326 180V690" className="bp-thin" markerStart="url(#bp-arrow2)" markerEnd="url(#bp-arrow2)" />
      <text x="316" y="440" className="bp-t" textAnchor="end">
        L
      </text>
      <path d="M258 100L300 120H340" className="bp-thin" />
      <text x="300" y="114" className="bp-t">
        КОЛЬЦА
      </text>
      <path d="M20 820H50M20 820V836" className="bp-thin" />
      <text x="22" y="812" className="bp-t">
        Б-Б
      </text>
    </Sheet>
  );
}

/** Дизельная форсунка в разрезе: штуцер, корпус с пружиной и штангой, гайка распылителя, игла, струи топлива */
export function InjectorBlueprint({ className }: { className?: string }) {
  return (
    <Sheet className={className} width={300}>
      <path d="M150 20V880" className="bp-axis" />
      {/* Штуцер подвода топлива с резьбой */}
      <path d="M122 40H178V96H122Z" />
      <path d="M122 50H178M122 60H178M122 70H178" className="bp-thin" />
      {/* Корпус и сливной штуцер */}
      <path d="M100 96H200V520H100Z" />
      <path d="M200 120H246V150H200" />
      <path d="M210 135H246" className="bp-thin" />
      {/* Топливный канал */}
      <path d="M128 70V700" className="bp-dash" />
      {/* Пружина, тарелки, регулировочная шайба */}
      <path d="M134 150H166V162H134ZM134 334H166V346H134Z" />
      <path d={coil(132, 168, 162, 12, 14.3)} className="bp-thin" />
      {/* Штанга */}
      <path d="M146 346V600M154 346V600" />
      {/* Гайка распылителя и распылитель */}
      <path d="M106 520H194L184 706H116Z" />
      <path d="M114 600H186" className="bp-thin" />
      <path d="M126 706L150 832L174 706" />
      {/* Игла */}
      <path d="M146 600V790L150 812L154 790V600" className="bp-thin" />
      {/* Струи топлива */}
      <path d="M150 832L102 892M150 832L198 892M150 832L132 896M150 832L168 896" className="bp-dash" />
      {/* Размеры и разрез */}
      <path d="M100 540H62M100 700H62" className="bp-thin" />
      <path d="M72 540V700" className="bp-thin" markerStart="url(#bp-arrow2)" markerEnd="url(#bp-arrow2)" />
      <text x="62" y="626" className="bp-t" textAnchor="end">
        h
      </text>
      <path d="M200 260L240 236H280" className="bp-thin" />
      <text x="244" y="230" className="bp-t">
        ПРУЖИНА
      </text>
      <path d="M20 40H50M20 40V56" className="bp-thin" />
      <text x="22" y="32" className="bp-t">
        В-В
      </text>
    </Sheet>
  );
}
