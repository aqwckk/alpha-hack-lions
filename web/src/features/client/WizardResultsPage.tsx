import { Alert, Badge, Button, Divider, Group, List, NumberInput, Paper, SimpleGrid, Stack, Text, Title } from '@mantine/core';
import { useDebouncedValue } from '@mantine/hooks';
import { IconBulb, IconCalendarTime, IconCheck, IconInfoCircle } from '@tabler/icons-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Navigate, useLocation, useNavigate } from 'react-router-dom';
import type { WizardState } from './WizardPage';
import { api } from '@/shared/api/endpoints';
import { storeApplication, useDictionaries } from '@/shared/api/queries';
import type { ProductCard } from '@/shared/api/types';
import { formatDate, formatMoney, formatRate, formatTerm } from '@/shared/lib/format';
import { newId } from '@/shared/lib/ids';
import { checkInn } from '@/shared/lib/inn';
import { EmptyState, ErrorState, PageHeader, PageSkeleton } from '@/shared/ui/components';
import { Term } from '@/shared/ui/Term';
import { toast } from '@/shared/ui/toast';

export function WizardResultsPage() {
  const location = useLocation();
  const state = location.state as WizardState | null;
  if (!state?.request) return <Navigate to="/client/wizard" replace />;
  return <Results state={state} />;
}

function Results({ state }: { state: WizardState }) {
  const { request } = state;
  const navigate = useNavigate();
  const dictionaries = useDictionaries();
  const purposeTitle = dictionaries.data?.purposes.find((p) => p.code === request.purpose)?.title ?? request.purpose;
  const inn = request.inn && checkInn(request.inn).ok ? request.inn : undefined;
  const match = useQuery({
    queryKey: ['catalog', 'match', request],
    queryFn: () =>
      api.match({
        purpose: request.purpose,
        amount: String(request.amount),
        term_months: request.term_months,
        ...(request.applicant_type !== 'ANY' ? { applicant_type: request.applicant_type } : {}),
        ...(inn ? { inn } : {}),
      }),
  });
  const edit = () => navigate('/client/wizard', { state });

  return (
    <>
      <PageHeader
        title="Подходящие варианты"
        back={{ to: '/client/applications', label: 'Мои заявки' }}
        subtitle={
          <>
            {purposeTitle}, {formatMoney(request.amount)} на {formatTerm(request.term_months)}.{' '}
            <Button variant="subtle" size="compact-sm" onClick={edit}>
              Изменить запрос
            </Button>
          </>
        }
      />
      <Stack gap="md">
        {match.isPending && <PageSkeleton lines={2} />}
        {match.isError && <ErrorState error={match.error} onRetry={() => void match.refetch()} />}
        {match.data && (
          <>
            {match.data.hints.map((hint) => (
              <Alert key={hint} color="blue" variant="light" radius="lg" icon={<IconBulb aria-hidden />}>
                {hint}
              </Alert>
            ))}
            {match.data.cards.length === 0 ? (
              <EmptyState
                title="Подходящих вариантов нет"
                text={match.data.empty_text ?? 'Попробуйте изменить сумму, срок или цель кредита.'}
                action={<Button onClick={edit}>Изменить запрос</Button>}
              />
            ) : (
              <SimpleGrid cols={{ base: 1, md: match.data.cards.length > 1 ? 2 : 1 }} spacing="md">
                {match.data.cards.map((card) => (
                  <ProductResult key={card.product_code} card={card} state={state} />
                ))}
              </SimpleGrid>
            )}
            <Text size="sm" c="dimmed">
              {match.data.disclaimer}.
            </Text>
          </>
        )}
      </Stack>
    </>
  );
}

function clamp(n: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, n));
}

function ProductResult({ card, state }: { card: ProductCard; state: WizardState }) {
  const { request } = state;
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const amountMin = Number(card.amount_min);
  const amountMax = Number(card.amount_max);
  const [amount, setAmount] = useState<number>(clamp(request.amount, amountMin, amountMax));
  const [term, setTerm] = useState<number>(card.term_months);
  const [debounced] = useDebouncedValue({ amount, term }, 300);
  const validAmount = debounced.amount >= amountMin && debounced.amount <= amountMax;
  const validTerm = debounced.term >= card.term_min_months && debounced.term <= card.term_max_months;
  const changed = debounced.amount !== clamp(request.amount, amountMin, amountMax) || debounced.term !== card.term_months;

  const calc = useQuery({
    queryKey: ['catalog', 'calculate', card.product_code, debounced.amount, debounced.term],
    queryFn: () => api.calculate({ product_code: card.product_code, amount: String(debounced.amount), term_months: debounced.term }),
    enabled: changed && validAmount && validTerm,
    placeholderData: (prev) => prev,
  });
  const payment = changed && calc.data ? calc.data.monthly_payment : card.monthly_payment_from;
  const overpayment = changed && calc.data ? calc.data.overpayment : card.overpayment_from;

  const apply = useMutation({
    mutationFn: async () => {
      const key = newId();
      void api
        .trackWizard({
          event_type: 'PRODUCT_SELECTED',
          wizard_session_id: state.wizardId,
          product_code: card.product_code,
          purpose: request.purpose,
          amount: String(amount),
          term_months: term,
          rank: card.rank,
          was_recommended: card.recommended,
        })
        .catch(() => undefined);
      let app = await api.createApplication(
        { product_code: card.product_code, purpose: request.purpose, amount: String(amount), term_months: term, wizard_session_id: state.wizardId },
        key,
      );
      const inn = request.inn && checkInn(request.inn).ok ? request.inn : null;
      if (inn) {
        try {
          app = (await api.prefill(app.id, inn, app.version)).application;
        } catch {
          // prefill is repeated on the company step; the draft is already saved
        }
      }
      return app;
    },
    onSuccess: (app) => {
      storeApplication(queryClient, app);
      navigate(`/client/applications/${app.id}/edit/company`);
    },
    onError: (e) => toast.error(e, 'Не удалось создать заявку'),
  });

  return (
    <Paper withBorder radius="lg" p="lg" className="option-card" data-recommended={card.recommended} data-disabled={!card.available}>
      <Group justify="space-between" align="flex-start" wrap="wrap" gap="xs">
        <div>
          <Title order={2} size="h3">
            {card.name}
          </Title>
          <Text size="sm" c="dimmed">
            {card.description}
          </Text>
        </div>
        {card.recommended && card.available && (
          <Badge color="green" variant="filled" leftSection={<IconCheck size={12} aria-hidden />}>
            Рекомендуем
          </Badge>
        )}
      </Group>

      {!card.available && (
        <Alert color="orange" variant="light" icon={<IconCalendarTime aria-hidden />} radius="md">
          {card.unavailable_reason}
          {card.eligible_date ? ` Будет доступен с ${formatDate(card.eligible_date)}.` : ''}
        </Alert>
      )}

      <div>
        <Text size="sm" c="dimmed">
          <Term k="payment">Платеж в месяц</Term> от
        </Text>
        <Text className="money-xl" aria-live="polite">
          {formatMoney(payment)}
        </Text>
        <Group gap="lg" mt={4}>
          <Text size="sm">
            <Term k="rateFrom">Ставка от</Term> <b>{formatRate(card.rate_from_percent)}</b>
          </Text>
          <Text size="sm">
            <Term k="overpayment">Переплата</Term> <b className="num">{formatMoney(overpayment)}</b>
          </Text>
        </Group>
        {card.term_note && (
          <Text size="xs" c="dimmed" mt={4}>
            {card.term_note}
          </Text>
        )}
      </div>

      <SimpleGrid cols={2} spacing="sm">
        <NumberInput
          label="Сумма"
          description={`от ${formatMoney(card.amount_min)} до ${formatMoney(card.amount_max)}`}
          value={amount}
          onChange={(v) => setAmount(typeof v === 'number' ? v : Number(String(v).replace(/\D/g, '')) || 0)}
          thousandSeparator=" "
          suffix=" ₽"
          allowDecimal={false}
          allowNegative={false}
          step={Number(card.amount_step)}
          error={amount < amountMin || amount > amountMax ? 'Вне границ продукта' : undefined}
        />
        <NumberInput
          label="Срок, месяцев"
          description={`от ${card.term_min_months} до ${card.term_max_months}`}
          value={term}
          onChange={(v) => setTerm(typeof v === 'number' ? v : Number(v) || 0)}
          allowDecimal={false}
          allowNegative={false}
          min={card.term_min_months}
          max={card.term_max_months}
          error={term < card.term_min_months || term > card.term_max_months ? 'Вне границ продукта' : undefined}
        />
      </SimpleGrid>

      <Divider />
      <Group gap={6}>
        <IconInfoCircle size={16} aria-hidden />
        <Text size="sm" fw={600}>
          {card.decision_speed}
        </Text>
      </Group>
      {(card.requirements.length > 0 || card.required_documents.length > 0) && (
        <div>
          <Text size="sm" fw={600} mb={4}>
            Что понадобится
          </Text>
          <List size="sm" spacing={2}>
            {card.requirements.map((r) => (
              <List.Item key={r}>{r}</List.Item>
            ))}
          </List>
        </div>
      )}
      {card.requirements.length === 0 && (
        <Text size="sm" c="dimmed">
          Документы не нужны: сведения о бизнесе банк получит сам.
        </Text>
      )}

      <Group mt="auto">
        <Button
          size="md"
          variant={card.available ? 'filled' : 'default'}
          onClick={() => apply.mutate()}
          loading={apply.isPending}
          disabled={amount < amountMin || amount > amountMax || term < card.term_min_months || term > card.term_max_months}
        >
          {card.available ? 'Оформить' : 'Все равно оформить'}
        </Button>
      </Group>
    </Paper>
  );
}
