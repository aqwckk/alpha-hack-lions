import type { ClientApplication } from '@/shared/api/types';
import type { FormStep } from '@/shared/lib/labels';
import { moneyToNumber } from '@/shared/lib/format';

/** Editable draft fields (INN is saved by the prefill command, consents and documents by their own commands). */
export interface DraftValues {
  purpose: string;
  amount: number | '';
  term_months: number | '';
  representative_role: string;
  monthly_revenue_declared: number | '';
  existing_monthly_payments_declared: number | '';
  owner_guarantee_agreed: boolean;
  collateral_type: string;
  collateral_description: string;
  collateral_value: number | '';
  collateral_owner: string;
  investment_project_description: string;
  own_contribution_amount: number | '';
  client_comment: string;
}

export type DraftField = keyof DraftValues;

const MONEY: DraftField[] = ['amount', 'monthly_revenue_declared', 'existing_monthly_payments_declared', 'collateral_value', 'own_contribution_amount'];
const TEXT: DraftField[] = [
  'purpose',
  'representative_role',
  'collateral_type',
  'collateral_description',
  'collateral_owner',
  'investment_project_description',
  'client_comment',
];

export const DRAFT_FIELDS: DraftField[] = [...MONEY, 'term_months', 'owner_guarantee_agreed', ...TEXT];

export const STEPS: { key: FormStep; title: string; short: string }[] = [
  { key: 'company', title: 'Компания', short: 'Компания' },
  { key: 'terms', title: 'Условия и финансы', short: 'Условия' },
  { key: 'documents', title: 'Документы', short: 'Документы' },
  { key: 'review', title: 'Проверка и отправка', short: 'Отправка' },
];

export function isStep(value: string | undefined): value is FormStep {
  return STEPS.some((s) => s.key === value);
}

function str(v: unknown): string {
  return typeof v === 'string' ? v : '';
}

export function valuesFromServer(form: Record<string, unknown>): DraftValues {
  const money = (k: string) => moneyToNumber(typeof form[k] === 'string' ? (form[k] as string) : null);
  return {
    purpose: str(form.purpose),
    amount: money('amount'),
    term_months: typeof form.term_months === 'number' ? form.term_months : '',
    representative_role: str(form.representative_role),
    monthly_revenue_declared: money('monthly_revenue_declared'),
    existing_monthly_payments_declared: money('existing_monthly_payments_declared'),
    owner_guarantee_agreed: form.owner_guarantee_agreed === true,
    collateral_type: str(form.collateral_type),
    collateral_description: str(form.collateral_description),
    collateral_value: money('collateral_value'),
    collateral_owner: str(form.collateral_owner),
    investment_project_description: str(form.investment_project_description),
    own_contribution_amount: money('own_contribution_amount'),
    client_comment: str(form.client_comment),
  };
}

export type PatchValue = string | number | boolean | null;

/** Value as sent in PATCH: money as a whole-ruble string, empty as null (clears the field). */
export function toPatchValue(field: DraftField, value: DraftValues[DraftField]): PatchValue {
  if (field === 'owner_guarantee_agreed') return value === true;
  if (field === 'term_months') return typeof value === 'number' && value > 0 ? value : null;
  if (MONEY.includes(field)) return typeof value === 'number' && Number.isFinite(value) ? String(Math.round(value)) : null;
  const text = typeof value === 'string' ? value.trim() : '';
  return text === '' ? null : text;
}

export function snapshot(values: DraftValues): Record<DraftField, PatchValue> {
  const out = {} as Record<DraftField, PatchValue>;
  for (const f of DRAFT_FIELDS) out[f] = toPatchValue(f, values[f]);
  return out;
}

/** The step a returning client continues from: the first one with something missing. */
export function resumeStep(app: ClientApplication): FormStep {
  const f = app.form as Record<string, unknown>;
  if (app.inn_check_status !== 'FOUND' || !f.representative_role) return 'company';
  if (f.monthly_revenue_declared == null || f.existing_monthly_payments_declared == null) return 'terms';
  if (app.required_documents.some((d) => !d.uploaded)) return 'documents';
  return 'review';
}
