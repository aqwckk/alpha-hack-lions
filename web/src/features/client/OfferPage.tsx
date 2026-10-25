import { Alert, Badge, Button, Group, Modal, Paper, Select, SimpleGrid, Stack, Text, Title } from '@mantine/core';
import { IconAlertTriangle, IconCheck, IconClockHour4, IconInfoCircle } from '@tabler/icons-react';
import { useState } from 'react';
import { Link, Navigate, useNavigate, useParams } from 'react-router-dom';
import { ScheduleLoader } from './ScheduleTable';
import { useClientCommand } from '@/shared/api/commands';
import { api } from '@/shared/api/endpoints';
import { useClientApplication, useDictionaries } from '@/shared/api/queries';
import type { ClientApplication, OfferView, OptionView } from '@/shared/api/types';
import { formatMoney, formatRate, formatTerm } from '@/shared/lib/format';
import { GLOSSARY } from '@/shared/lib/glossary';
import { OPTION_TYPE_LABELS } from '@/shared/lib/labels';
import { ConfirmModal, ErrorState, KeyValue, PageHeader, PageSkeleton, SectionCard } from '@/shared/ui/components';
import { Hint, Term } from '@/shared/ui/Term';

export function OfferPage() {
  const { id = '' } = useParams();
  const query = useClientApplication(id);
  if (query.isPending) return <PageSkeleton lines={3} />;
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} notFoundText="Заявка не найдена или у вас нет к ней доступа" />;
  const app = query.data;
  if (app.client_status === 'DOCUMENTS') return <Navigate to={`/client/applications/${app.id}/signing`} replace />;
  if (!app.offer || app.client_status !== 'DECISION_READY') return <Navigate to={`/client/applications/${app.id}`} replace />;
  return <OfferView app={app} offer={app.offer} />;
}

function optionTitle(o: OptionView): string {
  if (o.option_type === 'REQUESTED') return o.product_name;
  return `${OPTION_TYPE_LABELS[o.option_type] ?? o.product_name}`;
}

export function OfferOptionCard({
  option,
  selected,
  onSelect,
  onSchedule,
  selectable,
}: {
  option: OptionView;
  selected: boolean;
  onSelect: () => void;
  onSchedule: () => void;
  selectable: boolean;
}) {
  const isLine = option.product_code === 'CREDIT_LINE';
  return (
    <Paper className="option-card" data-recommended={option.recommended} data-selected={selected} component="article" aria-label={optionTitle(option)}>
      <Group justify="space-between" align="flex-start" wrap="wrap" gap="xs">
        <div>
          <Title order={3} size="h4">
            {optionTitle(option)}
          </Title>
          {optionTitle(option) !== option.product_name && (
            <Text size="sm" c="dimmed">
              {option.product_name}
            </Text>
          )}
        </div>
        {option.recommended && (
          <Badge color="green" variant="filled" leftSection={<IconCheck size={12} aria-hidden />}>
            Рекомендуем
          </Badge>
        )}
      </Group>
      {option.difference_text && (
        <Text fw={600} c="brand.8">
          {option.difference_text}
        </Text>
      )}
      <div>
        <Text size="sm" c="dimmed">
          {isLine ? 'Платеж, если взять весь лимит на 12 месяцев' : <Term k="payment">Ежемесячный платеж</Term>}
        </Text>
        <Text className="money-xl">{formatMoney(isLine && option.credit_line ? option.credit_line.payment_full_limit_12m : option.monthly_payment)}</Text>
      </div>
      <KeyValue
        cols={2}
        items={[
          { label: isLine ? 'Лимит' : 'Сумма', value: <b className="num">{formatMoney(option.amount)}</b> },
          { label: 'Срок', value: formatTerm(option.term_months) },
          { label: <Term k="rate">Ставка</Term>, value: formatRate(option.rate_percent) },
          { label: <Term k="overpayment">Переплата</Term>, value: formatMoney(option.overpayment), hidden: isLine },
          { label: 'Всего выплатить', value: formatMoney(option.total_payment), hidden: isLine },
          {
            label: 'Проценты в месяц при полном использовании',
            value: option.credit_line ? formatMoney(option.credit_line.monthly_interest_full_use) : '',
            hidden: !isLine || !option.credit_line,
          },
        ]}
      />
      {(option.requires_owner_guarantee || option.requires_collateral || isLine) && (
        <Stack gap={4}>
          {option.requires_owner_guarantee && (
            <Group gap={4}>
              <Text size="sm">Нужно поручительство собственника</Text>
              <Hint term="Поручительство" hint={GLOSSARY.guarantee} />
            </Group>
          )}
          {option.requires_collateral && (
            <Group gap={4}>
              <Text size="sm">Нужен залог</Text>
              <Hint term="Залог" hint={GLOSSARY.collateral} />
            </Group>
          )}
          {isLine && (
            <Group gap={4}>
              <Text size="sm">
                Деньги можно брать частями, каждый транш вернуть за {option.tranche_max_term_months ?? 12} месяцев. Проценты только на взятую сумму.
              </Text>
              <Hint term="Кредитная линия" hint={GLOSSARY.creditLine} />
            </Group>
          )}
        </Stack>
      )}
      <Group mt="auto" gap="sm">
        {selectable && (
          <Button variant={selected ? 'filled' : 'light'} onClick={onSelect} aria-pressed={selected} leftSection={selected ? <IconCheck size={16} aria-hidden /> : undefined}>
            {selected ? 'Выбран' : 'Выбрать этот вариант'}
          </Button>
        )}
        <Button variant="subtle" onClick={onSchedule}>
          График платежей
        </Button>
      </Group>
    </Paper>
  );
}

function OfferView({ app, offer }: { app: ClientApplication; offer: OfferView }) {
  const navigate = useNavigate();
  const dictionaries = useDictionaries();
  const recommended = offer.options.find((o) => o.recommended) ?? offer.options[0];
  const [selectedId, setSelectedId] = useState<string | undefined>(recommended?.id);
  const [scheduleFor, setScheduleFor] = useState<OptionView | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [declineOpen, setDeclineOpen] = useState(false);
  const [declineReason, setDeclineReason] = useState<string | null>(null);
  const selected = offer.options.find((o) => o.id === selectedId);
  const counter = offer.outcome === 'COUNTER_OFFER';
  const canAccept = app.available_actions.includes('ACCEPT_OFFER');
  const canDecline = app.available_actions.includes('DECLINE_OFFER');

  const accept = useClientCommand<{ optionId: string }>(app.id, ({ version, key, optionId }) => api.acceptOffer(app.id, version, optionId, key), {
    success: 'Условия приняты. Готовим документы для подписания.',
    onSuccess: (res) => navigate(`/client/applications/${res.id}/signing`),
    onError: (e) => {
      if (e.code === 'OFFER_EXPIRED') {
        setConfirm(false);
        navigate(`/client/applications/${app.id}`);
      }
      return false;
    },
  });
  const decline = useClientCommand<{ reason: string | null }>(app.id, ({ version, key, reason }) => api.declineOffer(app.id, version, reason, key), {
    success: 'Вы отказались от предложения',
    onSuccess: (res) => navigate(`/client/applications/${res.id}`),
  });

  return (
    <>
      <PageHeader
        title={counter ? 'Банк предлагает другие условия' : 'Заявка одобрена'}
        subtitle={`Заявка ${app.application_number}, ${app.product_name}`}
        back={{ to: `/client/applications/${app.id}`, label: 'К статусу заявки' }}
      />
      <Stack gap="lg">
        <Alert color="blue" variant="light" radius="lg" icon={<IconClockHour4 aria-hidden />}>
          <Group gap={4}>
            <Text fw={600}>Предложение действует до {offer.expires_text}</Text>
            <Hint term="Срок действия предложения" hint={GLOSSARY.offerExpiry} />
          </Group>
          <Text size="sm">{app.client_status_text.what_is_happening}</Text>
        </Alert>

        {counter && (
          <SectionCard title="Вы просили">
            <Stack gap="sm">
              <KeyValue
                cols={3}
                items={[
                  { label: 'Сумма', value: formatMoney(offer.requested.amount) },
                  { label: 'Срок', value: formatTerm(offer.requested.term_months) },
                  { label: 'Платеж в месяц', value: formatMoney(offer.requested.monthly_payment) },
                ]}
              />
              {offer.reasons.map((r, i) => (
                <Alert key={i} color="yellow" variant="light" icon={<IconInfoCircle aria-hidden />} radius="md" title={i === 0 ? 'Почему другие условия' : 'Еще вариант'}>
                  <Text size="sm">{r.text}</Text>
                  {r.next_step && (
                    <Text size="sm" mt={4}>
                      {r.next_step}
                    </Text>
                  )}
                </Alert>
              ))}
            </Stack>
          </SectionCard>
        )}

        {!counter &&
          offer.reasons.map((r, i) => (
            <Alert key={i} color="gray" variant="light" icon={<IconInfoCircle aria-hidden />} radius="md">
              {r.text} {r.next_step}
            </Alert>
          ))}

        <div>
          <Title order={2} size="h4" mb="sm">
            {offer.options.length > 1 ? 'Варианты банка: выберите подходящий' : 'Условия банка'}
          </Title>
          {offer.options.some((option) => option.recommended) && <Text size="sm" mb="sm">Рекомендация учитывает скорость и простоту оформления. Минимальная стоимость не гарантируется, сравните переплату и требования.</Text>}
          {offer.options.filter((option) => option.product_code !== 'CREDIT_LINE').length > 1 && <Text size="sm" mb="sm">Переплата по вариантам: {offer.options.filter((option) => option.product_code !== 'CREDIT_LINE').map((option) => `${optionTitle(option)}: ${formatMoney(option.overpayment)}`).join('; ')}.</Text>}
          <SimpleGrid cols={{ base: 1, sm: offer.options.length > 1 ? 2 : 1, lg: Math.min(offer.options.length, 3) }} spacing="md">
            {offer.options.map((o) => (
              <OfferOptionCard
                key={o.id}
                option={o}
                selected={o.id === selectedId}
                selectable={offer.options.length > 1}
                onSelect={() => setSelectedId(o.id)}
                onSchedule={() => setScheduleFor(o)}
              />
            ))}
          </SimpleGrid>
        </div>

        <Group gap="sm">
          {canAccept && (
            <Button size="lg" onClick={() => setConfirm(true)} disabled={!selected}>
              {counter ? 'Выбрать этот вариант' : 'Принять условия'}
            </Button>
          )}
          {canDecline && (
            <Button size="lg" variant="default" onClick={() => setDeclineOpen(true)}>
              Отказаться
            </Button>
          )}
          <Button component={Link} to={`/client/applications/${app.id}`} variant="subtle">
            Решу позже
          </Button>
        </Group>
        <Text size="sm" c="dimmed">
          Ставка назначена банком по результатам проверки. Платеж одинаковый весь срок, досрочное погашение в прототипе не моделируется.
        </Text>
      </Stack>

      <ConfirmModal
        opened={confirm}
        onClose={() => setConfirm(false)}
        onConfirm={() => selected && accept.trigger({ optionId: selected.id })}
        title="Подтвердите выбор"
        confirmLabel="Подтверждаю"
        loading={accept.isPending}
      >
        {selected && (
          <Stack gap="xs">
            <Text>
              Вы выбираете: <b>{optionTitle(selected)}</b>, {formatMoney(selected.amount)} на {formatTerm(selected.term_months)} под {formatRate(selected.rate_percent)},
              платеж {formatMoney(selected.monthly_payment)} в месяц.
            </Text>
            <Text size="sm" c="dimmed">
              Дальше банк подготовит документы для подписания. Подписать их можно будет здесь, в кабинете.
            </Text>
          </Stack>
        )}
      </ConfirmModal>

      <Modal opened={declineOpen} onClose={() => setDeclineOpen(false)} title="Отказаться от предложения?" centered>
        <Stack gap="md">
          <Text size="sm">Заявка будет закрыта. Если передумаете, можно будет подать новую: данные компании подставятся автоматически.</Text>
          <Select
            label="Почему отказываетесь"
            description="Необязательно, это поможет банку сделать предложения лучше"
            data={(dictionaries.data?.offer_decline_reasons ?? []).map((r) => ({ value: r.code, label: r.title }))}
            value={declineReason}
            onChange={setDeclineReason}
            clearable
          />
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setDeclineOpen(false)} data-autofocus>
              Отмена
            </Button>
            <Button color="red" leftSection={<IconAlertTriangle size={16} aria-hidden />} loading={decline.isPending} onClick={() => decline.trigger({ reason: declineReason })}>
              Отказаться
            </Button>
          </Group>
        </Stack>
      </Modal>

      <Modal opened={scheduleFor !== null} onClose={() => setScheduleFor(null)} title={scheduleFor ? `График платежей: ${optionTitle(scheduleFor)}` : ''} size="xl">
        {scheduleFor && <ScheduleLoader appId={app.id} optionId={scheduleFor.id} />}
      </Modal>
    </>
  );
}
