import { useQuery, type QueryClient } from '@tanstack/react-query';
import { api } from './endpoints';
import type { ClientApplication, ProductInfo } from './types';
import { pollInterval } from '@/shared/lib/labels';

/** Central query keys. Private data keys are cleared on logout (queryClient.clear()). */
export const qk = {
  meta: ['meta'] as const,
  products: ['catalog', 'products'] as const,
  dictionaries: ['catalog', 'dictionaries'] as const,
  bankDictionaries: ['bank', 'dictionaries'] as const,
  applications: ['client', 'applications'] as const,
  application: (id: string) => ['client', 'application', id] as const,
  schedule: (id: string, optionId?: string) => ['client', 'application', id, 'schedule', optionId ?? 'loan'] as const,
  notifications: ['notifications'] as const,
  bankList: (params: Record<string, unknown>) => ['bank', 'list', params] as const,
  bankCard: (id: string) => ['bank', 'card', id] as const,
  metrics: (period: number, product: string) => ['risk', 'metrics', period, product] as const,
  configs: ['risk', 'configs'] as const,
  configContent: (type: string) => ['risk', 'configs', type] as const,
  audit: (params: Record<string, unknown>) => ['risk', 'audit', params] as const,
  demo: ['demo', 'integrations'] as const,
};

const STATIC = { staleTime: Infinity, gcTime: Infinity } as const;

export function useMeta() {
  return useQuery({ queryKey: qk.meta, queryFn: api.meta, ...STATIC, retry: 1 });
}

export function useProducts() {
  return useQuery({ queryKey: qk.products, queryFn: api.products, ...STATIC });
}

export function useProduct(code: string | null | undefined): ProductInfo | undefined {
  const { data } = useProducts();
  return data?.items.find((p) => p.product_code === code);
}

export function useDictionaries() {
  return useQuery({ queryKey: qk.dictionaries, queryFn: api.dictionaries, ...STATIC });
}

export function useBankDictionaries() {
  return useQuery({ queryKey: qk.bankDictionaries, queryFn: api.bankDictionaries, ...STATIC });
}

/** Client application with live status: polls every 3 s while the system works, 15 s otherwise. */
export function useClientApplication(id: string) {
  return useQuery({
    queryKey: qk.application(id),
    queryFn: () => api.getApplication(id),
    refetchInterval: (query) => pollInterval(query.state.data?.client_status),
    refetchOnWindowFocus: true,
  });
}

export function useNotifications(enabled: boolean) {
  return useQuery({
    queryKey: qk.notifications,
    queryFn: api.notifications,
    enabled,
    refetchInterval: 15000,
  });
}

/**
 * Puts a confirmed server response into the cache. An in-flight poll started before the command
 * is cancelled, and an older version never overwrites a newer one (no stale UI after a command).
 */
export function putApplication(queryClient: QueryClient, app: ClientApplication): void {
  void queryClient.cancelQueries({ queryKey: qk.application(app.id), exact: true });
  const prev = queryClient.getQueryData<ClientApplication>(qk.application(app.id));
  if (!prev || app.version >= prev.version) queryClient.setQueryData(qk.application(app.id), app);
}

/** Stores a command result and refreshes dependent lists. */
export function storeApplication(queryClient: QueryClient, app: ClientApplication): void {
  putApplication(queryClient, app);
  void queryClient.invalidateQueries({ queryKey: qk.applications });
  void queryClient.invalidateQueries({ queryKey: qk.notifications });
}

export function currentVersion(queryClient: QueryClient, id: string): number | undefined {
  return queryClient.getQueryData<ClientApplication>(qk.application(id))?.version;
}
