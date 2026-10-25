// @ts-expect-error Node-only test helper; the browser project has no Node type dependency.
import { transferableAbortController } from 'node:util';
import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import * as autosave from './useDraftAutosave';
import { ApplicationFormPage } from './ApplicationFormPage';
import { api } from '@/shared/api/endpoints';
import { ApiError } from '@/shared/api/errors';
import { toast } from '@/shared/ui/toast';
import { makeApp } from '@/test/fixtures';

vi.mock('@/features/auth/AuthProvider', () => ({ useUser: () => ({ id: 'u1', login: 'client.test', role: 'CLIENT' }) }));

const id = makeApp().id;
const base = makeApp({ client_status: 'FILLING', available_actions: ['SUBMIT'], form: { applicant_inn: '002000010193', representative_role: 'DIRECTOR', client_comment: '' } });

function setup(step = 'company') {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const router = createMemoryRouter([
    { path: '/client/applications/:id/edit/:step', element: <ApplicationFormPage /> },
    { path: '*', element: <div>Страница статуса</div> },
  ], { initialEntries: [`/client/applications/${id}/edit/${step}`] });
  const view = render(<MantineProvider><QueryClientProvider client={queryClient}><RouterProvider router={router} /></QueryClientProvider></MantineProvider>);
  return { ...view, router };
}

beforeEach(() => {
  // React Router uses Node Request in jsdom; both must use the same AbortSignal implementation.
  vi.stubGlobal('AbortController', transferableAbortController().constructor);
  vi.spyOn(api, 'getApplication').mockResolvedValue(base);
  vi.spyOn(api, 'dictionaries').mockResolvedValue({ purposes: [], document_types: [], consents: [], offer_decline_reasons: [], representative_roles: [], collateral_types: [], collateral_owners: [] });
  vi.spyOn(api, 'products').mockResolvedValue({ policy_version: 'test', items: [] });
  vi.spyOn(api, 'meta').mockResolvedValue({ demo_mode: false } as Awaited<ReturnType<typeof api.meta>>);
  vi.spyOn(toast, 'error').mockImplementation(() => undefined);
  vi.spyOn(window, 'scrollTo').mockImplementation(() => undefined);
});

afterEach(() => vi.unstubAllGlobals());

describe('draft navigation and INN confirmation', () => {
  it('blocks cleared/invalid INN, permits retry after failure, and accepts persisted SOURCE_UNAVAILABLE', async () => {
    const user = userEvent.setup();
    const prefill = vi.spyOn(api, 'prefill')
      .mockRejectedValueOnce(new ApiError({ status: 503, code: 'SOURCE_FAILED', message: 'Нет связи' }))
      .mockResolvedValueOnce({ application: { ...base, version: 8, inn_check_status: 'UNAVAILABLE', form: { ...base.form, applicant_inn: '7707083893' } }, prefill: { status: 'SOURCE_UNAVAILABLE', message: 'Нет связи с реестром' } });
    const { router } = setup();
    const input = await screen.findByLabelText('ИНН компании или ИП');
    expect(screen.getByRole('button', { name: 'Далее' })).toBeEnabled();
    await user.clear(input);
    expect(screen.getByText(/В заявке сохранен ИНН:/)).toHaveTextContent('002000010193');
    expect(screen.getByText(/Поле очищено/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Далее' })).toBeDisabled();
    await user.click(screen.getByRole('button', { name: /Условия/ }));
    expect(router.state.location.pathname).toContain('/company');
    fireEvent.change(input, { target: { value: '7707083894' } });
    expect(screen.getByRole('button', { name: 'Далее' })).toBeDisabled();
    expect(prefill).not.toHaveBeenCalled();
    fireEvent.change(input, { target: { value: '7707083893' } });
    expect(screen.getByRole('button', { name: 'Далее' })).toBeDisabled();
    await waitFor(() => expect(prefill).toHaveBeenCalledTimes(1));
    await screen.findByText('Не удалось проверить ИНН. Повторите проверку.');
    await user.click(screen.getByRole('button', { name: 'Проверить ИНН повторно' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Далее' })).toBeEnabled());
    expect(prefill.mock.calls.map((call) => call[1])).toEqual(['7707083893', '7707083893']);
    await user.click(screen.getByRole('button', { name: 'Далее' }));
    await waitFor(() => expect(router.state.location.pathname).toContain('/terms'));
    await user.click(screen.getByRole('button', { name: 'Назад' }));
    expect(await screen.findByLabelText('ИНН компании или ИП')).toHaveValue('7707083893');
  });

  it('keeps a newer typed INN unconfirmed when an older prefill response arrives', async () => {
    let reply!: (value: Awaited<ReturnType<typeof api.prefill>>) => void;
    const prefill = vi.spyOn(api, 'prefill').mockImplementationOnce(() => new Promise((resolve) => { reply = resolve; }))
      .mockResolvedValueOnce({ application: { ...base, version: 9 }, prefill: { status: 'FOUND', message: null } });
    setup();
    const input = await screen.findByLabelText('ИНН компании или ИП');
    fireEvent.change(input, { target: { value: '7707083893' } });
    await waitFor(() => expect(prefill).toHaveBeenCalledTimes(1));
    fireEvent.change(input, { target: { value: '002000010193' } });
    expect(screen.getByRole('button', { name: 'Далее' })).toBeDisabled();
    await act(async () => reply({ application: { ...base, version: 8, form: { ...base.form, applicant_inn: '7707083893' } }, prefill: { status: 'FOUND', message: null } }));
    expect(screen.getByRole('button', { name: 'Далее' })).toBeDisabled();
    await waitFor(() => expect(screen.getByRole('button', { name: 'Далее' })).toBeEnabled());
    expect(prefill.mock.calls.map((call) => call[1])).toEqual(['7707083893', '002000010193']);
    expect(input).toHaveValue('002000010193');
  });

  it('waits before leaving and keeps the route and inline errors when PATCH rejects a field', async () => {
    const user = userEvent.setup();
    let reply!: (value: Awaited<ReturnType<typeof api.updateDraft>>) => void;
    const patch = vi.spyOn(api, 'updateDraft').mockImplementationOnce(() => new Promise((resolve) => { reply = resolve; }));
    const { router } = setup('terms');
    const comment = await screen.findByLabelText('Комментарий');
    expect(comment).toHaveAttribute('maxlength', '1000');
    fireEvent.change(comment, { target: { value: 'Комментарий' } });
    await user.click(screen.getByRole('link', { name: 'Статус и отмена заявки' }));
    await waitFor(() => expect(patch).toHaveBeenCalledTimes(1));
    expect(router.state.location.pathname).toContain('/terms');
    await act(async () => reply({ application: { ...base, version: 8 }, field_errors: [{ field: 'client_comment', code: 'INVALID', message: 'Исправьте комментарий' }] }));
    expect(await screen.findByText('Исправьте комментарий')).toBeInTheDocument();
    expect(router.state.location.pathname).toContain('/terms');
    expect(screen.queryByText(/^Сохранено в/)).not.toBeInTheDocument();
    patch.mockResolvedValue({ application: { ...base, version: 9 }, field_errors: [] });
    fireEvent.change(comment, { target: { value: 'Исправлен' } });
    await user.click(screen.getByRole('link', { name: 'Статус и отмена заявки' }));
    await screen.findByText('Страница статуса');
    expect(router.state.location.pathname).toBe(`/client/applications/${id}`);
  });
  it('does not call submit after a failed flush on the review step', async () => {
    const flush = vi.fn().mockResolvedValue(false);
    vi.spyOn(autosave, 'useDraftAutosave').mockReturnValue({ status: { state: 'error', message: 'Исправьте поля' }, flush, hasPending: () => true });
    const submit = vi.spyOn(api, 'submit');
    const { router } = setup('review');
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Отправить заявку' }));
    await waitFor(() => expect(flush).toHaveBeenCalled());
    expect(submit).not.toHaveBeenCalled();
    expect(router.state.location.pathname).toContain('/review');
    expect(screen.getByText('Исправьте поля')).toBeInTheDocument();
  });

});
