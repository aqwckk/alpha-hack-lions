export interface ApiFieldError {
  field: string;
  code: string;
  message?: string | null;
}

export type ApiErrorKind =
  | 'network'
  | 'unauthorized'
  | 'forbidden'
  | 'not_found'
  | 'conflict'
  | 'validation'
  | 'rate_limit'
  | 'unavailable'
  | 'server';

/** One error model for every API failure: the UI never parses raw responses. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string | null;
  readonly details: Record<string, unknown>;
  readonly fields: ApiFieldError[];

  constructor(init: {
    status: number;
    code: string;
    message: string;
    requestId?: string | null;
    details?: Record<string, unknown> | null;
    fields?: ApiFieldError[] | null;
  }) {
    super(init.message);
    this.name = 'ApiError';
    this.status = init.status;
    this.code = init.code;
    this.requestId = init.requestId ?? null;
    this.details = init.details ?? {};
    this.fields = init.fields ?? [];
  }

  get kind(): ApiErrorKind {
    if (this.status === 0) return 'network';
    if (this.status === 401) return 'unauthorized';
    if (this.status === 403) return 'forbidden';
    if (this.status === 404) return 'not_found';
    if (this.status === 409) return 'conflict';
    if (this.status === 422 || this.status === 400 || this.status === 413) return 'validation';
    if (this.status === 429) return 'rate_limit';
    if (this.status === 503) return 'unavailable';
    return 'server';
  }
}

export const NETWORK_MESSAGE = 'Нет связи с сервером. Проверьте подключение, мы повторим запрос.';

export function networkError(): ApiError {
  return new ApiError({ status: 0, code: 'NETWORK', message: NETWORK_MESSAGE });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** Converts the unified backend error body {"error": {...}} (or anything else) into ApiError. */
export function toApiError(status: number, body: unknown, requestIdHeader: string | null): ApiError {
  const err = isRecord(body) && isRecord(body.error) ? body.error : null;
  const fields = err && Array.isArray(err.fields)
    ? err.fields.filter(isRecord).map((f) => ({
        field: String(f.field ?? ''),
        code: String(f.code ?? ''),
        message: typeof f.message === 'string' ? f.message : null,
      }))
    : [];
  return new ApiError({
    status,
    code: err && typeof err.code === 'string' ? err.code : `HTTP_${status}`,
    message: err && typeof err.message === 'string' && err.message ? err.message : defaultMessage(status),
    requestId: err && typeof err.request_id === 'string' ? err.request_id : requestIdHeader,
    details: err && isRecord(err.details) ? err.details : null,
    fields,
  });
}

function defaultMessage(status: number): string {
  if (status === 401) return 'Сессия истекла, войдите снова';
  if (status === 403) return 'Недостаточно прав для этого действия';
  if (status === 404) return 'Не найдено или нет доступа';
  if (status === 409) return 'Данные изменились, обновите страницу';
  if (status === 429) return 'Слишком много запросов, попробуйте чуть позже';
  if (status >= 500) return 'Сервис временно недоступен, попробуйте позже';
  return 'Не удалось выполнить запрос';
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError;
}

export function errorMessage(error: unknown): string {
  if (isApiError(error)) return error.message;
  return 'Что-то пошло не так. Обновите страницу.';
}

/** Short diagnostic suffix for support: request id only, no personal data. */
export function errorReference(error: unknown): string | null {
  return isApiError(error) && error.requestId ? `Код запроса: ${error.requestId}` : null;
}
