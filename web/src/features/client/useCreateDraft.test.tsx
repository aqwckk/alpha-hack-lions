import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook } from '@testing-library/react';
import type { ReactNode } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useCreateDraft } from './useCreateDraft';
import { api } from '@/shared/api/endpoints';
import { ApiError, networkError } from '@/shared/api/errors';
import { readSessionDraft } from '@/shared/lib/sessionDrafts';
import { toast } from '@/shared/ui/toast';
import { makeApp } from '@/test/fixtures';

const body = { product_code: 'EXPRESS', purpose: 'EQUIPMENT', amount: '1200000', term_months: 24, wizard_session_id: 'wizard-1' };
function setup(userId = 'u1') {
  const queryClient = new QueryClient();
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={queryClient}><MemoryRouter>{children}</MemoryRouter></QueryClientProvider>;
  return renderHook(() => useCreateDraft(userId), { wrapper });
}

beforeEach(() => {
  sessionStorage.clear();
  vi.spyOn(toast, 'error').mockImplementation(() => undefined);
});

describe('draft creation recovery', () => {
  it('reuses key/payload for automatic retries and recovers the same intent after remount despite changed inputs', async () => {
    vi.useFakeTimers();
    try {
      const create = vi.spyOn(api, 'createApplication').mockRejectedValue(networkError());
      const first = setup();
      act(() => {
        expect(first.result.current.start(body)).toBe(true);
        expect(first.result.current.start({ ...body, amount: '9000000' })).toBe(false);
      });
      await act(async () => { await vi.advanceTimersByTimeAsync(3001); });
      expect(first.result.current.isPending).toBe(false);
      expect(create).toHaveBeenCalledTimes(3);
      const original = create.mock.calls[0];
      expect(original?.[0]).toEqual(body);
      expect(original?.[1]).toMatch(/^[0-9a-f-]{36}$/);
      expect(create.mock.calls).toEqual([original, original, original]);
      expect(readSessionDraft('create:u1')).toMatchObject({ body, key: original?.[1] });
      first.unmount();

      const otherUser = setup('u2');
      expect(otherUser.result.current.pending).toBeNull();
      otherUser.unmount();
      const recovered = setup();
      expect(recovered.result.current.pending?.body).toEqual(body);
      create.mockResolvedValue(makeApp({ client_status: 'FILLING' }));
      act(() => { recovered.result.current.start({ ...body, amount: '9000000', term_months: 36 }); });
      await act(async () => { await vi.advanceTimersByTimeAsync(1); });
      expect(create).toHaveBeenCalledTimes(4);
      expect(create.mock.calls[3]).toEqual(original);
      expect(recovered.result.current.pending).toBeNull();
      expect(readSessionDraft('create:u1')).toBeNull();
    } finally { vi.useRealTimers(); }
  });

  it('releases an intent after a definitive validation rejection so a corrected payload gets a new key', async () => {
    const create = vi.spyOn(api, 'createApplication').mockRejectedValue(new ApiError({ status: 422, code: 'VALIDATION_FAILED', message: 'Некорректная сумма' }));
    const { result } = setup();
    await act(async () => { result.current.start(body); });
    expect(readSessionDraft('create:u1')).toBeNull();
    create.mockResolvedValue(makeApp({ client_status: 'FILLING' }));
    await act(async () => { result.current.start({ ...body, amount: '1000000' }); });
    expect(create.mock.calls[1]?.[0].amount).toBe('1000000');
    expect(create.mock.calls[1]?.[1]).not.toBe(create.mock.calls[0]?.[1]);
  });
});
