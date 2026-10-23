/**
 * Image URLs come from two places:
 *
 *   - a link the owner pasted (https://some-host/photo.jpg), stored as-is;
 *   - an upload, which the backend stores under /uploads/<name> and returns as
 *     a backend-relative path.
 *
 * Uploads are kept relative so the stored records do not pin a hostname; they
 * are resolved against the configured backend URL when rendered.
 */

export const BACKEND_URL = (process.env.REACT_APP_BACKEND_URL || '').replace(/\/+$/, '');

export const API_BASE = `${BACKEND_URL}/api`;

export const imageSrc = (url) => {
  if (!url) return '';
  if (/^(https?:|data:|blob:)/i.test(url)) return url;
  return `${BACKEND_URL}${url.startsWith('/') ? '' : '/'}${url}`;
};

export default imageSrc;
