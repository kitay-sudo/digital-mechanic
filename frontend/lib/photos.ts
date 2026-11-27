/**
 * Фото узла от механика. Снимок с телефона весит мегабайты: перед отправкой он уменьшается
 * до 1568 px по длинной стороне (больше модель всё равно не разглядит) и сжимается в JPEG.
 */
export const MAX_PHOTOS = 3;
const MAX_SIDE = 1568;
const QUALITY = 0.85;

function loadImage(file: File): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(url);
      resolve(img);
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error('Не получилось открыть фото. Сфотографируйте ещё раз или выберите другой снимок.'));
    };
    img.src = url;
  });
}

/** Готовит снимок к отправке: data URL уменьшенного JPEG */
export async function photoFromFile(file: File): Promise<string> {
  if (!file.type.startsWith('image/')) throw new Error('Приложить можно только фото.');
  let source: ImageBitmap | HTMLImageElement;
  try {
    // Поворот по данным камеры (EXIF), иначе снимок с телефона может лечь боком
    source = await createImageBitmap(file, { imageOrientation: 'from-image' });
  } catch {
    source = await loadImage(file);
  }
  const width = source.width;
  const height = source.height;
  const scale = Math.min(1, MAX_SIDE / Math.max(width, height));
  const canvas = document.createElement('canvas');
  canvas.width = Math.max(1, Math.round(width * scale));
  canvas.height = Math.max(1, Math.round(height * scale));
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('Браузер не смог подготовить фото.');
  ctx.drawImage(source, 0, 0, canvas.width, canvas.height);
  if ('close' in source) source.close();
  return canvas.toDataURL('image/jpeg', QUALITY);
}
