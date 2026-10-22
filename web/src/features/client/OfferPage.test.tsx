import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { OfferPage } from './OfferPage';
import { makeApp, makeOption } from '@/test/fixtures';
import { renderRoute } from '@/test/render';
import { server } from '@/test/server';

describe('OfferPage', () => {
  it('preselects the recommended option and accepts it with version and a fresh Idempotency-Key', async () => {
    const reduced = makeOption();
    const extended = makeOption({
      id: '33333333-3333-4333-8333-333333333333',
      option_type: 'TERM_EXTENDED',
      amount: '15000000.00',
      term_months: 13,
      monthly_payment: '1285745.92',
      recommended: true,
      difference_text: 'на 1 месяц дольше',
    });
    const app = makeApp({
      client_status: 'DECISION_READY',
      version: 11,
      available_actions: ['ACCEPT_OFFER', 'DECLINE_OFFER', 'WITHDRAW'],
      offer: {
        id: 'o1',
        outcome: 'COUNTER_OFFER',
        status: 'ACTIVE',
        expires_at: '2026-10-30T15:00:00Z',
        expires_text: '30 октября, 18:00',
        selected_option_id: null,
        requested: { amount: '15000000.00', term_months: 12, monthly_payment: '1382348.67' },
        reasons: [{ text: 'Ежемесячный платеж больше, чем бизнес может платить.', next_step: null }],
        options: [reduced, extended],
      },
    });
    const accepted: { body: unknown; key: string | null }[] = [];
    server.use(
      http.get(`*/api/v1/applications/${app.id}`, () => HttpResponse.json(app)),
      http.get('*/api/v1/catalog/dictionaries', () => HttpResponse.json({ purposes: [], document_types: [], consents: [], offer_decline_reasons: [], representative_roles: [], collateral_types: [], collateral_owners: [] })),
      http.post(`*/api/v1/applications/${app.id}/offer/accept`, async ({ request }) => {
        accepted.push({ body: await request.json(), key: request.headers.get('Idempotency-Key') });
        return HttpResponse.json(makeApp({ client_status: 'DOCUMENTS', version: 12 }));
      }),
    );
    const user = userEvent.setup();
    renderRoute('/client/applications/:id/offer', `/client/applications/${app.id}/offer`, <OfferPage />);

    const recommendedCard = await screen.findByRole('article', { name: 'Дольше срок' });
    expect(within(recommendedCard).getByText('Рекомендуем')).toBeInTheDocument();
    expect(within(recommendedCard).getByText('на 1 месяц дольше')).toBeInTheDocument();
    expect(within(recommendedCard).getByRole('button', { name: 'Выбран' })).toHaveAttribute('aria-pressed', 'true');
    expect(within(screen.getByRole('article', { name: 'Меньше сумма' })).queryByText('Рекомендуем')).not.toBeInTheDocument();

    await user.click(screen.getAllByRole('button', { name: 'Выбрать этот вариант' }).at(-1) as HTMLElement);
    await user.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Подтверждаю' }));

    await waitFor(() => expect(accepted).toHaveLength(1));
    expect(accepted[0]?.body).toEqual({ expected_version: 11, option_id: extended.id });
    expect(accepted[0]?.key).toMatch(/^[0-9a-f-]{36}$/);
  });
});
