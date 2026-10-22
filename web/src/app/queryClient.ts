import { QueryClient } from '@tanstack/react-query';
import { isApiError } from '@/shared/api/errors';

/** Reads are retried on network and server failures only; 4xx answers are final. */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: (count, error) => {
          if (isApiError(error) && error.status >= 400 && error.status < 500) return false;
          return count < 3;
        },
        retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 8000),
        staleTime: 5_000,
      },
      mutations: { retry: false },
    },
  });
}
