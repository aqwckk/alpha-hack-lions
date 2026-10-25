import { http, rawRequest, unwrap } from './client';
import type {
  AiSummaryResponse,
  AuditPage,
  BankDictionaries,
  ClientApplication,
  ConfigsResponse,
  DemoState,
  Dictionaries,
  DraftResponse,
  DraftUpdateRequest,
  ExplanationResponse,
  InfoAnswer,
  InfoItemInput,
  IntegrationSource,
  MatchRequest,
  MatchResponse,
  MetaInfo,
  Metrics,
  NotificationsPage,
  OptionInput,
  PrefillResponse,
  ProductsResponse,
  ScheduleResponse,
  SigningCodeResponse,
  StaffCard,
  StaffPage,
  TokenResponse,
} from './types';

/**
 * Free-form endpoints (`additionalProperties: true` in the contract) are narrowed here, at the
 * boundary, to the documented shapes in ./types. Everything else is typed by the generated schema.
 */
function documented<T>(value: unknown): T {
  return value as T;
}

const idem = (key: string) => ({ header: { 'idempotency-key': key } });
const appPath = (id: string) => ({ path: { application_id: id } });

export type ConsentType = 'CONSENT_PERSONAL_DATA' | 'CONSENT_CREDIT_BUREAU' | 'AUTHORITY_CONFIRMATION';

export const api = {
  // Session and public endpoints
  meta: async (): Promise<MetaInfo> => unwrap(http.GET('/api/v1/meta')).then((d) => documented<MetaInfo>(d)),
  login: (login: string, password: string): Promise<TokenResponse> =>
    unwrap(http.POST('/api/v1/auth/login', { body: { login, password }, credentials: 'include' })),
  logout: (): Promise<unknown> => unwrap(http.POST('/api/v1/auth/logout', { credentials: 'include' })),

  products: async (): Promise<ProductsResponse> =>
    documented<ProductsResponse>(await unwrap(http.GET('/api/v1/catalog/products'))),
  dictionaries: async (): Promise<Dictionaries> =>
    documented<Dictionaries>(await unwrap(http.GET('/api/v1/catalog/dictionaries'))),
  match: (body: MatchRequest): Promise<MatchResponse> => unwrap(http.POST('/api/v1/catalog/match', { body })),
  calculate: (body: { product_code: string; amount: string; term_months: number; rate_percent?: string; with_schedule?: boolean }): Promise<ScheduleResponse> =>
    unwrap(http.POST('/api/v1/catalog/calculate', { body: { ...body, with_schedule: body.with_schedule ?? false } })),
  trackWizard: (body: {
    event_type: 'PRODUCT_WIZARD_STARTED' | 'PRODUCT_SELECTED';
    wizard_session_id: string;
    product_code?: string;
    purpose?: string;
    amount?: string;
    term_months?: number;
    rank?: number;
    was_recommended?: boolean;
  }): Promise<unknown> => unwrap(http.POST('/api/v1/analytics/events', { body })),

  // Client application endpoints
  listApplications: (page = 1, pageSize = 20) => unwrap(http.GET('/api/v1/applications', { params: { query: { page, page_size: pageSize } } })),
  getApplication: (id: string): Promise<ClientApplication> => unwrap(http.GET('/api/v1/applications/{application_id}', { params: appPath(id) })),
  createApplication: (
    body: { product_code: string; purpose: string; amount: string; term_months: number; wizard_session_id?: string },
    key: string,
  ): Promise<ClientApplication> => unwrap(http.POST('/api/v1/applications', { params: idem(key), body })),
  updateDraft: (id: string, body: DraftUpdateRequest, key: string): Promise<DraftResponse> =>
    unwrap(http.PATCH('/api/v1/applications/{application_id}', { params: { ...appPath(id), ...idem(key) }, body })),
  prefill: (id: string, inn: string, version: number): Promise<PrefillResponse> =>
    unwrap(http.POST('/api/v1/applications/{application_id}/prefill', { params: appPath(id), body: { inn, expected_version: version } })),
  giveConsent: (id: string, type: ConsentType, version: number): Promise<ClientApplication> =>
    unwrap(
      http.PUT('/api/v1/applications/{application_id}/consents/{consent_type}', {
        params: { path: { application_id: id, consent_type: type } },
        body: { expected_version: version },
      }),
    ),
  revokeConsent: (id: string, type: ConsentType, version: number): Promise<ClientApplication> =>
    unwrap(
      http.DELETE('/api/v1/applications/{application_id}/consents/{consent_type}', {
        params: { path: { application_id: id, consent_type: type }, query: { expected_version: version } },
      }),
    ),
  uploadDocument: async (
    id: string,
    input: { documentType: string; file: File; infoRequestItemId?: string; version?: number },
  ): Promise<ClientApplication> => {
    const form = new FormData();
    form.append('document_type', input.documentType);
    form.append('file', input.file, input.file.name);
    if (input.infoRequestItemId) form.append('info_request_item_id', input.infoRequestItemId);
    if (input.version !== undefined) form.append('expected_version', String(input.version));
    const res = await rawRequest(`/api/v1/applications/${encodeURIComponent(id)}/documents`, { method: 'POST', body: form });
    return documented<ClientApplication>(await res.json());
  },
  deleteDocument: (id: string, documentId: string, version: number): Promise<ClientApplication> =>
    unwrap(
      http.DELETE('/api/v1/applications/{application_id}/documents/{document_id}', {
        params: { path: { application_id: id, document_id: documentId }, query: { expected_version: version } },
      }),
    ),
  submit: (id: string, version: number, key: string): Promise<ClientApplication> =>
    unwrap(http.POST('/api/v1/applications/{application_id}/submit', { params: { ...appPath(id), ...idem(key) }, body: { expected_version: version } })),
  respondInfo: (id: string, version: number, answers: InfoAnswer[], key: string): Promise<ClientApplication> =>
    unwrap(
      http.POST('/api/v1/applications/{application_id}/info-response', {
        params: { ...appPath(id), ...idem(key) },
        body: { expected_version: version, answers },
      }),
    ),
  withdraw: (id: string, version: number, key: string): Promise<ClientApplication> =>
    unwrap(http.POST('/api/v1/applications/{application_id}/withdraw', { params: { ...appPath(id), ...idem(key) }, body: { expected_version: version } })),
  acceptOffer: (id: string, version: number, optionId: string, key: string): Promise<ClientApplication> =>
    unwrap(
      http.POST('/api/v1/applications/{application_id}/offer/accept', {
        params: { ...appPath(id), ...idem(key) },
        body: { expected_version: version, option_id: optionId },
      }),
    ),
  declineOffer: (id: string, version: number, reasonCode: string | null, key: string): Promise<ClientApplication> =>
    unwrap(
      http.POST('/api/v1/applications/{application_id}/offer/decline', {
        params: { ...appPath(id), ...idem(key) },
        body: { expected_version: version, reason_code: reasonCode },
      }),
    ),
  schedule: (id: string, optionId?: string): Promise<ScheduleResponse> =>
    unwrap(
      http.GET('/api/v1/applications/{application_id}/schedule', {
        params: { path: { application_id: id }, query: optionId ? { option_id: optionId } : {} },
      }),
    ),
  signingDocument: async (id: string, documentId: string): Promise<string> => {
    const data = await unwrap(
      http.GET('/api/v1/applications/{application_id}/signing-documents/{document_id}', {
        params: { path: { application_id: id, document_id: documentId } },
      }),
    );
    return typeof data === 'string' ? data : JSON.stringify(data, null, 2);
  },
  requestSigningCode: (id: string, key: string): Promise<SigningCodeResponse> =>
    unwrap(http.POST('/api/v1/applications/{application_id}/signing-code', { params: { ...appPath(id), ...idem(key) } })),
  sign: (id: string, version: number, code: string, key: string): Promise<ClientApplication> =>
    unwrap(http.POST('/api/v1/applications/{application_id}/sign', { params: { ...appPath(id), ...idem(key) }, body: { expected_version: version, code } })),
  explain: (id: string): Promise<ExplanationResponse> =>
    unwrap(http.POST('/api/v1/applications/{application_id}/explain', { params: appPath(id) })),
  clientDocument: (id: string, documentId: string): Promise<Response> =>
    rawRequest(`/api/v1/applications/${encodeURIComponent(id)}/documents/${encodeURIComponent(documentId)}/content`, {
      headers: { Accept: '*/*' },
    }),

  // Notification endpoints
  notifications: async (): Promise<NotificationsPage> =>
    documented<NotificationsPage>(await unwrap(http.GET('/api/v1/notifications', { params: { query: { page_size: 30 } } }))),
  markRead: (id: string): Promise<unknown> =>
    unwrap(http.POST('/api/v1/notifications/{notification_id}/read', { params: { path: { notification_id: id } } })),
  markAllRead: (): Promise<unknown> => unwrap(http.POST('/api/v1/notifications/read-all')),

  // Bank workplace endpoints
  bankList: async (query: Record<string, string | number | boolean | undefined>): Promise<StaffPage> =>
    documented<StaffPage>(await unwrap(http.GET('/api/v1/bank/applications', { params: { query: query as never } }))),
  bankCard: async (id: string, viewContext: 'QUEUE' | 'SEARCH' | 'ERROR_LIST'): Promise<StaffCard> =>
    documented<StaffCard>(
      await unwrap(http.GET('/api/v1/bank/applications/{application_id}', { params: { path: { application_id: id }, query: { view_context: viewContext } } })),
    ),
  bankDictionaries: async (): Promise<BankDictionaries> =>
    documented<BankDictionaries>(await unwrap(http.GET('/api/v1/bank/dictionaries'))),
  take: async (id: string, version: number, key: string): Promise<StaffCard> =>
    documented<StaffCard>(await unwrap(http.POST('/api/v1/bank/applications/{application_id}/take', { params: { ...appPath(id), ...idem(key) }, body: { expected_version: version } }))),
  release: async (id: string, version: number, comment: string, key: string): Promise<StaffCard> =>
    documented<StaffCard>(
      await unwrap(http.POST('/api/v1/bank/applications/{application_id}/release', { params: { ...appPath(id), ...idem(key) }, body: { expected_version: version, comment } })),
    ),
  approve: async (id: string, version: number, comment: string, key: string): Promise<StaffCard> =>
    documented<StaffCard>(
      await unwrap(http.POST('/api/v1/bank/applications/{application_id}/approve', { params: { ...appPath(id), ...idem(key) }, body: { expected_version: version, comment } })),
    ),
  counterOffer: async (id: string, version: number, options: OptionInput[], comment: string, key: string): Promise<StaffCard> =>
    documented<StaffCard>(
      await unwrap(
        http.POST('/api/v1/bank/applications/{application_id}/counter-offer', {
          params: { ...appPath(id), ...idem(key) },
          body: { expected_version: version, options, comment },
        }),
      ),
    ),
  requestInfo: async (id: string, version: number, items: InfoItemInput[], comment: string, key: string): Promise<StaffCard> =>
    documented<StaffCard>(
      await unwrap(
        http.POST('/api/v1/bank/applications/{application_id}/request-info', {
          params: { ...appPath(id), ...idem(key) },
          body: { expected_version: version, items, comment },
        }),
      ),
    ),
  decline: async (id: string, version: number, reasonCodes: string[], comment: string, key: string): Promise<StaffCard> =>
    documented<StaffCard>(
      await unwrap(
        http.POST('/api/v1/bank/applications/{application_id}/decline', {
          params: { ...appPath(id), ...idem(key) },
          body: { expected_version: version, reason_codes: reasonCodes, comment },
        }),
      ),
    ),
  confirm: async (id: string, version: number, comment: string, key: string): Promise<StaffCard> =>
    documented<StaffCard>(
      await unwrap(http.POST('/api/v1/bank/applications/{application_id}/confirm', { params: { ...appPath(id), ...idem(key) }, body: { expected_version: version, comment } })),
    ),
  returnDecision: async (id: string, version: number, comment: string, key: string): Promise<StaffCard> =>
    documented<StaffCard>(
      await unwrap(http.POST('/api/v1/bank/applications/{application_id}/return', { params: { ...appPath(id), ...idem(key) }, body: { expected_version: version, comment } })),
    ),
  retry: async (id: string, version: number, key: string): Promise<StaffCard> =>
    documented<StaffCard>(await unwrap(http.POST('/api/v1/bank/applications/{application_id}/retry', { params: { ...appPath(id), ...idem(key) }, body: { expected_version: version } }))),
  addComment: (id: string, body: string): Promise<unknown> =>
    unwrap(http.POST('/api/v1/bank/applications/{application_id}/comments', { params: appPath(id), body: { body } })),
  aiSummary: (id: string): Promise<AiSummaryResponse> =>
    unwrap(http.POST('/api/v1/bank/applications/{application_id}/ai-summary', { params: appPath(id) })),
  staffDocument: (id: string, documentId: string): Promise<Response> =>
    rawRequest(`/api/v1/bank/applications/${encodeURIComponent(id)}/documents/${encodeURIComponent(documentId)}/content`, {
      headers: { Accept: '*/*' },
    }),

  // Risk manager endpoints
  metrics: async (periodDays: number, productCode?: string): Promise<Metrics> =>
    documented<Metrics>(
      await unwrap(http.GET('/api/v1/risk/metrics', { params: { query: { period_days: periodDays, ...(productCode ? { product_code: productCode } : {}) } } })),
    ),
  configs: async (): Promise<ConfigsResponse> => documented<ConfigsResponse>(await unwrap(http.GET('/api/v1/risk/configs'))),
  configContent: async (type: 'SCORECARD' | 'POLICY'): Promise<Record<string, unknown>> =>
    documented<Record<string, unknown>>(await unwrap(http.GET('/api/v1/risk/configs/{config_type}', { params: { path: { config_type: type } } }))),
  audit: async (query: Record<string, string | number | boolean | undefined>): Promise<AuditPage> =>
    documented<AuditPage>(await unwrap(http.GET('/api/v1/risk/audit', { params: { query: query as never } }))),

  // Demo controls (DEMO_MODE only)
  demoState: async (): Promise<DemoState> => documented<DemoState>(await unwrap(http.GET('/api/v1/demo/integrations'))),
  demoReset: (): Promise<unknown> => unwrap(http.POST('/api/v1/demo/integrations/reset')),
  demoOutage: (source: IntegrationSource, failure: 'TIMEOUT' | 'HTTP_500' | null): Promise<unknown> =>
    unwrap(http.PUT('/api/v1/demo/integrations/outage', { body: { source, failure } })),
};

/** Opens a protected file (client or staff document) in a new tab via a short-lived object URL. */
export async function openProtectedFile(load: () => Promise<Response>, fileName: string): Promise<void> {
  const response = await load();
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = fileName;
  link.rel = 'noopener';
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
}
