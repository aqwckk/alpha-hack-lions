import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { ApplicationPage } from './ApplicationPage';
import { makeApp } from '@/test/fixtures';
import { renderRoute } from '@/test/render';
import { server } from '@/test/server';

const APP = makeApp();
const URL_APP = `*/api/v1/applications/${APP.id}`;

describe('ApplicationPage', () => {
  it('builds action buttons only from available_actions', async () => {
    server.use(http.get(URL_APP, () => HttpResponse.json(makeApp({ client_status: 'DECISION_READY', available_actions: [] }))));
    const first = renderRoute('/client/applications/:id', `/client/applications/${APP.id}`, <ApplicationPage />);
    expect(await screen.findByRole('heading', { name: 'Заявку рассматривает специалист' })).toBeInTheDocument();
    // status is DECISION_READY, but without ACCEPT_OFFER / WITHDRAW there must be no buttons for them
    expect(screen.queryByRole('link', { name: 'Посмотреть решение' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Отменить заявку' })).not.toBeInTheDocument();
    first.unmount();

    server.use(http.get(URL_APP, () => HttpResponse.json(makeApp({ client_status: 'DECISION_READY', available_actions: ['ACCEPT_OFFER', 'WITHDRAW'] }))));
    renderRoute('/client/applications/:id', `/client/applications/${APP.id}`, <ApplicationPage />);
    expect(await screen.findByRole('link', { name: /Посмотреть решение/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Отменить заявку' })).toBeInTheDocument();
  });

  it('on 409 VERSION_CONFLICT re-reads the application and explains what happened', async () => {
    let reads = 0;
    let withdrawBody: unknown = null;
    let withdrawKey: string | null = null;
    server.use(
      http.get(URL_APP, () => {
        reads += 1;
        return HttpResponse.json(makeApp({ version: reads === 1 ? 7 : 8, available_actions: ['WITHDRAW'] }));
      }),
      http.post(`${URL_APP}/withdraw`, async ({ request }) => {
        withdrawBody = await request.json();
        withdrawKey = request.headers.get('Idempotency-Key');
        return HttpResponse.json(
          { error: { code: 'VERSION_CONFLICT', message: 'Заявка изменилась, обновите данные', request_id: 'r1', details: { current_version: 8 } } },
          { status: 409 },
        );
      }),
    );
    const user = userEvent.setup();
    renderRoute('/client/applications/:id', `/client/applications/${APP.id}`, <ApplicationPage />);
    await user.click(await screen.findByRole('button', { name: 'Отменить заявку' }));
    const dialog = await screen.findByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: 'Отменить заявку' }));

    await waitFor(() => expect(reads).toBe(2));
    expect(withdrawBody).toEqual({ expected_version: 7 });
    expect(withdrawKey).toMatch(/^[0-9a-f-]{36}$/);
    expect(await screen.findByText(/Заявка изменилась, мы обновили данные/)).toBeInTheDocument();
  });
});
