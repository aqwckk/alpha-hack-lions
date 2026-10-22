import { Alert, Badge, Button, Group, SegmentedControl, Stack, Table, Text } from '@mantine/core';
import { IconFlask, IconRefresh } from '@tabler/icons-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/shared/api/endpoints';
import { qk, useMeta } from '@/shared/api/queries';
import type { IntegrationSource } from '@/shared/api/types';
import { SOURCE_LABELS } from '@/shared/lib/labels';
import { ErrorState, PageHeader, PageSkeleton, SectionCard } from '@/shared/ui/components';
import { toast } from '@/shared/ui/toast';

const SOURCES: IntegrationSource[] = ['REGISTRY', 'FNS', 'FINANCIAL_STATEMENTS', 'CREDIT_BUREAU', 'BANK_TURNOVER', 'EDO', 'ABS'];

/** Demo-only controls of the integrations simulator (DEMO_MODE): reset failure counters, switch a source off. */
export function DemoPanelPage() {
  const meta = useMeta();
  const queryClient = useQueryClient();
  const state = useQuery({ queryKey: qk.demo, queryFn: api.demoState, refetchInterval: 5000, enabled: Boolean(meta.data?.demo_mode) });
  const reset = useMutation({
    mutationFn: api.demoReset,
    onSuccess: () => {
      toast.success('Счетчики сбоев сброшены: сценарий S5 можно показать снова');
      void queryClient.invalidateQueries({ queryKey: qk.demo });
    },
    onError: (e) => toast.error(e),
  });
  const outage = useMutation({
    mutationFn: ({ source, failure }: { source: IntegrationSource; failure: 'TIMEOUT' | 'HTTP_500' | null }) => api.demoOutage(source, failure),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: qk.demo }),
    onError: (e) => toast.error(e),
  });

  if (meta.data && !meta.data.demo_mode) {
    return <Alert color="gray">Демо-режим выключен: управление симулятором недоступно.</Alert>;
  }
  return (
    <>
      <PageHeader title="Демо-панель" subtitle="Управление симулятором внешних систем для показа отказоустойчивости. Доступно только в демо-режиме." />
      <Stack gap="lg">
        <Alert color="yellow" icon={<IconFlask aria-hidden />} radius="lg">
          S5: перед показом нажмите "Сбросить сбои". Бюро кредитных историй снова ответит таймаутом на первые 4 запроса по ИНН 0010005015, заявка подождет и получит
          одобрение. S5b: выключите источник, дождитесь вкладки "Ошибки обработки" в очереди, включите источник и нажмите "Повторить обработку" в карточке.
        </Alert>
        <Group>
          <Button leftSection={<IconRefresh size={16} aria-hidden />} onClick={() => reset.mutate()} loading={reset.isPending}>
            Сбросить сбои
          </Button>
        </Group>
        {state.isPending && <PageSkeleton lines={2} />}
        {state.isError && <ErrorState error={state.error} onRetry={() => void state.refetch()} />}
        {state.data && (
          <>
            <SectionCard title="Источники">
              <div className="table-scroll">
                <Table verticalSpacing="sm" style={{ minWidth: 640 }}>
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th>Источник</Table.Th>
                      <Table.Th>Запросов</Table.Th>
                      <Table.Th>Состояние</Table.Th>
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {SOURCES.map((src) => {
                      const failure = state.data.outages[src] ?? null;
                      return (
                        <Table.Tr key={src}>
                          <Table.Td>{SOURCE_LABELS[src] ?? src}</Table.Td>
                          <Table.Td>{state.data.requests_total[src] ?? 0}</Table.Td>
                          <Table.Td>
                            <Group gap="sm" wrap="nowrap">
                              <Badge color={failure ? 'red' : 'green'} variant="light">
                                {failure ? `выключен: ${failure}` : 'работает'}
                              </Badge>
                              <SegmentedControl
                                size="xs"
                                value={failure ?? 'OK'}
                                onChange={(v) => outage.mutate({ source: src, failure: v === 'OK' ? null : (v as 'TIMEOUT' | 'HTTP_500') })}
                                data={[
                                  { value: 'OK', label: 'Работает' },
                                  { value: 'TIMEOUT', label: 'Таймаут' },
                                  { value: 'HTTP_500', label: 'Ошибка 500' },
                                ]}
                                aria-label={`Режим источника ${SOURCE_LABELS[src] ?? src}`}
                              />
                            </Group>
                          </Table.Td>
                        </Table.Tr>
                      );
                    })}
                  </Table.Tbody>
                </Table>
              </div>
            </SectionCard>
            {state.data.counters.length > 0 && (
              <SectionCard title="Счетчики настроенных сбоев по ИНН">
                {state.data.counters.map((c) => (
                  <Text key={`${c.source}-${c.inn}`} size="sm">
                    {SOURCE_LABELS[c.source] ?? c.source}, ИНН {c.inn}: запросов {c.requests}
                  </Text>
                ))}
              </SectionCard>
            )}
          </>
        )}
      </Stack>
    </>
  );
}

export default DemoPanelPage;
