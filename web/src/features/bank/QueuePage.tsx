import { Badge, Button, Group, Pagination, Paper, Select, SimpleGrid, Stack, Table, Tabs, Text, TextInput, Tooltip } from '@mantine/core';
import { IconAlertTriangle, IconClockHour4, IconFilter, IconRefresh, IconSearch } from '@tabler/icons-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useUser } from '@/features/auth/AuthProvider';
import { reactToCommandError } from '@/shared/api/commands';
import { moscowDateBoundary } from '@/shared/lib/dateFilters';
import { api } from '@/shared/api/endpoints';
import { qk } from '@/shared/api/queries';
import type { StaffListItem } from '@/shared/api/types';
import { formatDateTime, formatDuration, formatMoney, formatTerm } from '@/shared/lib/format';
import { newId } from '@/shared/lib/ids';
import { INTERNAL_STATUS, OUTCOME_LABELS, PRODUCT_NAMES, productName } from '@/shared/lib/labels';
import { EmptyState, ErrorState, InternalStatusBadge, PageHeader, PageSkeleton } from '@/shared/ui/components';

type Tab = 'queue' | 'mine' | 'errors' | 'decided' | 'approval' | 'all';

const TAB_LABELS: Record<Tab, string> = {
  queue: 'Очередь',
  mine: 'Мои',
  errors: 'Ошибки обработки',
  decided: 'Решенные мной',
  approval: 'На согласовании',
  all: 'Все заявки',
};

const EMPTY_TEXT: Record<Tab, string> = {
  queue: 'Очередь пуста. Все заявки решены автоматически или уже в работе.',
  mine: 'У вас нет заявок в работе. Возьмите заявку из очереди.',
  errors: 'Заявок с ошибкой обработки нет: все внешние источники отвечают.',
  decided: 'Вы еще не приняли ни одного решения.',
  approval: 'Нет решений, ожидающих подтверждения.',
  all: 'Заявок по фильтру нет.',
};

const FILTER_KEYS = ['status', 'product_code', 'outcome', 'mode', 'number', 'inn', 'created_from', 'created_to'] as const;

export function QueuePage({ defaultTab }: { defaultTab?: Tab }) {
  const user = useUser();
  const isRisk = user.role === 'RISK_MANAGER';
  const tabs: Tab[] = isRisk ? ['approval', 'queue', 'errors', 'all'] : ['queue', 'mine', 'errors', 'decided'];
  const [params, setParams] = useSearchParams();
  const rawTab = params.get('tab');
  const tab: Tab = rawTab && (tabs as string[]).includes(rawTab) ? (rawTab as Tab) : (defaultTab ?? tabs[0] ?? 'queue');
  const page = Math.max(1, Number(params.get('page')) || 1);
  const filters: Record<string, string> = {};
  for (const k of FILTER_KEYS) {
    const v = params.get(k);
    if (v) filters[k] = v;
  }
  const [showFilters, setShowFilters] = useState(Object.keys(filters).length > 0 || tab === 'all');
  const queryParams = { tab, page, page_size: 20, ...filters, created_from: moscowDateBoundary(filters.created_from), created_to: moscowDateBoundary(filters.created_to, true) };
  const query = useQuery({ queryKey: qk.bankList(queryParams), queryFn: () => api.bankList(queryParams), refetchInterval: 15000, placeholderData: (prev) => prev });

  const update = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(patch)) {
      if (v) next.set(k, v);
      else next.delete(k);
    }
    if (!('page' in patch)) next.delete('page');
    setParams(next, { replace: false });
  };

  const counters = query.data?.counters ?? {};
  const title = defaultTab === 'all' ? 'Все заявки' : 'Очередь заявок';

  return (
    <>
      <PageHeader
        title={title}
        subtitle={isRisk ? 'Контроль заявок, согласование решений по принципу 4 глаз' : 'Заявки для ручного рассмотрения, отсортированы по сроку SLA'}
        actions={
          <Group gap="xs">
            <Button variant="default" leftSection={<IconFilter size={16} aria-hidden />} onClick={() => setShowFilters((v) => !v)} aria-expanded={showFilters}>
              Фильтры
            </Button>
            <Button variant="subtle" leftSection={<IconRefresh size={16} aria-hidden />} onClick={() => void query.refetch()} loading={query.isFetching}>
              Обновить
            </Button>
          </Group>
        }
      />
      <Stack gap="md">
        <Tabs value={tab} onChange={(v) => v && update({ tab: v })} keepMounted={false}>
          <Tabs.List style={{ flexWrap: 'wrap' }}>
            {tabs.map((t) => (
              <Tabs.Tab
                key={t}
                value={t}
                rightSection={
                  counters[t] !== undefined ? (
                    <Badge size="sm" variant={t === tab ? 'filled' : 'light'} color={t === 'errors' && (counters[t] ?? 0) > 0 ? 'red' : 'gray'} circle={false}>
                      {counters[t]}
                    </Badge>
                  ) : undefined
                }
              >
                {TAB_LABELS[t]}
              </Tabs.Tab>
            ))}
          </Tabs.List>
        </Tabs>
        {showFilters && <Filters filters={filters} onApply={(f) => update(f)} showStatus={tab === 'all'} />}
        {query.isPending && <PageSkeleton lines={3} />}
        {query.isError && <ErrorState error={query.error} onRetry={() => void query.refetch()} />}
        {query.data && query.data.items.length === 0 && <EmptyState title="Пусто" text={EMPTY_TEXT[tab]} />}
        {query.data && query.data.items.length > 0 && (
          <>
            <QueueTable items={query.data.items} tab={tab} canTake={user.role === 'UNDERWRITER'} />
            {query.data.total > query.data.page_size && (
              <Group justify="space-between">
                <Text size="sm" c="dimmed">
                  Всего: {query.data.total}
                </Text>
                <Pagination total={Math.ceil(query.data.total / query.data.page_size)} value={page} onChange={(p) => update({ page: String(p) })} aria-label="Страницы" />
              </Group>
            )}
          </>
        )}
      </Stack>
    </>
  );
}

function Filters({ filters, onApply, showStatus }: { filters: Record<string, string>; onApply: (f: Record<string, string | null>) => void; showStatus: boolean }) {
  const [draft, setDraft] = useState<Record<string, string>>(filters);
  const set = (k: string, v: string | null) => setDraft((d) => ({ ...d, [k]: v ?? '' }));
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const out: Record<string, string | null> = {};
    for (const k of FILTER_KEYS) out[k] = draft[k]?.trim() || null;
    onApply(out);
  };
  const reset = () => {
    setDraft({});
    const out: Record<string, string | null> = {};
    for (const k of FILTER_KEYS) out[k] = null;
    onApply(out);
  };
  return (
    <Paper withBorder radius="lg" p="md" component="form" onSubmit={submit} aria-label="Фильтры заявок">
      <SimpleGrid cols={{ base: 1, xs: 2, md: 4 }} spacing="sm">
        <TextInput label="Номер заявки" placeholder="A-000123" value={draft.number ?? ''} onChange={(e) => set('number', e.currentTarget.value)} />
        <TextInput label="ИНН" inputMode="numeric" value={draft.inn ?? ''} onChange={(e) => set('inn', e.currentTarget.value.replace(/\D/g, ''))} />
        <Select label="Продукт" clearable data={Object.entries(PRODUCT_NAMES).map(([value, label]) => ({ value, label }))} value={draft.product_code || null} onChange={(v) => set('product_code', v)} />
        {showStatus && (
          <Select label="Статус" clearable searchable data={Object.entries(INTERNAL_STATUS).filter(([k]) => k !== 'DRAFT').map(([value, m]) => ({ value, label: m.label }))} value={draft.status || null} onChange={(v) => set('status', v)} />
        )}
        <Select label="Исход решения" clearable data={['APPROVED', 'COUNTER_OFFER', 'DECLINED'].map((v) => ({ value: v, label: OUTCOME_LABELS[v] ?? v }))} value={draft.outcome || null} onChange={(v) => set('outcome', v)} />
        <Select label="Режим решения" clearable data={[{ value: 'AUTO', label: 'Автоматически' }, { value: 'MANUAL', label: 'Специалистом' }]} value={draft.mode || null} onChange={(v) => set('mode', v)} />
        <TextInput label="Создана с (МСК)" type="date" value={draft.created_from ?? ''} onChange={(e) => set('created_from', e.currentTarget.value)} />
        <TextInput label="Создана по (МСК, включительно)" type="date" value={draft.created_to ?? ''} onChange={(e) => set('created_to', e.currentTarget.value)} />
      </SimpleGrid>
      <Group mt="md" gap="sm">
        <Button type="submit" leftSection={<IconSearch size={16} aria-hidden />}>
          Применить
        </Button>
        <Button variant="subtle" onClick={reset}>
          Сбросить
        </Button>
      </Group>
    </Paper>
  );
}

function SlaCell({ item }: { item: StaffListItem }) {
  if (!item.review_due_at) return <Text size="sm" c="dimmed">нет</Text>;
  if (item.sla_breached) {
    return (
      <Badge color="red" variant="light" leftSection={<IconAlertTriangle size={12} aria-hidden />}>
        просрочено: {formatDateTime(item.review_due_at)}
      </Badge>
    );
  }
  return (
    <Group gap={4} wrap="nowrap">
      <IconClockHour4 size={14} aria-hidden />
      <Text size="sm">до {formatDateTime(item.review_due_at)}</Text>
    </Group>
  );
}

function useTake() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  return useMutation({
    mutationFn: (item: StaffListItem) => api.take(item.id, item.version, newId()),
    onSuccess: (card) => {
      queryClient.setQueryData(qk.bankCard(card.id), card);
      void queryClient.invalidateQueries({ queryKey: ['bank', 'list'] });
      navigate(`/bank/applications/${card.id}`, { state: { viewContext: 'QUEUE' } });
    },
    onError: (e) => reactToCommandError(e, queryClient, ['bank', 'list']),
  });
}

function ReasonList({ item }: { item: StaffListItem }) {
  if (item.failed_stage) {
    return (
      <Text size="sm">
        Этап {item.failed_stage}: {item.last_error_code}
        {item.next_retry_at ? `, повтор ${formatDateTime(item.next_retry_at)}` : ''}
      </Text>
    );
  }
  if (item.manual_review_reasons.length === 0) return <Text size="sm" c="dimmed">нет</Text>;
  return (
    <Stack gap={2}>
      {item.manual_review_reasons.map((r) => (
        <Tooltip key={r.code} label={r.code} position="top-start">
          <Text size="sm" lineClamp={2}>
            {r.text ?? r.code}
          </Text>
        </Tooltip>
      ))}
    </Stack>
  );
}

function QueueTable({ items, tab, canTake }: { items: StaffListItem[]; tab: Tab; canTake: boolean }) {
  const take = useTake();
  const open = (item: StaffListItem) => ({ pathname: `/bank/applications/${item.id}`, state: { viewContext: tab === 'errors' ? 'ERROR_LIST' : tab === 'all' ? 'SEARCH' : 'QUEUE' } });
  const showTake = canTake && tab === 'queue';
  return (
    <>
      <div className="table-scroll hide-mobile">
        <Table striped highlightOnHover verticalSpacing="sm" style={{ minWidth: 980 }}>
          <Table.Caption>{TAB_LABELS[tab]}: {items.length} на странице</Table.Caption>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Заявка</Table.Th>
              <Table.Th>Компания</Table.Th>
              <Table.Th>Продукт и сумма</Table.Th>
              <Table.Th>Причины</Table.Th>
              <Table.Th>Грейд</Table.Th>
              <Table.Th>В очереди</Table.Th>
              <Table.Th>Срок SLA</Table.Th>
              <Table.Th>Исполнитель</Table.Th>
              <Table.Th>
                <span className="visually-hidden">Действия</span>
              </Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {items.map((item) => (
              <Table.Tr key={item.id} className={item.sla_breached ? 'row-breached' : undefined}>
                <Table.Td>
                  <Text fw={600} size="sm" component={Link} to={open(item).pathname} state={open(item).state} style={{ textDecoration: 'none', color: 'inherit' }}>
                    {item.application_number}
                  </Text>
                  <InternalStatusBadge status={item.status} />
                </Table.Td>
                <Table.Td>
                  <Text size="sm">{item.company_short_name ?? 'не указана'}</Text>
                  <Text size="xs" c="dimmed" className="num">
                    ИНН {item.applicant_inn ?? 'нет'}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <Text size="sm">{productName(item.product_code)}</Text>
                  <Text size="xs" c="dimmed" className="num">
                    {formatMoney(item.amount)}, {formatTerm(item.term_months)}
                  </Text>
                </Table.Td>
                <Table.Td maw={280}>
                  <ReasonList item={item} />
                </Table.Td>
                <Table.Td>
                  {item.grade ? (
                    <Text size="sm" fw={600} className="num">
                      {item.grade} · {item.score}
                    </Text>
                  ) : (
                    <Text size="sm" c="dimmed">нет</Text>
                  )}
                </Table.Td>
                <Table.Td>
                  <Text size="sm">{item.time_in_queue_sec !== null ? formatDuration(item.time_in_queue_sec) : 'нет'}</Text>
                </Table.Td>
                <Table.Td>
                  <SlaCell item={item} />
                </Table.Td>
                <Table.Td>
                  <Text size="sm">{item.assignee?.full_name ?? 'не назначен'}</Text>
                </Table.Td>
                <Table.Td>
                  <Group gap={6} wrap="nowrap">
                    <Button component={Link} to={open(item).pathname} state={open(item).state} size="xs" variant="light">
                      Открыть
                    </Button>
                    {showTake && (
                      <Button size="xs" onClick={() => take.mutate(item)} loading={take.isPending && take.variables.id === item.id}>
                        Взять в работу
                      </Button>
                    )}
                  </Group>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </div>
      <Stack gap="sm" className="show-mobile" component="ul" style={{ listStyle: 'none', padding: 0, margin: 0 }}>
        {items.map((item) => (
          <Paper key={item.id} component="li" withBorder radius="lg" p="md" style={item.sla_breached ? { borderColor: 'var(--mantine-color-red-4)' } : undefined}>
            <Stack gap={6}>
              <Group justify="space-between" wrap="nowrap">
                <Text fw={700}>{item.application_number}</Text>
                <InternalStatusBadge status={item.status} />
              </Group>
              <Text size="sm">
                {item.company_short_name}, {productName(item.product_code)}, {formatMoney(item.amount)}
              </Text>
              <ReasonList item={item} />
              <SlaCell item={item} />
              <Group gap={6}>
                <Button component={Link} to={open(item).pathname} state={open(item).state} size="xs" variant="light">
                  Открыть
                </Button>
                {showTake && (
                  <Button size="xs" onClick={() => take.mutate(item)} loading={take.isPending && take.variables.id === item.id}>
                    Взять в работу
                  </Button>
                )}
              </Group>
            </Stack>
          </Paper>
        ))}
      </Stack>
    </>
  );
}
