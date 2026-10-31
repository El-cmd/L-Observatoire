/** Long side sent to the server: enough to read text, about 1 900 Qwen tokens at most. */
const MAX_SIDE = 1600;
const MAX_PNG = 2.5 * 1024 * 1024;
export const MAX_IMAGES = 5;

/**
 * Decodes the image in the browser's own sandbox, scales it down and re-encodes it: EXIF data
 * (GPS position included) never leaves the device. The server checks and re-encodes it again.
 */
export async function prepareImage(file: File): Promise<Blob> {
  if (!file.type.startsWith('image/') || file.type === 'image/svg+xml') throw new Error(`« ${file.name} » n’est pas une image acceptée (SVG compris).`);
  let bitmap: ImageBitmap;
  try { bitmap = await createImageBitmap(file); }
  catch { throw new Error(`« ${file.name} » : format non lu par ce navigateur. Exporte-la en JPEG ou en PNG.`); }
  const scale = Math.min(1, MAX_SIDE / Math.max(bitmap.width, bitmap.height));
  const width = Math.max(1, Math.round(bitmap.width * scale)), height = Math.max(1, Math.round(bitmap.height * scale));
  const canvas = document.createElement('canvas'); canvas.width = width; canvas.height = height;
  const context = canvas.getContext('2d');
  if (!context) {bitmap.close(); throw new Error('Le navigateur ne peut pas préparer cette image.');}
  context.fillStyle = '#fff'; context.fillRect(0, 0, width, height);
  context.drawImage(bitmap, 0, 0, width, height); bitmap.close();
  const encode = (type: string, quality?: number) => new Promise<Blob | null>(resolve => canvas.toBlob(resolve, type, quality));
  // Screenshots stay PNG while they are light, so that small text remains sharp.
  if (file.type === 'image/png') {
    const png = await encode('image/png');
    if (png && png.size <= MAX_PNG) return png;
  }
  const jpeg = await encode('image/jpeg', 0.9);
  if (!jpeg) throw new Error('Le navigateur ne peut pas préparer cette image.');
  return jpeg;
}

export const imageURL = (id: string) => `/api/attachments/${id}`;
export const thumbnailURL = (id: string) => `/api/attachments/${id}/thumbnail`;

export function formatBytes(value: number): string {
  if (value < 1024 * 1024) return `${Math.max(1, Math.round(value / 1024)).toLocaleString('fr-FR')} Ko`;
  return `${(value / 1024 / 1024).toLocaleString('fr-FR', {maximumFractionDigits: 1})} Mo`;
}
