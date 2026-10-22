/** Russian taxpayer number (INN) checks: 10 digits for a company, 12 for an individual entrepreneur. */
export type InnCheck = { ok: true; kind: 'LEGAL_ENTITY' | 'INDIVIDUAL_ENTREPRENEUR' } | { ok: false; code: 'INN_LENGTH' | 'INN_CHECKSUM' };

const W10 = [2, 4, 10, 3, 5, 9, 4, 6, 8];
const W11 = [7, 2, 4, 10, 3, 5, 9, 4, 6, 8];
const W12 = [3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8];

function control(digits: number[], weights: number[]): number {
  const sum = weights.reduce((acc, w, i) => acc + w * (digits[i] ?? 0), 0);
  return (sum % 11) % 10;
}

export function checkInn(raw: string): InnCheck {
  const value = raw.trim();
  if (!/^\d{10}$|^\d{12}$/.test(value)) return { ok: false, code: 'INN_LENGTH' };
  const d = Array.from(value, Number);
  if (value.length === 10) {
    return control(d, W10) === d[9] ? { ok: true, kind: 'LEGAL_ENTITY' } : { ok: false, code: 'INN_CHECKSUM' };
  }
  return control(d, W11) === d[10] && control(d, W12) === d[11]
    ? { ok: true, kind: 'INDIVIDUAL_ENTREPRENEUR' }
    : { ok: false, code: 'INN_CHECKSUM' };
}

export const INN_MESSAGES = {
  INN_LENGTH: 'ИНН компании состоит из 10 цифр, ИНН ИП из 12 цифр',
  INN_CHECKSUM: 'В ИНН ошибка: проверьте цифры',
} as const;

/** Validation message for a form field, or null when the value is a valid INN. */
export function innError(raw: string): string | null {
  const result = checkInn(raw);
  return result.ok ? null : INN_MESSAGES[result.code];
}
