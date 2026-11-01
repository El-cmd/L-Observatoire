import type {AttachmentRef, LibraryItem} from '../types';
/** Long side sent to the server: enough to read text, about 1 900 Qwen tokens at most. */
const MAX_SIDE = 1600;
const MAX_PNG = 2.5 * 1024 * 1024;
/** Images and documents together. */
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

/** Documents read by the server; images are any image/* file. */
export const DOCUMENT_TYPES = '.pdf,.docx,.txt,.md,.markdown,.csv,.tsv,.json,.xml,.yaml,.yml,.toml,.ini,.log,.srt,.tex,.html,.py,.js,.ts,.tsx,.jsx,.rs,.go,.java,.c,.h,.cpp,.cs,.php,.rb,.sh,.sql,.css,.scss';
export const isImage = (file: File) => file.type.startsWith('image/');
export const isDocument = (ref: AttachmentRef) => ref.kind === 'document';

export function toRef(item: LibraryItem): AttachmentRef {
  return item.kind === 'document' ? {id:item.id, name:item.name, width:0, height:0, kind:'document', pages:item.pages, tokens:item.tokens}
    : {id:item.id, name:item.name, width:item.width, height:item.height};
}

/** « 12 pages », or the kind of file for Word and text files. */
export function documentSize(ref: AttachmentRef): string {
  if (ref.pages) return `${ref.pages} page${ref.pages > 1 ? 's' : ''}`;
  return /\.docx$/i.test(ref.name) ? 'Word' : 'Texte';
}

/** What the reading of a document found, in plain words. */
export function readingSummary(item: LibraryItem): string {
  const parts = [documentSize(toRef(item))];
  if (item.scanned) parts.push(`${item.scanned} lue${item.scanned > 1 ? 's' : ''} sur l’image`);
  if (item.doubts) parts.push(`${item.doubts} passage${item.doubts > 1 ? 's' : ''} incertain${item.doubts > 1 ? 's' : ''}`);
  return parts.join(' · ');
}
