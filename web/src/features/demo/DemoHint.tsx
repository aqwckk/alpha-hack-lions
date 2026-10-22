import { Alert, Collapse, Group, Text, UnstyledButton } from '@mantine/core';
import { IconBulb, IconChevronDown } from '@tabler/icons-react';
import { useState } from 'react';
import { DEMO_EXTRA_INNS, DEMO_SCENARIOS } from './demoData';
import { useMeta } from '@/shared/api/queries';
import { useUser } from '@/features/auth/AuthProvider';
import { KeyValue } from '@/shared/ui/components';

/** Demo-only helper: the scenario values for the signed-in test client, collapsed by default. */
export function DemoHint({ defaultOpen = false }: { defaultOpen?: boolean }) {
  const meta = useMeta();
  const user = useUser();
  const [open, setOpen] = useState(defaultOpen);
  if (!meta.data?.demo_mode) return null;
  const scenario = DEMO_SCENARIOS[user.login];
  return (
    <Alert color="yellow" variant="light" radius="lg" icon={<IconBulb aria-hidden />} p="sm">
      <UnstyledButton onClick={() => setOpen((v) => !v)} aria-expanded={open} style={{ width: '100%' }}>
        <Group justify="space-between" wrap="nowrap">
          <Text size="sm" fw={600}>
            {scenario ? `Демо-подсказка: сценарий ${scenario.code}, ${scenario.title}` : 'Демо-подсказка: тестовые ИНН'}
          </Text>
          <IconChevronDown size={16} aria-hidden style={{ transform: open ? 'rotate(180deg)' : undefined }} />
        </Group>
      </UnstyledButton>
      <Collapse in={open}>
        <div style={{ paddingTop: 10 }}>
          {scenario ? (
            <KeyValue
              cols={3}
              items={[
                { label: 'Задача', value: scenario.purpose },
                { label: 'Продукт', value: scenario.product },
                { label: 'Сумма и срок', value: `${scenario.amount} ₽, ${scenario.term}` },
                { label: 'ИНН', value: <span className="num">{scenario.inn}</span> },
                { label: 'Компания', value: scenario.company },
                { label: 'Ваша роль', value: scenario.role },
                { label: 'Выручка в месяц', value: `${scenario.revenue} ₽` },
                { label: 'Платежи по кредитам', value: `${scenario.payments} ₽` },
                { label: 'Что получится', value: scenario.outcome },
                { label: 'Еще', value: scenario.extra, hidden: !scenario.extra },
              ]}
            />
          ) : (
            <KeyValue cols={2} items={DEMO_EXTRA_INNS.map((x) => ({ label: <span className="num">{x.inn}</span>, value: x.note }))} />
          )}
          <Text size="xs" c="dimmed" mt="xs">
            Подсказка видна только в демо-режиме. Данные синтетические.
          </Text>
        </div>
      </Collapse>
    </Alert>
  );
}
