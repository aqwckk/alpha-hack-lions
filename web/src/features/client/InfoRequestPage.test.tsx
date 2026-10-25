import { fireEvent, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, it, vi } from 'vitest';
import { InfoRequestPage } from './InfoRequestPage';
import { api } from '@/shared/api/endpoints';
import type { ClientApplication } from '@/shared/api/types';
import { clearSessionDrafts, readSessionDraft, writeSessionDraft } from '@/shared/lib/sessionDrafts';
import { toast } from '@/shared/ui/toast';
import { makeApp } from '@/test/fixtures';
import { renderRoute } from '@/test/render';

const identity = vi.hoisted(() => ({ id: 'u1' }));
vi.mock('@/features/auth/AuthProvider', () => ({ useUser: () => ({ id: identity.id }) }));
const request: NonNullable<ClientApplication['info_request']> = {
  id: 'r1', status: 'OPEN', created_at: null, answered_at: null, due_at: '2026-10-28T12:00:00Z', due_text: '28 октября',
  items: [{ id: 'i1', answer_type: 'TEXT', field_name: null, field_label: null, current_value: null, document_type: null, document_title: null, client_text: 'Поясните сезонность', required: true, answer_text: null, answer_value: null, document_ids: [] }],
};
const app = makeApp({ client_status: 'ACTION_REQUIRED', available_actions: ['RESPOND_INFO'], info_request: request });
const mount = () => renderRoute('/client/applications/:id/info-request', `/client/applications/${app.id}/info-request`, <InfoRequestPage />);

beforeEach(() => {
  identity.id = 'u1';
  sessionStorage.clear();
  vi.spyOn(toast, 'success').mockImplementation(() => undefined);
});

it('limits replies to 2000, restores by user/application/request, and clears only after successful send or logout cleanup', async () => {
  const get = vi.spyOn(api, 'getApplication').mockResolvedValue(app);
  const respond = vi.spyOn(api, 'respondInfo').mockResolvedValue(makeApp());
  let view = mount();
  const input = await screen.findByLabelText('Ваш ответ');
  expect(input).toHaveAttribute('maxlength', '2000');
  const text = 'а'.repeat(2000);
  fireEvent.change(input, { target: { value: text } });
  expect(screen.getByText('2000 / 2000 символов')).toBeInTheDocument();
  await userEvent.setup().type(input, 'б');
  expect(input).toHaveValue(text);
  view.unmount();
  identity.id = 'u2';
  view = mount();
  expect(await screen.findByLabelText('Ваш ответ')).toHaveValue('');
  view.unmount();
  identity.id = 'u1';
  get.mockResolvedValue({ ...app, info_request: { ...request, id: 'r2' } });
  view = mount();
  expect(await screen.findByLabelText('Ваш ответ')).toHaveValue('');
  view.unmount();
  get.mockResolvedValue(app);
  view = mount();
  expect(await screen.findByLabelText('Ваш ответ')).toHaveValue(text);
  await userEvent.setup().click(screen.getByRole('button', { name: 'Отправить ответ' }));
  await waitFor(() => expect(respond).toHaveBeenCalledTimes(1));
  expect(respond.mock.calls[0]?.[2]).toEqual([{ item_id: 'i1', answer_text: text }]);
  await waitFor(() => expect(readSessionDraft(`info:u1:${app.id}:r1`)).toBeNull());
  writeSessionDraft(`info:u1:${app.id}:r2`, { i1: { text: 'Черновик', value: '' } });
  sessionStorage.setItem('unrelated', 'keep');
  clearSessionDrafts();
  expect(readSessionDraft(`info:u1:${app.id}:r2`)).toBeNull();
  expect(sessionStorage.getItem('unrelated')).toBe('keep');
});
