import { MantineProvider, TextInput } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, render, renderHook, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { useForm } from 'react-hook-form';
import { describe, expect, it, vi } from 'vitest';
import { valuesFromServer, type DraftValues } from './formModel';
import { useDraftAutosave } from './useDraftAutosave';
import { api } from '@/shared/api/endpoints';
import { ApiError, networkError } from '@/shared/api/errors';
import type { DraftResponse } from '@/shared/api/types';
import { qk } from '@/shared/api/queries';
import { makeApp } from '@/test/fixtures';
import { server } from '@/test/server';

const app = makeApp({ client_status: 'FILLING', version: 3, form: { amount: '1200000.00', term_months: 24, client_comment: null } });

function Draft() {
  const initial: DraftValues = valuesFromServer(app.form as Record<string, unknown>);
  const form = useForm<DraftValues>({ defaultValues: initial });
  const { status } = useDraftAutosave(app.id, form, initial);
  return (
    <form>
      <TextInput label="Комментарий" {...form.register('client_comment')} />
      <p>{status.state === 'saved' ? 'Сохранено' : status.state}</p>
    </form>
  );
}

describe('useDraftAutosave', () => {
  it('saves only the changed field with expected_version from the latest server answer', async () => {
    const patches: unknown[] = [];
    server.use(
      http.patch(`*/api/v1/applications/${app.id}`, async ({ request }) => {
        patches.push(await request.json());
        return HttpResponse.json({ application: { ...app, version: 4 }, field_errors: [] });
      }),
    );
    const queryClient = new QueryClient();
    queryClient.setQueryData(qk.application(app.id), app);
    const user = userEvent.setup();
    render(
      <MantineProvider>
        <QueryClientProvider client={queryClient}>
          <Draft />
        </QueryClientProvider>
      </MantineProvider>,
    );

    await user.type(screen.getByLabelText('Комментарий'), 'Сезонные продажи');
    expect(await screen.findByText('Сохранено', {}, { timeout: 4000 })).toBeInTheDocument();
    expect(patches).toEqual([{ expected_version: 3, client_comment: 'Сезонные продажи' }]);
    await waitFor(() => expect(queryClient.getQueryData<typeof app>(qk.application(app.id))?.version).toBe(4));
  });
});

// Deferred responses expose edits that arrive between two serialized PATCHes.
describe('flush', () => {
  function setup() {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    queryClient.setQueryData(qk.application(app.id), app);
    const wrapper = ({ children }: { children: React.ReactNode }) => <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
    const hook = renderHook(() => {
      const initial = valuesFromServer(app.form as Record<string, unknown>);
      const form = useForm<DraftValues>({ defaultValues: initial });
      return { form, ...useDraftAutosave(app.id, form, initial) };
    }, { wrapper });
    return { ...hook, queryClient };
  }

  it('shares a serialized flush and waits for every edit made during the first request', async () => {
    const first = deferred<DraftResponse>();
    const second = deferred<DraftResponse>();
    const patch = vi.spyOn(api, 'updateDraft').mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const { result } = setup();
    act(() => result.current.form.setValue('client_comment', 'Первый'));
    let flush!: Promise<boolean>;
    act(() => { flush = result.current.flush(); });
    await waitFor(() => expect(patch).toHaveBeenCalledTimes(1));
    act(() => {
      result.current.form.setValue('client_comment', 'Последний');
      result.current.form.setValue('amount', 2000000);
    });
    expect(result.current.flush()).toBe(flush);
    let resolved = false;
    void flush.then(() => { resolved = true; });
    await act(async () => first.resolve({ application: { ...app, version: 4 }, field_errors: [] }));
    expect(resolved).toBe(false);
    expect(patch).toHaveBeenCalledTimes(2);
    expect(patch.mock.calls[0]?.[1]).toEqual({ expected_version: 3, client_comment: 'Первый' });
    expect(patch.mock.calls[1]?.[1]).toEqual({ expected_version: 4, client_comment: 'Последний', amount: '2000000' });
    await act(async () => second.resolve({ application: { ...app, version: 5 }, field_errors: [] }));
    expect(await flush).toBe(true);
    expect(result.current.hasPending()).toBe(false);
  });

  it('keeps field errors and blocks flush until the rejected field is corrected', async () => {
    const patch = vi.spyOn(api, 'updateDraft')
      .mockResolvedValueOnce({ application: { ...app, version: 4 }, field_errors: [{ field: 'client_comment', code: 'TOO_LONG', message: 'Не более 1000 символов' }] })
      .mockResolvedValueOnce({ application: { ...app, version: 5 }, field_errors: [] })
      .mockResolvedValueOnce({ application: { ...app, version: 6 }, field_errors: [] });
    const { result } = setup();
    act(() => {
      result.current.form.setValue('client_comment', 'x'.repeat(1001));
      result.current.form.setValue('amount', 2000000);
    });
    let saved = true;
    await act(async () => { saved = await result.current.flush(); });
    expect(saved).toBe(false);
    expect(result.current.status.state).toBe('error');
    expect(result.current.form.getFieldState('client_comment').error?.message).toBe('Не более 1000 символов');
    expect(result.current.hasPending()).toBe(true);
    act(() => {
      result.current.form.setError('purpose', { type: 'server', message: 'Выберите цель' });
      result.current.form.setValue('client_comment', 'Исправлен');
    });
    await act(async () => { saved = await result.current.flush(); });
    expect(saved).toBe(true);
    expect(patch.mock.calls[1]?.[1]).toEqual({ expected_version: 4, client_comment: 'Исправлен' });
    expect(result.current.form.getFieldState('client_comment').error).toBeUndefined();
    expect(result.current.form.getFieldState('purpose').error?.message).toBe('Выберите цель');
  });

  it('reuses the exact body and key across network failures and manual retry, then rebases a version conflict', async () => {
    vi.useFakeTimers();
    try {
      const patch = vi.spyOn(api, 'updateDraft').mockRejectedValue(networkError());
      const { result, queryClient } = setup();
      act(() => result.current.form.setValue('client_comment', 'Правка'));
      let flush!: Promise<boolean>;
      act(() => { flush = result.current.flush(); });
      await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
      expect(await flush).toBe(false);
      expect(patch).toHaveBeenCalledTimes(3);
      const original = patch.mock.calls[0];
      queryClient.setQueryData(qk.application(app.id), { ...app, version: 8 });
      act(() => result.current.form.setValue('client_comment', 'Новая правка'));
      patch.mockRejectedValueOnce(new ApiError({ status: 409, code: 'VERSION_CONFLICT', message: 'Конфликт' }))
        .mockResolvedValueOnce({ application: { ...app, version: 10 }, field_errors: [] });
      vi.spyOn(api, 'getApplication').mockResolvedValue({ ...app, version: 9 });
      await act(async () => { expect(await result.current.flush()).toBe(true); });
      expect(patch.mock.calls.slice(0, 4)).toEqual([original, original, original, original]);
      expect(patch.mock.calls[4]?.[1]).toEqual({ expected_version: 9, client_comment: 'Новая правка' });
      expect(patch.mock.calls[4]?.[2]).not.toBe(original?.[2]);
    } finally { vi.useRealTimers(); }
  });
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}
