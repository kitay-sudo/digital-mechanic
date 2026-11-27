'use client';

/**
 * Короткие тихие звуки голосового ввода, без файлов: тон собирается в браузере.
 * Механик в шуме цеха понимает на слух, что запись началась, закончилась и фраза ушла агенту.
 * Первый звук играется по нажатию на микрофон: браузер разрешает звук только после действия человека.
 */
let ctx: AudioContext | null = null;

function audio(): AudioContext | null {
  if (typeof window === 'undefined') return null;
  try {
    const Ctor = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!Ctor) return null;
    ctx ??= new Ctor();
    if (ctx.state === 'suspended') void ctx.resume().catch(() => undefined);
    return ctx;
  } catch {
    return null;
  }
}

/** Ноты подряд: мягкое нарастание и затухание, без щелчков */
function chime(freqs: number[], step = 0.085, volume = 0.06): void {
  const a = audio();
  if (!a) return;
  const t0 = a.currentTime + 0.01;
  freqs.forEach((f, i) => {
    const osc = a.createOscillator();
    const gain = a.createGain();
    osc.type = 'sine';
    osc.frequency.value = f;
    const s = t0 + i * step;
    gain.gain.setValueAtTime(0, s);
    gain.gain.linearRampToValueAtTime(volume, s + 0.012);
    gain.gain.exponentialRampToValueAtTime(0.0001, s + step + 0.14);
    osc.connect(gain);
    gain.connect(a.destination);
    osc.start(s);
    osc.stop(s + step + 0.16);
  });
}

export const sounds = {
  /** Запись началась: два тона вверх */
  start: () => chime([660, 990]),
  /** Запись закончена, ушла на распознавание: два тона вниз */
  stop: () => chime([990, 660]),
  /** Фраза ушла агенту: короткий высокий тон */
  sent: () => chime([1320], 0.07, 0.045),
  /** Запись отменена: один низкий тон */
  cancel: () => chime([440], 0.08, 0.045),
};
