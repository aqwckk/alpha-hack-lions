const TZ = 'Europe/Moscow';

function toNumber(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined || value === '') return null;
  const n = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(n) ? n : null;
}

const intFormat = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 });
const kopFormat = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** 1 200 000 ₽ or 62 253,79 ₽ (kopecks only when present). */
export function formatMoney(value: string | number | null | undefined, empty = 'не указано'): string {
  const n = toNumber(value);
  if (n === null) return empty;
  const hasKopecks = Math.round(n * 100) % 100 !== 0;
  return `${(hasKopecks ? kopFormat : intFormat).format(n)} ₽`;
}

/** Plain grouped number without currency: 1 200 000. */
export function formatNumber(value: string | number | null | undefined): string {
  const n = toNumber(value);
  return n === null ? '' : intFormat.format(n);
}

/** "22.00" -> 22%, "19.50" -> 19,5%. */
export function formatRate(value: string | number | null | undefined): string {
  const n = toNumber(value);
  if (n === null) return 'не указано';
  return `${new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 }).format(n)}%`;
}

/** Share 0.7073 -> 70,7%. */
export function formatShare(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return 'недостаточно данных';
  return `${new Intl.NumberFormat('ru-RU', { maximumFractionDigits: digits }).format(value * 100)}%`;
}

export function plural(n: number, forms: readonly [string, string, string]): string {
  const a = Math.abs(n) % 100;
  const b = a % 10;
  if (a > 10 && a < 20) return forms[2];
  if (b > 1 && b < 5) return forms[1];
  if (b === 1) return forms[0];
  return forms[2];
}

export function formatTerm(months: number | null | undefined): string {
  if (months === null || months === undefined) return 'не указан';
  return `${months} ${plural(months, ['месяц', 'месяца', 'месяцев'])}`;
}

function toDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  // Plain dates (YYYY-MM-DD) are calendar dates, not instants: keep the day as is.
  const d = /^\d{4}-\d{2}-\d{2}$/.test(value) ? new Date(`${value}T12:00:00Z`) : new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** 23 октября 2026 */
export function formatDate(value: string | null | undefined): string {
  const d = toDate(value);
  if (!d) return 'не указано';
  return new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long', year: 'numeric', timeZone: TZ }).format(d).replace(' г.', '');
}

/** 23 октября, 09:10 */
export function formatDateTime(value: string | null | undefined): string {
  const d = toDate(value);
  if (!d) return 'не указано';
  const date = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long', timeZone: TZ }).format(d);
  return `${date}, ${formatTime(value)}`;
}

/** 23.10.2026 09:10:05 for dense staff tables. */
export function formatStamp(value: string | null | undefined): string {
  const d = toDate(value);
  if (!d) return '';
  return new Intl.DateTimeFormat('ru-RU', {
    day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit', timeZone: TZ,
  }).format(d);
}

export function formatTime(value: string | null | undefined): string {
  const d = toDate(value);
  if (!d) return '';
  return new Intl.DateTimeFormat('ru-RU', { hour: '2-digit', minute: '2-digit', timeZone: TZ }).format(d);
}

/** 3 ч 5 мин, 45 сек */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return 'нет данных';
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s} сек`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} мин${s % 60 ? ` ${s % 60} сек` : ''}`;
  const h = Math.floor(m / 60);
  if (h < 48) return `${h} ч${m % 60 ? ` ${m % 60} мин` : ''}`;
  const days = Math.floor(h / 24);
  return `${days} ${plural(days, ['день', 'дня', 'дней'])}`;
}

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} КБ`;
  return `${(bytes / 1024 / 1024).toFixed(1).replace('.', ',')} МБ`;
}

/** Converts a money string from the API ("1500000.00") to a whole number for inputs. */
export function moneyToNumber(value: string | null | undefined): number | '' {
  const n = toNumber(value);
  return n === null ? '' : n;
}
