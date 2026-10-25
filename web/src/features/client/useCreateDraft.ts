import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '@/shared/api/endpoints';
import { isApiError } from '@/shared/api/errors';
import { storeApplication } from '@/shared/api/queries';
import { newId } from '@/shared/lib/ids';
import { readSessionDraft, removeSessionDraft, writeSessionDraft } from '@/shared/lib/sessionDrafts';
import { toast } from '@/shared/ui/toast';

type CreateBody = Parameters<typeof api.createApplication>[0];
interface Attempt { key: string; body: CreateBody; inn: string | null }

function restore(key: string): Attempt | null {
  const value = readSessionDraft(key) as Partial<Attempt> | null;
  const body = value?.body;
  if (!value || typeof value.key !== 'string' || !body || typeof body.product_code !== 'string' || typeof body.purpose !== 'string' || typeof body.amount !== 'string' || typeof body.term_months !== 'number' || (value.inn !== null && typeof value.inn !== 'string')) return null;
  return value as Attempt;
}

const unknownOutcome = (error: unknown) => !isApiError(error) || error.kind === 'network' || error.status >= 500 || error.status === 408 || error.code === 'IDEMPOTENCY_IN_PROGRESS';

/** A single unresolved creation per user/tab survives page reloads with its exact payload and key. */
export function useCreateDraft(userId: string) {
  const storageKey = `create:${userId}`;
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [pending, setPending] = useState<Attempt | null>(() => restore(storageKey));
  const attempt = useRef(pending);
  const busy = useRef(false);
  const mutation = useMutation({
    mutationFn: (intent: Attempt) => api.createApplication(intent.body, intent.key),
    retry: (count, error) => unknownOutcome(error) && count < 2,
    retryDelay: 1500,
    onSuccess: async (created, intent) => {
      let app = created;
      if (intent.inn) {
        try { app = (await api.prefill(app.id, intent.inn, app.version)).application; }
        catch { /* The company step can repeat prefill for this existing draft. */ }
      }
      storeApplication(queryClient, app);
      removeSessionDraft(storageKey);
      attempt.current = null;
      setPending(null);
      navigate(`/client/applications/${app.id}/edit/company`);
    },
    onError: (error) => {
      if (!unknownOutcome(error)) {
        removeSessionDraft(storageKey);
        attempt.current = null;
        setPending(null);
      }
      toast.error(error, 'Не удалось создать заявку');
    },
    onSettled: () => { busy.current = false; },
  });

  const start = (body?: CreateBody, inn: string | null = null): boolean => {
    if (busy.current) return false;
    let intent = attempt.current;
    if (!intent) {
      if (!body) return false;
      intent = { key: newId(), body: { ...body }, inn };
      if (!writeSessionDraft(storageKey, intent)) {
        toast.warning('Разрешите сохранение данных этой вкладки в браузере и повторите создание заявки.');
        return false;
      }
      attempt.current = intent;
      setPending(intent);
    }
    busy.current = true;
    mutation.mutate(intent);
    return true;
  };

  return { start, pending, isPending: mutation.isPending };
}
