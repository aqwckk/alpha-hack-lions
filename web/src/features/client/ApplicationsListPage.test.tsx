import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { expect, it, vi } from 'vitest';
import { ApplicationsListPage } from './ApplicationsListPage';
import { api } from '@/shared/api/endpoints';
import { renderRoute } from '@/test/render';
import { server } from '@/test/server';

vi.mock('@/features/auth/AuthProvider', () => ({ useUser: () => ({ id: 'u1', login: 'client.test', role: 'CLIENT' }) }));

it('requests server pages and reaches an application beyond the old first-100 limit', async () => {
  vi.spyOn(api, 'meta').mockResolvedValue({ demo_mode: false } as Awaited<ReturnType<typeof api.meta>>);
  const pages: number[] = [];
  server.use(http.get('*/api/v1/applications', ({ request }) => {
    const params = new URL(request.url).searchParams;
    const page = Number(params.get('page'));
    pages.push(page);
    expect(params.get('page_size')).toBe('20');
    return HttpResponse.json({ page, page_size: 20, total: 105, items: [{
      id: `application-${page}`, application_number: page === 6 ? 'A-000105' : 'A-000001', product_name: 'Экспресс-кредит', client_status: 'FILLING', client_status_title: 'Черновик', amount: '1200000', term_months: 24, updated_at: '2026-10-25T12:00:00Z', company_short_name: null,
    }] });
  }));
  renderRoute('/client/applications', '/client/applications', <ApplicationsListPage />);
  expect(await screen.findByText('Заявка A-000001')).toBeInTheDocument();
  await userEvent.setup().click(screen.getByRole('button', { name: '6' }));
  expect(await screen.findByText('Заявка A-000105')).toBeInTheDocument();
  expect(pages).toEqual([1, 6]);
  expect(screen.getByText('Всего заявок: 105')).toBeInTheDocument();
});
