import { Alert, Badge, Button, Group, NumberInput, Paper, Stack, Text, TextInput, Textarea, Title } from '@mantine/core';
import { IconClockHour4, IconInfoCircle, IconSend } from '@tabler/icons-react';
import { useState } from 'react';
import { Link, Navigate, useNavigate, useParams } from 'react-router-dom';
import { DocumentList, DocumentUpload } from './DocumentUpload';
import { useClientCommand } from '@/shared/api/commands';
import { api } from '@/shared/api/endpoints';
import { useClientApplication } from '@/shared/api/queries';
import type { ClientApplication, InfoAnswer, InfoItemView } from '@/shared/api/types';
import { plural } from '@/shared/lib/format';
import { ErrorState, PageHeader, PageSkeleton } from '@/shared/ui/components';

const MONEY_FIELDS = new Set(['monthly_revenue_declared', 'existing_monthly_payments_declared', 'collateral_value', 'own_contribution_amount', 'amount']);

export function InfoRequestPage() {
  const { id = '' } = useParams();
  const query = useClientApplication(id);
  if (query.isPending) return <PageSkeleton lines={3} />;
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} notFoundText="Заявка не найдена или у вас нет к ней доступа" />;
  const app = query.data;
  if (app.client_status !== 'ACTION_REQUIRED' || !app.info_request) return <Navigate to={`/client/applications/${app.id}`} replace />;
  return <InfoRequestForm app={app} />;
}

type Answers = Record<string, { text: string; value: string | number | '' }>;

function initialAnswers(items: InfoItemView[]): Answers {
  const out: Answers = {};
  for (const it of items) {
    const current = it.answer_value ?? it.current_value ?? '';
    out[it.id] = {
      text: it.answer_text ?? '',
      value: it.field_name && MONEY_FIELDS.has(it.field_name) && current !== '' ? Number(current) : current,
    };
  }
  return out;
}

function InfoRequestForm({ app }: { app: ClientApplication }) {
  const navigate = useNavigate();
  const request = app.info_request;
  const items = request?.items ?? [];
  const [answers, setAnswers] = useState<Answers>(() => initialAnswers(items));
  const [touched, setTouched] = useState(false);

  const docsFor = (item: InfoItemView) => app.documents.filter((d) => d.info_request_item_id === item.id);
  const isAnswered = (item: InfoItemView): boolean => {
    const a = answers[item.id];
    if (item.answer_type === 'DOCUMENT') return docsFor(item).length > 0;
    if (item.answer_type === 'FIELD') return a !== undefined && a.value !== '' && a.value !== null;
    return Boolean(a?.text.trim());
  };
  const missing = items.filter((it) => it.required && !isAnswered(it));

  const respond = useClientCommand<{ answers: InfoAnswer[] }>(app.id, ({ version, key, answers: list }) => api.respondInfo(app.id, version, list, key), {
    success: 'Ответ отправлен. Рассмотрение продолжится автоматически.',
    onSuccess: (res) => navigate(`/client/applications/${res.id}`),
  });

  const onSubmit = () => {
    setTouched(true);
    if (missing.length > 0) return;
    const list: InfoAnswer[] = items.map((it) => {
      const a = answers[it.id];
      if (it.answer_type === 'DOCUMENT') return { item_id: it.id, document_ids: docsFor(it).map((d) => d.id) };
      if (it.answer_type === 'FIELD') return { item_id: it.id, answer_value: a && a.value !== '' ? String(a.value) : null };
      return { item_id: it.id, answer_text: a?.text.trim() || null };
    });
    respond.trigger({ answers: list });
  };

  const set = (itemId: string, patch: Partial<{ text: string; value: string | number | '' }>) =>
    setAnswers((prev) => ({ ...prev, [itemId]: { text: prev[itemId]?.text ?? '', value: prev[itemId]?.value ?? '', ...patch } }));

  return (
    <>
      <PageHeader
        title={`Банку нужно ${items.length} ${plural(items.length, ['уточнение', 'уточнения', 'уточнений'])}`}
        subtitle={`Заявка ${app.application_number}, ${app.product_name}`}
        back={{ to: `/client/applications/${app.id}`, label: 'К статусу заявки' }}
      />
      <Stack gap="lg">
        <Alert color="orange" variant="light" radius="lg" icon={<IconClockHour4 aria-hidden />}>
          <Text fw={600}>{app.client_status_text.deadline_text ?? `Ответить до ${request?.due_text ?? ''}`}</Text>
          <Text size="sm">
            После отправки рассмотрение продолжится автоматически. Если вопрос непонятен, опишите это в ответе, специалист увидит ваш комментарий.
          </Text>
        </Alert>
        {items.map((item, idx) => {
          const a = answers[item.id];
          const showError = touched && item.required && !isAnswered(item);
          return (
            <Paper key={item.id} withBorder radius="lg" p={{ base: 'md', sm: 'lg' }} component="section" aria-labelledby={`item-${item.id}`}>
              <Stack gap="sm">
                <Group justify="space-between" wrap="wrap" gap="xs">
                  <Title order={2} size="h5" id={`item-${item.id}`}>
                    Вопрос {idx + 1}
                    {item.answer_type === 'DOCUMENT' && item.document_title ? `: ${item.document_title}` : ''}
                    {item.answer_type === 'FIELD' && item.field_label ? `: ${item.field_label}` : ''}
                  </Title>
                  <Badge variant="light" color={item.required ? 'orange' : 'gray'}>
                    {item.required ? 'обязательно' : 'по желанию'}
                  </Badge>
                </Group>
                <Text>{item.client_text}</Text>
                {item.answer_type === 'TEXT' && (
                  <Textarea
                    label="Ваш ответ"
                    autosize
                    minRows={3}
                    maxLength={4000}
                    value={a?.text ?? ''}
                    onChange={(e) => set(item.id, { text: e.currentTarget.value })}
                    error={showError ? 'Ответьте на этот вопрос' : undefined}
                  />
                )}
                {item.answer_type === 'FIELD' &&
                  (item.field_name && MONEY_FIELDS.has(item.field_name) ? (
                    <NumberInput
                      label={item.field_label ?? 'Значение'}
                      description={item.current_value ? 'Сейчас в заявке указано значение ниже. Исправьте его или подтвердите' : undefined}
                      value={typeof a?.value === 'number' ? a.value : a?.value === '' ? '' : Number(a?.value ?? '')}
                      onChange={(v) => set(item.id, { value: typeof v === 'number' ? v : '' })}
                      thousandSeparator=" "
                      suffix=" ₽"
                      allowDecimal={false}
                      allowNegative={false}
                      hideControls
                      maw={360}
                      error={showError ? 'Укажите значение' : undefined}
                    />
                  ) : (
                    <TextInput
                      label={item.field_label ?? 'Значение'}
                      value={String(a?.value ?? '')}
                      onChange={(e) => set(item.id, { value: e.currentTarget.value })}
                      maw={420}
                      error={showError ? 'Укажите значение' : undefined}
                    />
                  ))}
                {item.answer_type === 'DOCUMENT' && (
                  <Stack gap="xs">
                    <DocumentList appId={app.id} documents={docsFor(item)} canDelete={false} />
                    <DocumentUpload appId={app.id} documentType={item.document_type ?? 'OTHER'} infoRequestItemId={item.id} label={docsFor(item).length ? 'Добавить еще файл' : 'Загрузить файл'} />
                    {showError && (
                      <Text size="sm" c="red.8">
                        Загрузите документ
                      </Text>
                    )}
                  </Stack>
                )}
              </Stack>
            </Paper>
          );
        })}
        {touched && missing.length > 0 && (
          <Alert color="red" icon={<IconInfoCircle aria-hidden />} role="alert">
            Ответьте на все обязательные вопросы: осталось {missing.length}.
          </Alert>
        )}
        <Group>
          <Button size="lg" leftSection={<IconSend size={18} aria-hidden />} onClick={onSubmit} loading={respond.isPending} disabled={!app.available_actions.includes('RESPOND_INFO')}>
            Отправить ответ
          </Button>
          <Button component={Link} to={`/client/applications/${app.id}`} variant="subtle">
            Ответить позже
          </Button>
        </Group>
      </Stack>
    </>
  );
}
