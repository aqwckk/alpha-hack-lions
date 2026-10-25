import { Button, Checkbox, Code, Group, Pagination, Paper, SimpleGrid, Stack, Table, Text, TextInput } from '@mantine/core';
import { IconSearch } from '@tabler/icons-react';
import { useQuery } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { moscowDateBoundary } from '@/shared/lib/dateFilters';
import { api } from '@/shared/api/endpoints';
import { qk } from '@/shared/api/queries';
import { formatStamp } from '@/shared/lib/format';
import { ROLE_LABELS } from '@/shared/lib/labels';
import { EmptyState, ErrorState, PageHeader, PageSkeleton } from '@/shared/ui/components';

const KEYS = ['action', 'actor_login', 'application_id', 'from', 'to'] as const;

export function AuditPage() {
  const [params, setParams] = useSearchParams();
  const page = Math.max(1, Number(params.get('page')) || 1);
  const accessOnly = params.get('access_only') === 'true';
  const filters: Record<string, string> = {};
  for (const k of KEYS) {
    const v = params.get(k);
    if (v) filters[k] = v;
  }
  const [draft, setDraft] = useState<Record<string, string>>(filters);
  const queryParams = { page, page_size: 50, ...(accessOnly ? { access_only: true } : {}), ...filters, from: moscowDateBoundary(filters.from), to: moscowDateBoundary(filters.to, true) };
  const query = useQuery({ queryKey: qk.audit(queryParams), queryFn: () => api.audit(queryParams), placeholderData: (prev) => prev });

  const apply = (e?: FormEvent) => {
    e?.preventDefault();
    const next = new URLSearchParams();
    for (const k of KEYS) if (draft[k]?.trim()) next.set(k, draft[k].trim());
    if (accessOnly) next.set('access_only', 'true');
    setParams(next);
  };
  const toggleAccess = (checked: boolean) => {
    const next = new URLSearchParams(params);
    if (checked) next.set('access_only', 'true');
    else next.delete('access_only');
    next.delete('page');
    setParams(next);
  };

  return (
    <>
      <PageHeader title="Журнал аудита" subtitle="Кто, что и когда делал с заявками и данными: входы, просмотры карточек, скачивания, решения." />
      <Stack gap="md">
        <Paper withBorder radius="lg" p="md" component="form" onSubmit={apply} aria-label="Фильтры журнала">
          <SimpleGrid cols={{ base: 1, xs: 2, md: 5 }} spacing="sm">
            <TextInput label="Действие" placeholder="VIEW_APPLICATION" value={draft.action ?? ''} onChange={(e) => setDraft({ ...draft, action: e.currentTarget.value })} />
            <TextInput label="Пользователь" placeholder="uw.dmitry" value={draft.actor_login ?? ''} onChange={(e) => setDraft({ ...draft, actor_login: e.currentTarget.value })} />
            <TextInput label="ID заявки" value={draft.application_id ?? ''} onChange={(e) => setDraft({ ...draft, application_id: e.currentTarget.value })} />
            <TextInput label="С (МСК)" type="date" value={draft.from ?? ''} onChange={(e) => setDraft({ ...draft, from: e.currentTarget.value })} />
            <TextInput label="По (МСК, включительно)" type="date" value={draft.to ?? ''} onChange={(e) => setDraft({ ...draft, to: e.currentTarget.value })} />
          </SimpleGrid>
          <Group mt="md" justify="space-between">
            <Checkbox label="Только просмотры карточек и скачивания документов" checked={accessOnly} onChange={(e) => toggleAccess(e.currentTarget.checked)} />
            <Button type="submit" leftSection={<IconSearch size={16} aria-hidden />}>
              Применить
            </Button>
          </Group>
        </Paper>
        {query.isPending && <PageSkeleton lines={3} />}
        {query.isError && <ErrorState error={query.error} onRetry={() => void query.refetch()} />}
        {query.data && query.data.items.length === 0 && <EmptyState title="Записей нет" text="Измените фильтры или период." />}
        {query.data && query.data.items.length > 0 && (
          <>
            <div className="table-scroll">
              <Table striped verticalSpacing={4} fz="sm" style={{ minWidth: 960 }}>
                <Table.Caption>Записей: {query.data.total}</Table.Caption>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Время</Table.Th>
                    <Table.Th>Кто</Table.Th>
                    <Table.Th>Действие</Table.Th>
                    <Table.Th>Результат</Table.Th>
                    <Table.Th>Заявка</Table.Th>
                    <Table.Th>IP</Table.Th>
                    <Table.Th>Детали</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {query.data.items.map((a, i) => (
                    <Table.Tr key={a.id ?? i}>
                      <Table.Td style={{ whiteSpace: 'nowrap' }}>{formatStamp(a.occurred_at)}</Table.Td>
                      <Table.Td>
                        {a.actor_login ?? 'система'}
                        <Text size="xs" c="dimmed">
                          {ROLE_LABELS[a.actor_role ?? ''] ?? a.actor_role}
                        </Text>
                      </Table.Td>
                      <Table.Td>
                        <Code>{a.action}</Code>
                      </Table.Td>
                      <Table.Td>
                        <Text size="sm" c={a.result === 'SUCCESS' ? undefined : 'red.8'}>
                          {a.result}
                        </Text>
                      </Table.Td>
                      <Table.Td>
                        {a.application_id ? (
                          <Link to={`/bank/applications/${a.application_id}`} state={{ viewContext: 'SEARCH' }}>
                            открыть
                          </Link>
                        ) : (
                          ''
                        )}
                      </Table.Td>
                      <Table.Td>{a.ip_address}</Table.Td>
                      <Table.Td maw={260}>
                        <Text size="xs" lineClamp={2}>
                          {Object.keys(a.details).length ? JSON.stringify(a.details) : ''}
                        </Text>
                      </Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </div>
            {query.data.total > query.data.page_size && (
              <Pagination
                total={Math.ceil(query.data.total / query.data.page_size)}
                value={page}
                onChange={(p) => {
                  const next = new URLSearchParams(params);
                  next.set('page', String(p));
                  setParams(next);
                }}
                aria-label="Страницы журнала"
              />
            )}
          </>
        )}
      </Stack>
    </>
  );
}

export default AuditPage;
