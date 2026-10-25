import { Alert, Anchor, Button, Checkbox, Group, List, Modal, Stack, Text } from '@mantine/core';
import { IconAlertTriangle, IconClockHour4, IconSend } from '@tabler/icons-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useWatch, type UseFormReturn } from 'react-hook-form';
import { Link, useNavigate } from 'react-router-dom';
import type { DraftValues } from './formModel';
import { reactToCommandError, withFreshVersion } from '@/shared/api/commands';
import { api, type ConsentType } from '@/shared/api/endpoints';
import { isApiError, type ApiFieldError } from '@/shared/api/errors';
import { currentVersion, qk, storeApplication, useDictionaries, useProduct } from '@/shared/api/queries';
import type { ClientApplication, CompanyInfo, ConsentText } from '@/shared/api/types';
import { formatMoney, formatRate, formatTerm } from '@/shared/lib/format';
import { newId } from '@/shared/lib/ids';
import { fieldMeta, type FormStep } from '@/shared/lib/labels';
import { KeyValue, SectionCard } from '@/shared/ui/components';
import { toast } from '@/shared/ui/toast';

export function StepReview({
  app,
  form,
  flush,
  goTo,
  innReady,
  confirmInn,
}: {
  app: ClientApplication;
  form: UseFormReturn<DraftValues>;
  flush: () => Promise<boolean>;
  goTo: (step: FormStep) => Promise<void>;
  innReady: boolean;
  confirmInn: () => boolean;
}) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const dictionaries = useDictionaries();
  const product = useProduct(app.product_code);
  const values = useWatch({ control: form.control });
  const company = app.company as CompanyInfo | null;
  const [fieldErrors, setFieldErrors] = useState<ApiFieldError[]>([]);
  const [duplicateId, setDuplicateId] = useState<string | null>(null);
  const [consentText, setConsentText] = useState<ConsentText | null>(null);
  const [submitKey, setSubmitKey] = useState<string | null>(null);

  const calc = useQuery({
    queryKey: ['catalog', 'calculate', app.product_code, values.amount, values.term_months],
    queryFn: () => api.calculate({ product_code: app.product_code, amount: String(values.amount), term_months: Number(values.term_months) }),
    enabled: typeof values.amount === 'number' && typeof values.term_months === 'number' && values.amount > 0 && values.term_months > 0,
    retry: false,
  });

  const consent = useMutation({
    mutationFn: ({ type, give }: { type: ConsentType; give: boolean }) =>
      withFreshVersion(queryClient, app.id, (version) => (give ? api.giveConsent(app.id, type, version) : api.revokeConsent(app.id, type, version))),
    onSuccess: (res, vars) => {
      storeApplication(queryClient, res);
      setFieldErrors((errs) => errs.filter((e) => e.field !== `consents.${vars.type}`));
    },
    onError: (e) => toast.error(e, 'Не удалось сохранить согласие'),
  });

  const submit = useMutation({
    mutationFn: async (key: string) => {
      if (!confirmInn() || !(await flush()) || !confirmInn()) throw new Error('Не удалось сохранить заявку. Проверьте поля и ИНН перед отправкой.');
      const version = currentVersion(queryClient, app.id) ?? app.version;
      return api.submit(app.id, version, key);
    },
    retry: (count, error) => isApiError(error) && error.kind === 'network' && count < 2,
    retryDelay: 1500,
    onSuccess: (res) => {
      storeApplication(queryClient, res);
      toast.success('Заявка отправлена. Статус обновляется на этой странице.');
      navigate(`/client/applications/${res.id}`);
    },
    onError: (error) => {
      setSubmitKey(null);
      if (isApiError(error) && error.code === 'VALIDATION_FAILED') {
        setFieldErrors(error.fields);
        for (const f of error.fields) {
          if (f.field in form.getValues()) form.setError(f.field as keyof DraftValues, { type: 'server', message: f.message ?? 'Проверьте значение' });
        }
        document.getElementById('submit-errors')?.focus();
        return;
      }
      if (isApiError(error) && error.code === 'DUPLICATE_ACTIVE_APPLICATION') {
        setDuplicateId(typeof error.details.application_id === 'string' ? error.details.application_id : null);
        return;
      }
      reactToCommandError(error, queryClient, qk.application(app.id));
    },
  });

  const onSubmit = () => {
    if (submit.isPending || !innReady) return;
    // One key per user intent: an automatic network retry reuses it, a new click creates a new one.
    const key = submitKey ?? newId();
    setSubmitKey(key);
    setDuplicateId(null);
    submit.mutate(key);
  };

  const purposeTitle = dictionaries.data?.purposes.find((p) => p.code === values.purpose)?.title ?? values.purpose;
  const roleTitle = dictionaries.data?.representative_roles.find((r) => r.code === values.representative_role)?.title;
  const missingDocs = app.required_documents.filter((d) => !d.uploaded);
  const consentError = (type: string) => fieldErrors.find((e) => e.field === `consents.${type}`)?.message;
  const nonConsentErrors = fieldErrors.filter((e) => !e.field.startsWith('consents.'));
  const edit = (step: FormStep) => (
    <Button variant="subtle" size="compact-sm" onClick={() => void goTo(step)}>
      Изменить
    </Button>
  );

  return (
    <Stack gap="lg">
      {(nonConsentErrors.length > 0 || fieldErrors.length > 0) && (
        <Alert id="submit-errors" tabIndex={-1} color="red" icon={<IconAlertTriangle aria-hidden />} radius="lg" title="Проверьте заявку" role="alert">
          <List size="sm" spacing={4}>
            {fieldErrors.map((e) => {
              const meta = fieldMeta(e.field);
              return (
                <List.Item key={e.field}>
                  {meta.label}: {e.message}{' '}
                  {meta.step !== 'review' && (
                    <Anchor component="button" type="button" size="sm" onClick={() => void goTo(meta.step)}>
                      Исправить
                    </Anchor>
                  )}
                </List.Item>
              );
            })}
          </List>
        </Alert>
      )}
      {duplicateId !== null && (
        <Alert color="orange" icon={<IconAlertTriangle aria-hidden />} radius="lg" role="alert">
          У вас уже есть заявка на этот продукт по этой компании. Продолжите ее или отмените.{' '}
          {duplicateId && (
            <Anchor component={Link} to={`/client/applications/${duplicateId}`}>
              Открыть существующую заявку
            </Anchor>
          )}
        </Alert>
      )}

      <SectionCard title="Компания" actions={edit('company')}>
        <KeyValue
          items={[
            { label: 'Компания', value: company?.company_short_name ?? 'не найдена по ИНН' },
            { label: 'ИНН', value: <span className="num">{typeof app.form.applicant_inn === 'string' ? app.form.applicant_inn : 'не указан'}</span> },
            { label: 'Кем вы являетесь', value: roleTitle ?? 'не указано' },
          ]}
        />
      </SectionCard>

      <SectionCard title="Условия и финансы" actions={edit('terms')}>
        <KeyValue
          items={[
            { label: 'Продукт', value: app.product_name },
            { label: 'Цель', value: purposeTitle || 'не указана' },
            { label: 'Сумма', value: formatMoney(values.amount === '' ? null : values.amount) },
            { label: 'Срок', value: formatTerm(typeof values.term_months === 'number' ? values.term_months : null) },
            { label: 'Выручка в месяц', value: formatMoney(values.monthly_revenue_declared === '' ? null : values.monthly_revenue_declared) },
            { label: 'Платежи по кредитам в месяц', value: formatMoney(values.existing_monthly_payments_declared === '' ? null : values.existing_monthly_payments_declared) },
            {
              label: 'Поручительство собственника',
              value: values.owner_guarantee_agreed ? 'согласие есть' : 'нет согласия',
              hidden: !(product && app.applicant_type && product.requires_owner_guarantee_for.includes(app.applicant_type)),
            },
            { label: 'Залог', value: values.collateral_description || 'не указан', hidden: !product?.requires_collateral },
          ]}
        />
        {calc.data && (
          <Text mt="md" fw={600}>
            Ваш платеж будет около <span className="num">{formatMoney(calc.data.monthly_payment)}</span> в месяц при ставке от {formatRate(calc.data.rate_percent)}
          </Text>
        )}
      </SectionCard>

      <SectionCard title="Документы" actions={edit('documents')}>
        {app.required_documents.length === 0 ? (
          <Text size="sm">Документы не нужны.</Text>
        ) : (
          <Stack gap={4}>
            <Text size="sm">
              Загружено файлов: {app.documents.length}. {missingDocs.length === 0 ? 'Все нужные документы на месте.' : ''}
            </Text>
            {missingDocs.length > 0 && (
              <Alert color="yellow" icon={<IconAlertTriangle aria-hidden />} radius="md">
                Не хватает: {missingDocs.map((d) => d.title).join(', ')}. Без этих документов рассмотрение начнется только после их загрузки. Банк попросит их в
                кабинете.
              </Alert>
            )}
          </Stack>
        )}
      </SectionCard>

      <SectionCard title="Согласия">
        <Stack gap="md">
          <Text size="sm" c="dimmed">
            Без этих согласий банк не сможет рассмотреть заявку. Каждое фиксируется с временем и версией текста.
          </Text>
          {(dictionaries.data?.consents ?? []).map((c) => {
            const state = app.consents.find((s) => s.consent_type === c.code);
            const busy = consent.isPending && consent.variables.type === c.code;
            return (
              <Stack key={c.code} gap={2}>
                <Checkbox
                  id={`consent-${c.code}`}
                  checked={busy ? Boolean(consent.variables?.give) : Boolean(state?.given)}
                  disabled={busy}
                  onChange={(e) => consent.mutate({ type: c.code as ConsentType, give: e.currentTarget.checked })}
                  label={<Text fw={600} size="sm">{c.title}</Text>}
                  description={c.short_text}
                  error={consentError(c.code)}
                />
                <Anchor component="button" type="button" size="sm" ml={32} onClick={() => setConsentText(c)} style={{ alignSelf: 'flex-start' }}>
                  Что это значит
                </Anchor>
              </Stack>
            );
          })}
        </Stack>
      </SectionCard>

      <Alert color="blue" variant="light" radius="lg" icon={<IconClockHour4 aria-hidden />} title="Что будет дальше">
        После отправки мы проверим данные в госреестрах, налоговой и бюро кредитных историй. Обычно решение готово за несколько минут, для инвестиционного кредита до 24
        часов. Статус будет обновляться на странице заявки сам.
      </Alert>

      <Group>
        <Button size="lg" leftSection={<IconSend size={18} aria-hidden />} onClick={onSubmit} loading={submit.isPending} disabled={!innReady || !app.available_actions.includes('SUBMIT')}>
          Отправить заявку
        </Button>
      </Group>

      <Modal opened={consentText !== null} onClose={() => setConsentText(null)} title={consentText?.title ?? ''} size="lg">
        <Stack gap="sm">
          <Text size="sm" style={{ whiteSpace: 'pre-wrap' }}>
            {consentText?.full_text}
          </Text>
          <Text size="xs" c="dimmed">
            Версия текста {consentText?.text_version}
            {consentText?.ttl_days ? `, действует ${consentText.ttl_days} дней` : ''}
          </Text>
        </Stack>
      </Modal>
    </Stack>
  );
}
