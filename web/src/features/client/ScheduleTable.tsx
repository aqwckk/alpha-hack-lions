import { Button, Collapse, Group, Stack, Table, Text } from '@mantine/core';
import { IconTable } from '@tabler/icons-react';
import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { api } from '@/shared/api/endpoints';
import { qk } from '@/shared/api/queries';
import type { ScheduleResponse } from '@/shared/api/types';
import { formatDate, formatMoney } from '@/shared/lib/format';
import { ErrorState, PageSkeleton } from '@/shared/ui/components';

export function ScheduleView({ schedule }: { schedule: ScheduleResponse }) {
  return (
    <Stack gap="sm">
      <Text size="sm">
        Платеж {formatMoney(schedule.monthly_payment)} в месяц, всего {formatMoney(schedule.total_payment)}, переплата {formatMoney(schedule.overpayment)}. Первый
        платеж {formatDate(schedule.first_payment_date)}.
      </Text>
      <div className="table-scroll" style={{ maxHeight: 420 }}>
        <Table striped stickyHeader verticalSpacing={4} fz="sm" style={{ minWidth: 520 }}>
          <Table.Caption>График платежей: {schedule.rows.length} платежей</Table.Caption>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>№</Table.Th>
              <Table.Th>Дата</Table.Th>
              <Table.Th ta="right">Платеж</Table.Th>
              <Table.Th ta="right">Проценты</Table.Th>
              <Table.Th ta="right">Основной долг</Table.Th>
              <Table.Th ta="right">Остаток</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {schedule.rows.map((r) => (
              <Table.Tr key={r.n}>
                <Table.Td>{r.n}</Table.Td>
                <Table.Td>{formatDate(r.date)}</Table.Td>
                <Table.Td ta="right" className="num">
                  {formatMoney(r.payment)}
                </Table.Td>
                <Table.Td ta="right" className="num">
                  {formatMoney(r.interest)}
                </Table.Td>
                <Table.Td ta="right" className="num">
                  {formatMoney(r.principal)}
                </Table.Td>
                <Table.Td ta="right" className="num">
                  {formatMoney(r.balance)}
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </div>
    </Stack>
  );
}

/** Lazily loaded schedule of an offer option or of the issued loan. */
export function ScheduleLoader({ appId, optionId }: { appId: string; optionId?: string }) {
  const query = useQuery({ queryKey: qk.schedule(appId, optionId), queryFn: () => api.schedule(appId, optionId), staleTime: 60_000 });
  if (query.isPending) return <PageSkeleton lines={1} />;
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  return <ScheduleView schedule={query.data} />;
}

export function ScheduleToggle({ appId, optionId, label = 'График платежей' }: { appId: string; optionId?: string; label?: string }) {
  const [open, setOpen] = useState(false);
  return (
    <Stack gap="sm">
      <Group>
        <Button variant="light" leftSection={<IconTable size={16} aria-hidden />} onClick={() => setOpen((v) => !v)} aria-expanded={open}>
          {open ? 'Скрыть график' : label}
        </Button>
      </Group>
      <Collapse in={open}>{open && <ScheduleLoader appId={appId} {...(optionId ? { optionId } : {})} />}</Collapse>
    </Stack>
  );
}
