import { useMutation, useQueryClient, type QueryClient } from '@tanstack/react-query';
import { ApiError, isApiError } from './errors';
import { currentVersion, qk, storeApplication } from './queries';
import type { ClientApplication, StaffCard } from './types';
import { newId } from '@/shared/lib/ids';
import { toast } from '@/shared/ui/toast';

/** Commands are retried only after a network failure and always with the same Idempotency-Key. */
const retryOnNetwork = (count: number, error: unknown) => isApiError(error) && error.kind === 'network' && count < 2;

export const CONFLICT_MESSAGE = 'Заявка изменилась, мы обновили данные. Проверьте их и повторите действие, если оно еще нужно.';

/** Shared reaction to command failures; returns the text shown to the user. */
export function reactToCommandError(error: unknown, queryClient: QueryClient, refreshKey: readonly unknown[]): string {
  if (!isApiError(error)) {
    toast.error(error);
    return 'Что-то пошло не так';
  }
  switch (error.code) {
    case 'VERSION_CONFLICT':
    case 'INVALID_TRANSITION':
    case 'OFFER_EXPIRED':
    case 'DOCUMENTS_NOT_READY':
    case 'ALREADY_TAKEN': {
      void queryClient.invalidateQueries({ queryKey: refreshKey });
      const text = error.code === 'VERSION_CONFLICT' ? CONFLICT_MESSAGE : error.message;
      toast.warning(text, error.code === 'VERSION_CONFLICT' ? 'Данные обновлены' : undefined);
      return text;
    }
    default: {
      // Field errors are listed so that a dialog never fails silently.
      const details = error.fields.map((f) => f.message).filter(Boolean).join('. ');
      const text = details ? `${error.message}: ${details}` : error.message;
      toast.error(new ApiError({ status: error.status, code: error.code, message: text, requestId: error.requestId }));
      return text;
    }
  }
}

interface CommandOptions<R> {
  /** Toast after success. */
  success?: string;
  onSuccess?: (result: R) => void;
  /** Return true when the page handled the error itself (inline message). */
  onError?: (error: ApiError) => boolean;
}

/** Client command over an application: current version + fresh Idempotency-Key on every click. */
export function useClientCommand<V>(
  appId: string,
  run: (vars: V & { version: number; key: string }) => Promise<ClientApplication>,
  options: CommandOptions<ClientApplication> = {},
) {
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationFn: run,
    retry: retryOnNetwork,
    retryDelay: 1500,
    onSuccess: (app) => {
      storeApplication(queryClient, app);
      if (options.success) toast.success(options.success);
      options.onSuccess?.(app);
    },
    onError: (error) => {
      if (isApiError(error) && options.onError?.(error)) return;
      reactToCommandError(error, queryClient, qk.application(appId));
    },
  });
  const trigger = (vars: V) => {
    if (mutation.isPending) return;
    const version = currentVersion(queryClient, appId);
    if (version === undefined) return;
    mutation.mutate({ ...vars, version, key: newId() });
  };
  return { trigger, isPending: mutation.isPending, error: mutation.error, reset: mutation.reset };
}

/** Bank employee command over a staff card (same version and idempotency rules). */
export function useStaffCommand<V>(
  appId: string,
  run: (vars: V & { version: number; key: string }) => Promise<StaffCard>,
  options: CommandOptions<StaffCard> = {},
) {
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationFn: run,
    retry: retryOnNetwork,
    retryDelay: 1500,
    onSuccess: (card) => {
      queryClient.setQueryData(qk.bankCard(appId), card);
      void queryClient.invalidateQueries({ queryKey: ['bank', 'list'] });
      if (options.success) toast.success(options.success);
      options.onSuccess?.(card);
    },
    onError: (error) => {
      if (isApiError(error) && options.onError?.(error)) return;
      reactToCommandError(error, queryClient, qk.bankCard(appId));
    },
  });
  const trigger = (vars: V, version: number) => {
    if (mutation.isPending) return;
    mutation.mutate({ ...vars, version, key: newId() });
  };
  return { trigger, isPending: mutation.isPending, error: mutation.error, reset: mutation.reset };
}

/**
 * Draft-phase commands (prefill, consents, documents) express the client's own intent, so after a
 * version conflict they re-read the application once and repeat with the fresh version.
 */
export async function withFreshVersion<T>(queryClient: QueryClient, appId: string, fn: (version: number) => Promise<T>): Promise<T> {
  try {
    return await fn(currentVersion(queryClient, appId) ?? 0);
  } catch (error) {
    if (isApiError(error) && error.code === 'VERSION_CONFLICT') {
      await queryClient.refetchQueries({ queryKey: qk.application(appId), exact: true });
      return fn(currentVersion(queryClient, appId) ?? 0);
    }
    throw error;
  }
}
