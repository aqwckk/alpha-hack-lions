import { ActionIcon, Badge, Button, Drawer, Group, Indicator, Stack, Text, UnstyledButton } from '@mantine/core';
import { IconBell } from '@tabler/icons-react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '@/shared/api/endpoints';
import { qk, useNotifications } from '@/shared/api/queries';
import type { NotificationItem, Role } from '@/shared/api/types';
import { formatDateTime } from '@/shared/lib/format';
import { ErrorState, PageSkeleton } from '@/shared/ui/components';

/** In-product notifications (CL-14): the only channel, no email or SMS. */
export function NotificationsBell({ role }: { role: Role }) {
  const [opened, setOpened] = useState(false);
  const query = useNotifications(true);
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const unread = query.data?.unread ?? 0;

  const markRead = useMutation({
    mutationFn: api.markRead,
    onSettled: () => queryClient.invalidateQueries({ queryKey: qk.notifications }),
  });
  const markAll = useMutation({
    mutationFn: api.markAllRead,
    onSettled: () => queryClient.invalidateQueries({ queryKey: qk.notifications }),
  });

  const open = (n: NotificationItem) => {
    if (!n.read) markRead.mutate(n.id);
    setOpened(false);
    if (n.application_id) {
      navigate(role === 'CLIENT' ? `/client/applications/${n.application_id}` : `/bank/applications/${n.application_id}`);
    }
  };

  return (
    <>
      <Indicator label={unread > 99 ? '99+' : unread} size={18} disabled={unread === 0} color="brand" offset={4}>
        <ActionIcon
          variant="subtle"
          color="gray"
          size="lg"
          radius="xl"
          onClick={() => setOpened(true)}
          aria-label={unread ? `Уведомления, непрочитанных: ${unread}` : 'Уведомления'}
          aria-haspopup="dialog"
        >
          <IconBell size={22} aria-hidden />
        </ActionIcon>
      </Indicator>
      <Drawer opened={opened} onClose={() => setOpened(false)} position="right" title="Уведомления" size="md">
        <Stack gap="sm">
          <Group justify="space-between">
            <Text size="sm" c="dimmed">
              Уведомления приходят только сюда, без email и SMS.
            </Text>
            {unread > 0 && (
              <Button size="compact-sm" variant="subtle" onClick={() => markAll.mutate()} loading={markAll.isPending}>
                Отметить все прочитанными
              </Button>
            )}
          </Group>
          {query.isPending && <PageSkeleton lines={3} />}
          {query.isError && <ErrorState error={query.error} onRetry={() => void query.refetch()} />}
          {query.data && query.data.items.length === 0 && (
            <Text c="dimmed" ta="center" py="xl">
              Новых уведомлений нет
            </Text>
          )}
          <Stack gap={8} component="ul" style={{ listStyle: 'none', padding: 0, margin: 0 }}>
            {query.data?.items.map((n) => (
              <li key={n.id}>
                <UnstyledButton
                  onClick={() => open(n)}
                  w="100%"
                  p="sm"
                  style={{ borderRadius: 12, border: '1px solid var(--app-border)', background: n.read ? '#fff' : '#fff7f7' }}
                >
                  <Group justify="space-between" align="flex-start" wrap="nowrap" gap="xs">
                    <Text fw={600} size="sm">
                      {n.title}
                    </Text>
                    {!n.read && (
                      <Badge size="xs" color="brand" variant="filled">
                        новое
                      </Badge>
                    )}
                  </Group>
                  <Text size="sm" mt={4}>
                    {n.body}
                  </Text>
                  <Text size="xs" c="dimmed" mt={4}>
                    {formatDateTime(n.created_at)}
                    {n.application_id ? ' · открыть заявку' : ''}
                  </Text>
                </UnstyledButton>
              </li>
            ))}
          </Stack>
        </Stack>
      </Drawer>
    </>
  );
}
