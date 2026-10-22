import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { tokenStore } from './client';
import { api } from './endpoints';
import { server } from '@/test/server';

describe('API client session', () => {
  it('refreshes an expired access token once and repeats the request with the new token', async () => {
    tokenStore.set('expired-token');
    const seen: (string | null)[] = [];
    let refreshCalls = 0;
    server.use(
      http.get('*/api/v1/applications', ({ request }) => {
        const auth = request.headers.get('Authorization');
        seen.push(auth);
        return auth === 'Bearer fresh-token'
          ? HttpResponse.json({ items: [], page: 1, page_size: 100, total: 0 })
          : HttpResponse.json({ error: { code: 'TOKEN_INVALID', message: 'Сессия недействительна' } }, { status: 401 });
      }),
      http.post('*/api/v1/auth/refresh', () => {
        refreshCalls += 1;
        return HttpResponse.json({
          access_token: 'fresh-token',
          token_type: 'Bearer',
          expires_in: 1800,
          user: { id: 'u1', login: 'client.demo', role: 'CLIENT', full_name: 'Тестов Т.Т.' },
        });
      }),
    );

    const page = await api.listApplications();

    expect(page.total).toBe(0);
    expect(seen).toEqual(['Bearer expired-token', 'Bearer fresh-token']);
    expect(refreshCalls).toBe(1);
    expect(tokenStore.get()).toBe('fresh-token');
  });
});
