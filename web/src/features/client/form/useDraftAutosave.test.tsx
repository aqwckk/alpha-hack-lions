import { MantineProvider, TextInput } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { useForm } from 'react-hook-form';
import { describe, expect, it } from 'vitest';
import { valuesFromServer, type DraftValues } from './formModel';
import { useDraftAutosave } from './useDraftAutosave';
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
