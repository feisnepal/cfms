/**
 * Make a phone photo small enough to send from the forest: at most `maxSide` pixels on the long side, as a JPEG. A phone camera gives 4 to 12 MB; over a weak signal
 * that is the difference between a photo that arrives and one that does not. When the browser cannot do it (no canvas, an unreadable image) the original is sent
 * unchanged; the server accepts it up to its own limit.
 */
export const shrinkImage = async (file: File, maxSide = 1600, quality = 0.82): Promise<Blob> => {
  try {
    if (typeof createImageBitmap !== 'function' || typeof document === 'undefined') return file;
    const bmp = await createImageBitmap(file);
    const scale = Math.min(1, maxSide / Math.max(bmp.width, bmp.height));
    if (scale === 1 && file.size <= 1_500_000) { bmp.close?.(); return file; }   // already small
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(bmp.width * scale));
    canvas.height = Math.max(1, Math.round(bmp.height * scale));
    const ctx = canvas.getContext('2d');
    if (!ctx) { bmp.close?.(); return file; }
    ctx.drawImage(bmp, 0, 0, canvas.width, canvas.height);
    bmp.close?.();
    const out = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/jpeg', quality));
    return out && out.size < file.size ? out : file;
  } catch {
    return file;   // the original goes as it is: shrinking is only a courtesy to the connection
  }
};
