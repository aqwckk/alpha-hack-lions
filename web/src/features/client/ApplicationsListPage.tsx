import { Button, Group, Pagination, Paper, SimpleGrid, Stack, Text, Title } from '@mantine/core';
import { IconPlus, IconReportMoney } from '@tabler/icons-react';
import { useQuery } from '@tanstack/react-query';
import { useEffect } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { DemoHint } from '@/features/demo/DemoHint';
import { api } from '@/shared/api/endpoints';
import { qk } from '@/shared/api/queries';
import type { ClientApplicationListItem } from '@/shared/api/types';
import { formatDateTime, formatMoney, formatTerm } from '@/shared/lib/format';
import { ClientStatusBadge, EmptyState, ErrorState, PageHeader, PageSkeleton } from '@/shared/ui/components';

/** One next action per application, by client status (screens.md, CL-02). */
export function nextActionFor(item: Pick<ClientApplicationListItem, 'id' | 'client_status'>): { label: string; to: string; primary: boolean } {
  const base = `/client/applications/${item.id}`;
  switch (item.client_status) {
    case 'FILLING':
      return { label: 'Продолжить заполнение', to: `${base}/edit`, primary: true };
    case 'ACTION_REQUIRED':
      return { label: 'Ответить на запрос банка', to: `${base}/info-request`, primary: true };
    case 'DECISION_READY':
      return { label: 'Посмотреть решение', to: `${base}/offer`, primary: true };
    case 'DOCUMENTS':
      return { label: 'Подписать документы', to: `${base}/signing`, primary: true };
    default:
      return { label: 'Открыть', to: base, primary: false };
  }
}

export function ApplicationsListPage() {
  const [params, setParams] = useSearchParams();
  const rawPage = Number(params.get('page'));
  const page = Number.isSafeInteger(rawPage) && rawPage > 0 ? rawPage : 1;
  const query = useQuery({ queryKey: [...qk.applications, { page, pageSize: 20 }], queryFn: () => api.listApplications(page, 20), refetchInterval: 15000 });
  const changePage = (nextPage: number) => {
    const next = new URLSearchParams(params);
    if (nextPage === 1) next.delete('page');
    else next.set('page', String(nextPage));
    setParams(next);
  };
  useEffect(() => {
    if (!query.data) return;
    const lastPage = Math.max(1, Math.ceil(query.data.total / query.data.page_size));
    if (page > lastPage) {
      const next = new URLSearchParams(params);
      if (lastPage === 1) next.delete('page');
      else next.set('page', String(lastPage));
      setParams(next, { replace: true });
    }
  }, [query.data, page, params, setParams]);

  return (
    <>
      <PageHeader
        title="Мои заявки"
        subtitle="Здесь видно, что происходит с каждой заявкой и что нужно сделать дальше"
        actions={
          <Button component={Link} to="/client/wizard" leftSection={<IconPlus size={18} aria-hidden />}>
            Подобрать кредит
          </Button>
        }
      />
      <Stack gap="md">
        <DemoHint />
        {query.isPending && <PageSkeleton lines={3} />}
        {query.isError && <ErrorState error={query.error} onRetry={() => void query.refetch()} />}
        {query.data && query.data.total === 0 && (
          <EmptyState
            icon={<IconReportMoney size={44} color="var(--app-accent)" aria-hidden />}
            title="У вас пока нет заявок"
            text="Расскажите, на что нужны деньги, и мы подберем подходящий кредит"
            action={
              <Button component={Link} to="/client/wizard" size="md">
                Подобрать кредит
              </Button>
            }
          />
        )}
        {query.data && query.data.items.length > 0 && (
          <SimpleGrid cols={{ base: 1, md: 2 }} spacing="md" component="ul" style={{ listStyle: 'none', padding: 0, margin: 0 }}>
            {query.data.items.map((item) => {
              const next = nextActionFor(item);
              return (
                <Paper component="li" key={item.id} withBorder radius="lg" p="lg">
                  <Stack gap="sm" h="100%">
                    <Group justify="space-between" align="flex-start" wrap="wrap" gap="xs">
                      <div>
                        <Title order={2} size="h4">
                          {item.product_name}
                        </Title>
                        <Text size="sm" c="dimmed">
                          Заявка {item.application_number}
                          {item.company_short_name ? `, ${item.company_short_name}` : ''}
                        </Text>
                      </div>
                      <ClientStatusBadge status={item.client_status} title={item.client_status_title} />
                    </Group>
                    <Group gap="lg">
                      <div>
                        <Text size="xs" c="dimmed">
                          Сумма
                        </Text>
                        <Text fw={600} className="num">
                          {formatMoney(item.amount)}
                        </Text>
                      </div>
                      <div>
                        <Text size="xs" c="dimmed">
                          Срок
                        </Text>
                        <Text fw={600}>{formatTerm(item.term_months)}</Text>
                      </div>
                      <div>
                        <Text size="xs" c="dimmed">
                          Изменена
                        </Text>
                        <Text>{formatDateTime(item.updated_at)}</Text>
                      </div>
                    </Group>
                    <Group mt="auto" gap="sm">
                      <Button
                        component={Link}
                        to={next.to}
                        variant={next.primary ? 'filled' : 'light'}
                        color={item.client_status === 'ACTION_REQUIRED' ? 'orange' : undefined}
                        aria-label={`${next.label}: заявка ${item.application_number}`}
                      >
                        {next.label}
                      </Button>
                      {next.primary && (
                        <Button component={Link} to={`/client/applications/${item.id}`} variant="subtle">
                          Статус заявки
                        </Button>
                      )}
                    </Group>
                  </Stack>
                </Paper>
              );
            })}
          </SimpleGrid>
        )}
        {query.data && query.data.total > 0 && (
          <Group justify="space-between" wrap="wrap">
            <Text size="sm" c="dimmed">Всего заявок: {query.data.total}</Text>
            {query.data.total > query.data.page_size && <Pagination total={Math.ceil(query.data.total / query.data.page_size)} value={page} onChange={changePage} aria-label="Страницы заявок" />}
          </Group>
        )}
      </Stack>
    </>
  );
}
