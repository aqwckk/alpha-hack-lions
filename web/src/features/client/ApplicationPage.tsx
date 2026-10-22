import { Alert, Badge, Button, Group, Paper, SimpleGrid, Stack, Text, ThemeIcon, Timeline, Title } from '@mantine/core';
import {
  IconAlertTriangle,
  IconArrowRight,
  IconBulb,
  IconCircleCheck,
  IconClockHour4,
  IconMessage2,
  IconRefresh,
} from '@tabler/icons-react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { nextActionFor } from './ApplicationsListPage';
import { ProgressTracker } from './ProgressTracker';
import { ScheduleToggle } from './ScheduleTable';
import { SigningDocs } from './SigningDocs';
import { useClientCommand } from '@/shared/api/commands';
import { api } from '@/shared/api/endpoints';
import { qk, useClientApplication } from '@/shared/api/queries';
import type { ClientApplication, CompanyInfo } from '@/shared/api/types';
import { formatDate, formatDateTime, formatMoney, formatRate, formatTerm } from '@/shared/lib/format';
import { clientStatusMeta } from '@/shared/lib/labels';
import { ClientStatusBadge, ConfirmModal, ErrorState, KeyValue, PageHeader, PageSkeleton, SectionCard, clientStatusIcon } from '@/shared/ui/components';
import { Term } from '@/shared/ui/Term';
import { toast } from '@/shared/ui/toast';

export function ApplicationPage() {
  const { id = '' } = useParams();
  const query = useClientApplication(id);
  if (query.isPending) return <PageSkeleton lines={4} />;
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} notFoundText="Заявка не найдена или у вас нет к ней доступа" />;
  return <ApplicationView app={query.data} refreshing={query.isFetching} onRefresh={() => void query.refetch()} />;
}

/** Announces status changes to screen readers and refreshes notifications when the status moves. */
function useStatusAnnouncer(app: ClientApplication): string {
  const queryClient = useQueryClient();
  const previous = useRef(app.client_status);
  const [message, setMessage] = useState('');
  useEffect(() => {
    if (previous.current !== app.client_status) {
      previous.current = app.client_status;
      setMessage(`Статус заявки обновлен: ${app.client_status_text.title ?? clientStatusMeta(app.client_status).label}`);
      void queryClient.invalidateQueries({ queryKey: qk.notifications });
      void queryClient.invalidateQueries({ queryKey: qk.applications });
    }
  }, [app.client_status, app.client_status_text.title, queryClient]);
  return message;
}

function StatusHero({ app }: { app: ClientApplication }) {
  const meta = clientStatusMeta(app.client_status);
  const Icon = clientStatusIcon(app.client_status);
  const text = app.client_status_text;
  const action = nextActionFor(app);
  const hasAction =
    action.primary &&
    ((app.client_status === 'FILLING' && app.available_actions.includes('UPDATE_DRAFT')) ||
      (app.client_status === 'ACTION_REQUIRED' && app.available_actions.includes('RESPOND_INFO')) ||
      (app.client_status === 'DECISION_READY' && app.available_actions.includes('ACCEPT_OFFER')) ||
      (app.client_status === 'DOCUMENTS' && (app.available_actions.includes('REQUEST_SIGNING_CODE') || app.available_actions.includes('SIGN'))));
  const explain = useMutation({ mutationFn: () => api.explain(app.id), onError: (e) => toast.error(e) });
  const canExplain = ['DECISION_READY', 'REJECTED', 'ACTION_REQUIRED', 'SPECIALIST_REVIEW'].includes(app.client_status);

  return (
    <Paper withBorder radius="lg" p={{ base: 'md', sm: 'xl' }} style={{ borderColor: hasAction ? 'var(--mantine-color-orange-4)' : undefined }}>
      <Stack gap="md">
        <Group gap="md" align="flex-start" wrap="nowrap">
          <ThemeIcon color={meta.tone} variant="light" size={52} radius="md" aria-hidden>
            <Icon size={28} />
          </ThemeIcon>
          <Stack gap={4} style={{ minWidth: 0 }}>
            <Title order={2} size="h3">
              {text.title ?? meta.label}
            </Title>
            {meta.waiting && !hasAction && (
              <Group gap={8}>
                <span className="pulse-dot" aria-hidden />
                <Text size="sm" c="blue.8" fw={600}>
                  От вас ничего не нужно, страница обновится сама
                </Text>
              </Group>
            )}
          </Stack>
        </Group>
        <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="md">
          <div>
            <Text size="xs" tt="uppercase" c="dimmed" fw={700}>
              Что происходит
            </Text>
            <Text>{text.what_is_happening}</Text>
          </div>
          <div>
            <Text size="xs" tt="uppercase" c="dimmed" fw={700}>
              Что дальше
            </Text>
            <Text>{text.what_next}</Text>
          </div>
        </SimpleGrid>
        {text.notes.map((n) => (
          <Alert key={n} color="blue" variant="light" radius="md" icon={<IconBulb aria-hidden />}>
            {n}
          </Alert>
        ))}
        {text.deadline_text && (
          <Group gap={6}>
            <IconClockHour4 size={18} aria-hidden />
            <Text fw={600}>{text.deadline_text}</Text>
          </Group>
        )}
        {(hasAction || canExplain) && (
          <Group gap="sm">
            {hasAction && (
              <Button component={Link} to={action.to} size="md" color={app.client_status === 'ACTION_REQUIRED' ? 'orange' : undefined} rightSection={<IconArrowRight size={18} aria-hidden />}>
                {action.label}
              </Button>
            )}
            {canExplain && (
              <Button variant="subtle" onClick={() => explain.mutate()} loading={explain.isPending}>
                Объяснить проще
              </Button>
            )}
          </Group>
        )}
        {explain.data && (
          <Alert color="gray" variant="light" radius="md" title={explain.data.label ?? 'Простыми словами'}>
            {explain.data.text}
          </Alert>
        )}
      </Stack>
    </Paper>
  );
}

function RejectedBlock({ app }: { app: ClientApplication }) {
  if (!app.decision) return null;
  return (
    <SectionCard title="Почему банк отказал и что можно сделать">
      <Stack gap="md">
        {app.decision.reasons.length === 0 && <Text>Банк не может выдать кредит по этой заявке.</Text>}
        {app.decision.reasons.map((r, i) => (
          <Paper key={i} withBorder radius="md" p="md">
            <Group gap="xs" wrap="nowrap" align="flex-start">
              <IconAlertTriangle size={18} color="var(--mantine-color-red-7)" aria-hidden style={{ flex: 'none', marginTop: 3 }} />
              <Stack gap={4}>
                <Text>{r.text}</Text>
                {r.next_step && (
                  <Text fw={600} size="sm">
                    Что можно сделать: {r.next_step}
                  </Text>
                )}
              </Stack>
            </Group>
          </Paper>
        ))}
        <Group>
          <Button component={Link} to="/client/wizard">
            Подобрать другой вариант
          </Button>
          <Button component={Link} to="/client/applications" variant="default">
            Вернуться к заявкам
          </Button>
        </Group>
      </Stack>
    </SectionCard>
  );
}

function LoanBlock({ app }: { app: ClientApplication }) {
  const loan = app.loan;
  if (!loan) return null;
  const isLine = loan.operation_type === 'CREDIT_LINE_LIMIT';
  return (
    <SectionCard
      title={
        <Group gap="xs" component="span">
          <IconCircleCheck color="var(--mantine-color-green-7)" aria-hidden /> {isLine ? 'Детали кредитной линии' : 'Детали кредита'}
        </Group>
      }
    >
      <Stack gap="md">
        <KeyValue
          cols={3}
          items={[
            { label: isLine ? 'Лимит' : 'Сумма', value: <span className="money-xl">{formatMoney(loan.amount)}</span> },
            { label: 'Счет', value: <span className="num">{loan.account_number_masked}</span> },
            { label: 'Номер договора', value: loan.contract_number },
            { label: <Term k="rate">Ставка</Term>, value: formatRate(loan.rate_percent) },
            { label: 'Срок', value: formatTerm(loan.term_months) },
            { label: isLine ? 'Платеж, если взять весь лимит' : 'Ежемесячный платеж', value: formatMoney(loan.monthly_payment) },
            { label: 'Первый платеж', value: formatDate(loan.first_payment_date) },
            { label: 'Дата выдачи', value: formatDateTime(loan.issued_at) },
          ]}
        />
        <Text size="sm" c="dimmed">
          Платежи списываются со счета автоматически в дату платежа. В прототипе обслуживание кредита не моделируется.
        </Text>
        <ScheduleToggle appId={app.id} />
        {app.signing && (
          <div>
            <Text fw={600} mb="xs">
              Подписанные документы
            </Text>
            <SigningDocs appId={app.id} signing={app.signing} />
          </div>
        )}
      </Stack>
    </SectionCard>
  );
}

function ApplicationView({ app, refreshing, onRefresh }: { app: ClientApplication; refreshing: boolean; onRefresh: () => void }) {
  const announcement = useStatusAnnouncer(app);
  const [confirmWithdraw, setConfirmWithdraw] = useState(false);
  const withdraw = useClientCommand<Record<string, never>>(app.id, ({ version, key }) => api.withdraw(app.id, version, key), {
    success: 'Заявка отменена',
    onSuccess: () => setConfirmWithdraw(false),
  });
  const company = app.company as CompanyInfo | null;
  const form = app.form as Record<string, unknown>;
  const terminal = clientStatusMeta(app.client_status).terminal;

  return (
    <>
      <div aria-live="polite" className="visually-hidden">
        {announcement}
      </div>
      <PageHeader
        title={`Заявка ${app.application_number}`}
        subtitle={`${app.product_name}, ${formatMoney(typeof form.amount === 'string' ? form.amount : null)} на ${formatTerm(typeof form.term_months === 'number' ? form.term_months : null)}`}
        back={{ to: '/client/applications', label: 'Мои заявки' }}
        actions={
          <Group gap="xs">
            <ClientStatusBadge status={app.client_status} title={app.client_status_text.title} />
            <Button variant="subtle" size="compact-sm" leftSection={<IconRefresh size={14} aria-hidden />} onClick={onRefresh} loading={refreshing} aria-label="Обновить статус">
              Обновить
            </Button>
          </Group>
        }
      />
      <Stack gap="lg">
        <SectionCard>
          <ProgressTracker steps={app.progress} />
        </SectionCard>
        <StatusHero app={app} />
        {app.client_status === 'REJECTED' && <RejectedBlock app={app} />}
        {(app.client_status === 'WITHDRAWN' || app.client_status === 'EXPIRED') && (
          <Group>
            <Button component={Link} to="/client/wizard">
              Подать новую заявку
            </Button>
          </Group>
        )}
        <LoanBlock app={app} />

        <SimpleGrid cols={{ base: 1, md: 2 }} spacing="lg">
          <SectionCard title="Параметры заявки">
            <KeyValue
              cols={1}
              items={[
                { label: 'Продукт', value: app.product_name },
                { label: 'Цель', value: app.purpose_title },
                { label: 'Сумма', value: formatMoney(typeof form.amount === 'string' ? form.amount : null) },
                { label: 'Срок', value: formatTerm(typeof form.term_months === 'number' ? form.term_months : null) },
                { label: 'Компания', value: company?.company_short_name ?? 'не указана' },
                { label: 'Итоговые условия', value: app.final_terms ? `${formatMoney(app.final_terms.amount)} на ${formatTerm(app.final_terms.term_months)}, ${formatRate(app.final_terms.rate_percent)}, платеж ${formatMoney(app.final_terms.monthly_payment)}` : '', hidden: !app.final_terms },
              ]}
            />
          </SectionCard>
          <SectionCard title="История">
            <Timeline active={app.timeline.length - 1} bulletSize={18} lineWidth={2}>
              {app.timeline.map((t, i) => (
                <Timeline.Item key={`${t.client_status}-${i}`} title={t.title}>
                  <Text size="xs" c="dimmed">
                    {formatDateTime(t.at)}
                  </Text>
                </Timeline.Item>
              ))}
            </Timeline>
          </SectionCard>
        </SimpleGrid>

        {app.notifications.length > 0 && (
          <SectionCard title="Сообщения по заявке">
            <Stack gap="xs" component="ul" style={{ listStyle: 'none', padding: 0, margin: 0 }}>
              {app.notifications.slice(0, 6).map((n) => (
                <Group key={n.id} component="li" gap="sm" wrap="nowrap" align="flex-start">
                  <IconMessage2 size={18} aria-hidden style={{ flex: 'none', marginTop: 2 }} />
                  <div>
                    <Group gap={6}>
                      <Text size="sm" fw={600}>
                        {n.title}
                      </Text>
                      {!n.read && (
                        <Badge size="xs" color="brand">
                          новое
                        </Badge>
                      )}
                    </Group>
                    <Text size="sm">{n.body}</Text>
                    <Text size="xs" c="dimmed">
                      {formatDateTime(n.created_at)}
                    </Text>
                  </div>
                </Group>
              ))}
            </Stack>
          </SectionCard>
        )}

        {app.available_actions.includes('WITHDRAW') && !terminal && (
          <Group justify="flex-end">
            <Button variant="subtle" color="red" onClick={() => setConfirmWithdraw(true)}>
              Отменить заявку
            </Button>
          </Group>
        )}
      </Stack>
      <ConfirmModal
        opened={confirmWithdraw}
        onClose={() => setConfirmWithdraw(false)}
        onConfirm={() => withdraw.trigger({})}
        title="Отменить заявку?"
        confirmLabel="Отменить заявку"
        danger
        loading={withdraw.isPending}
      >
        <Text>Заявка будет закрыта, отменить это действие нельзя. Данные компании подставятся в новую заявку автоматически.</Text>
      </ConfirmModal>
    </>
  );
}
