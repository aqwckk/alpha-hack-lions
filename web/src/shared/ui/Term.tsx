import { ActionIcon, Group, Popover, Text } from '@mantine/core';
import { IconInfoCircle } from '@tabler/icons-react';
import type { ReactNode } from 'react';
import { GLOSSARY, type GlossaryKey } from '@/shared/lib/glossary';

/** Inline hint for a term: opens on click or keyboard (not hover-only), text in plain language. */
export function Hint({ term, hint, label }: { term: string; hint: string; label?: string }) {
  return (
    <Popover width={300} position="top" withArrow shadow="md" trapFocus={false} returnFocus>
      <Popover.Target>
        <ActionIcon
          variant="subtle"
          color="gray"
          size="sm"
          radius="xl"
          aria-label={label ?? `Что значит "${term}"?`}
          className="hint-trigger"
        >
          <IconInfoCircle size={16} aria-hidden />
        </ActionIcon>
      </Popover.Target>
      <Popover.Dropdown>
        <Text size="sm" fw={600} mb={4}>
          {term}
        </Text>
        <Text size="sm">{hint}</Text>
      </Popover.Dropdown>
    </Popover>
  );
}

/** Text with a glossary hint next to it. */
export function Term({ children, k }: { children: ReactNode; k: GlossaryKey }) {
  const term = typeof children === 'string' ? children : '';
  return (
    <Group gap={2} wrap="nowrap" component="span" style={{ display: 'inline-flex', verticalAlign: 'middle' }}>
      <span>{children}</span>
      <Hint term={term || 'Подсказка'} hint={GLOSSARY[k]} />
    </Group>
  );
}
