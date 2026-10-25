import { fireEvent, screen, waitFor } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { WizardResultsPage } from './WizardResultsPage';
import { api } from '@/shared/api/endpoints';
import type { ProductCard } from '@/shared/api/types';
import { renderRoute } from '@/test/render';

vi.mock('@/features/auth/AuthProvider', () => ({ useUser: () => ({ id: 'u1' }) }));
vi.mock('react-router-dom', async (original) => ({
  ...await original<typeof import('react-router-dom')>(),
  useLocation: () => ({ state: { request: { purpose: 'EQUIPMENT', amount: 1200000, term_months: 24, applicant_type: 'ANY', inn: '' }, wizardId: 'w1' } }),
}));

it('explains recommendation and blocks calculation and applying for amounts outside the product step', async () => {
  sessionStorage.clear();
  const card: ProductCard = { product_code: 'EXPRESS', name: 'Экспресс-кредит', description: 'Для бизнеса', decision_speed: 'Несколько минут', review_mode: 'AUTO', rate_from_percent: '24', term_months: 24, term_note: null, monthly_payment_from: '63445.32', total_payment_from: '1522687.68', overpayment_from: '322687.68', amount_min: '100000', amount_max: '5000000', amount_step: '100000', term_min_months: 6, term_max_months: 36, requirements: [], required_documents: [], available: true, unavailable_reason: null, eligible_date: null, recommended: true, rank: 1 };
  vi.spyOn(api, 'dictionaries').mockResolvedValue({ purposes: [], document_types: [], consents: [], offer_decline_reasons: [], representative_roles: [], collateral_types: [], collateral_owners: [] });
  vi.spyOn(api, 'match').mockResolvedValue({ cards: [card], hints: [], disclaimer: 'Предварительный расчет', empty_text: null } as Awaited<ReturnType<typeof api.match>>);
  const calculate = vi.spyOn(api, 'calculate').mockResolvedValue({ monthly_payment: '65000', overpayment: '260000' } as Awaited<ReturnType<typeof api.calculate>>);
  renderRoute('/client/wizard/results', '/client/wizard/results', <WizardResultsPage />);
  const amount = await screen.findByLabelText('Сумма');
  expect(screen.getByText(/Рекомендация учитывает скорость решения/)).toBeInTheDocument();
  fireEvent.change(amount, { target: { value: '1200001' } });
  expect(screen.getByRole('button', { name: 'Оформить' })).toBeDisabled();
  expect(await screen.findByText(/Укажите сумму от/)).toBeInTheDocument();
  // Wait past debounce to ensure the invalid amount was never calculated.
  await new Promise((resolve) => setTimeout(resolve, 350));
  expect(calculate).not.toHaveBeenCalled();
  fireEvent.change(amount, { target: { value: '1300000' } });
  expect(screen.getByRole('button', { name: 'Оформить' })).toBeEnabled();
  await waitFor(() => expect(calculate).toHaveBeenCalledWith({ product_code: 'EXPRESS', amount: '1300000', term_months: 24 }));
});
