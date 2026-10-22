import {
  Alert,
  Badge,
  Button,
  Code,
  Collapse,
  Group,
  List,
  Paper,
  SimpleGrid,
  Stack,
  Table,
  Tabs,
  Text,
  Textarea,
  Title,
} from '@mantine/core';
import {
  IconAlertTriangle,
  IconChartBar,
  IconClockHour4,
  IconDownload,
  IconRefresh,
  IconRobot,
  IconScale,
} from '@tabler/icons-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';
import { useLocation, useParams } from 'react-router-dom';
import { DecisionDialog, latestAutoDecision, type DialogKind } from './DecisionDialogs';
import { useUser } from '@/features/auth/AuthProvider';
import { api, openProtectedFile } from '@/shared/api/endpoints';
import { qk } from '@/shared/api/queries';
import type { HistoryEvent, SourceInfo, StaffCard, StaffDecision } from '@/shared/api/types';
import { formatDateTime, formatFileSize, formatMoney, formatRate, formatShare, formatStamp, formatTerm } from '@/shared/lib/format';
import {
  APPLICANT_TYPES,
  DECISION_VALUE_LABELS,
  OUTCOME_LABELS,
  ROLE_LABELS,
  RULE_LABELS,
  RULE_RESULT_LABELS,
  SOURCE_LABELS,
  STAFF_ACTION_LABELS,
  clientStatusMeta,
  productName,
} from '@/shared/lib/labels';
import { CompanyBlock } from '@/features/client/form/StepCompany';
import { EmptyState, ErrorState, InternalStatusBadge, KeyValue, PageHeader, PageSkeleton, SectionCard } from '@/shared/ui/components';
import { toast } from '@/shared/ui/toast';

type ViewContext = 'QUEUE' | 'SEARCH' | 'ERROR_LIST';

export function CardPage() {
  const { id = '' } = useParams();
  const location = useLocation();
  const raw = (location.state as { viewContext?: unknown } | null)?.viewContext;
  const viewContext: ViewContext = raw === 'QUEUE' || raw === 'ERROR_LIST' ? raw : 'SEARCH';
  // Every GET of the card writes APPLICATION_VIEWED to the audit log: no polling, explicit refresh only.
  const query = useQuery({
    queryKey: qk.bankCard(id),
    queryFn: () => api.bankCard(id, viewContext),
    refetchOnWindowFocus: false,
    staleTime: Infinity,
  });
  if (query.isPending) return <PageSkeleton lines={5} />;
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} notFoundText="Заявка не найдена или у вас нет к ней доступа" />;
  return <Card card={query.data} refreshing={query.isFetching} onRefresh={() => void query.refetch()} />;
}

const ACTION_ORDER: DialogKind[] = ['TAKE', 'APPROVE', 'MAKE_COUNTER_OFFER', 'REQUEST_INFO', 'DECLINE', 'CONFIRM_DECISION', 'RETURN_DECISION', 'RETRY_PROCESSING', 'RELEASE'];

function Card({ card, refreshing, onRefresh }: { card: StaffCard; refreshing: boolean; onRefresh: () => void }) {
  const user = useUser();
  const [dialog, setDialog] = useState<DialogKind | null>(null);
  const actions = ACTION_ORDER.filter((a) => card.available_actions.includes(a));
  const form = card.form;
  const clientMeta = clientStatusMeta(card.client_status);

  return (
    <>
      <PageHeader
        title={`Заявка ${card.application_number}`}
        subtitle={`${card.company_short_name ?? 'Компания не указана'}, ИНН ${card.applicant_inn ?? 'нет'}`}
        back={{ to: user.role === 'RISK_MANAGER' ? '/bank/applications' : '/bank/queue', label: user.role === 'RISK_MANAGER' ? 'Все заявки' : 'Очередь' }}
        actions={
          <Button variant="subtle" leftSection={<IconRefresh size={16} aria-hidden />} onClick={onRefresh} loading={refreshing}>
            Обновить
          </Button>
        }
      />
      <Stack gap="lg">
        <Paper withBorder radius="lg" p="lg">
          <Stack gap="md">
            <SimpleGrid cols={{ base: 1, xs: 2, md: 4 }} spacing="md">
              <div>
                <Text size="xs" c="dimmed">
                  Продукт
                </Text>
                <Text fw={600}>{card.product_name}</Text>
                <Text size="sm" className="num">
                  {formatMoney(typeof form.amount === 'string' ? form.amount : null)}, {formatTerm(typeof form.term_months === 'number' ? form.term_months : null)}
                </Text>
              </div>
              <div>
                <Text size="xs" c="dimmed">
                  Статус
                </Text>
                <InternalStatusBadge status={card.status} />
                <Text size="xs" c="dimmed" mt={4}>
                  Клиент видит: {card.client_status_title ?? clientMeta.label}
                </Text>
              </div>
              <div>
                <Text size="xs" c="dimmed">
                  Исполнитель
                </Text>
                <Text fw={600}>{card.assignee?.full_name ?? 'не назначен'}</Text>
              </div>
              <div>
                <Text size="xs" c="dimmed">
                  Срок SLA
                </Text>
                {card.sla.review_due_at ? (
                  <Group gap={4}>
                    {card.sla.sla_breached ? <IconAlertTriangle size={16} color="var(--mantine-color-red-7)" aria-hidden /> : <IconClockHour4 size={16} aria-hidden />}
                    <Text fw={600} c={card.sla.sla_breached ? 'red.8' : undefined}>
                      {card.sla.sla_breached ? 'просрочено: ' : 'до '}
                      {formatDateTime(card.sla.review_due_at)}
                    </Text>
                  </Group>
                ) : (
                  <Text c="dimmed">не применяется</Text>
                )}
              </div>
            </SimpleGrid>
            {actions.length > 0 ? (
              <Group gap="sm" aria-label="Действия по заявке" role="group">
                {actions.map((a) => (
                  <Button
                    key={a}
                    onClick={() => setDialog(a)}
                    variant={a === 'APPROVE' || a === 'CONFIRM_DECISION' || a === 'TAKE' ? 'filled' : a === 'DECLINE' || a === 'RETURN_DECISION' ? 'light' : 'default'}
                    color={a === 'DECLINE' || a === 'RETURN_DECISION' ? 'red' : a === 'APPROVE' || a === 'CONFIRM_DECISION' ? 'green' : undefined}
                  >
                    {STAFF_ACTION_LABELS[a]}
                  </Button>
                ))}
              </Group>
            ) : (
              <Text size="sm" c="dimmed">
                Сейчас действий по заявке нет:{' '}
                {card.status === 'PENDING_RISK_APPROVAL'
                  ? 'решение ждет подтверждения риск-менеджера (принцип 4 глаз)'
                  : card.assignee && card.status === 'IN_REVIEW'
                    ? 'она в работе у коллеги'
                    : 'на этом этапе решение сотрудника не требуется'}
                .
              </Text>
            )}
          </Stack>
        </Paper>

        <Tabs defaultValue="summary" keepMounted={false}>
          <Tabs.List style={{ flexWrap: 'wrap' }}>
            <Tabs.Tab value="summary">Сводка</Tabs.Tab>
            <Tabs.Tab value="scoring">Скоринг</Tabs.Tab>
            <Tabs.Tab value="policy">Политика</Tabs.Tab>
            <Tabs.Tab value="sources">Источники</Tabs.Tab>
            <Tabs.Tab value="form">Анкета и документы</Tabs.Tab>
            <Tabs.Tab value="info" rightSection={card.info_requests.length ? <Badge size="xs">{card.info_requests.length}</Badge> : undefined}>
              Дозапросы
            </Tabs.Tab>
            <Tabs.Tab value="history">История</Tabs.Tab>
            <Tabs.Tab value="comments" rightSection={card.comments.length ? <Badge size="xs">{card.comments.length}</Badge> : undefined}>
              Комментарии
            </Tabs.Tab>
          </Tabs.List>
          <Tabs.Panel value="summary" pt="md">
            <SummaryTab card={card} />
          </Tabs.Panel>
          <Tabs.Panel value="scoring" pt="md">
            <ScoringTab card={card} />
          </Tabs.Panel>
          <Tabs.Panel value="policy" pt="md">
            <PolicyTab card={card} />
          </Tabs.Panel>
          <Tabs.Panel value="sources" pt="md">
            <SourcesTab card={card} />
          </Tabs.Panel>
          <Tabs.Panel value="form" pt="md">
            <FormTab card={card} />
          </Tabs.Panel>
          <Tabs.Panel value="info" pt="md">
            <InfoTab card={card} />
          </Tabs.Panel>
          <Tabs.Panel value="history" pt="md">
            <HistoryTab card={card} />
          </Tabs.Panel>
          <Tabs.Panel value="comments" pt="md">
            <CommentsTab card={card} />
          </Tabs.Panel>
        </Tabs>
      </Stack>
      {dialog && <DecisionDialog kind={dialog} card={card} onClose={() => setDialog(null)} />}
    </>
  );
}

function money(v: unknown): string {
  return formatMoney(typeof v === 'string' || typeof v === 'number' ? v : null);
}

function AiSummary({ card }: { card: StaffCard }) {
  const summary = useMutation({ mutationFn: () => api.aiSummary(card.id), onError: (e) => toast.error(e) });
  const blocks = (summary.data?.blocks ?? {}) as Record<string, unknown>;
  const titles: Record<string, string> = { risks: 'Риски', checks: 'Что проверить', positives: 'Сильные стороны' };
  return (
    <SectionCard
      title={
        <Group gap={6} component="span">
          <IconRobot size={20} aria-hidden /> Резюме заявки
        </Group>
      }
      actions={
        <Button size="xs" variant="light" onClick={() => summary.mutate()} loading={summary.isPending}>
          {summary.data ? 'Обновить резюме' : 'Сформировать резюме'}
        </Button>
      }
    >
      {!summary.data && (
        <Text size="sm" c="dimmed">
          Короткая выжимка рисков и проверок по данным карточки. Работает без внешних сервисов; если подключена локальная модель, текст формулирует она.
        </Text>
      )}
      {summary.data && (
        <Stack gap="sm">
          <SimpleGrid cols={{ base: 1, md: 3 }} spacing="md">
            {Object.entries(blocks).map(([k, v]) => (
              <div key={k}>
                <Text fw={600} size="sm" mb={4}>
                  {titles[k] ?? k}
                </Text>
                <List size="sm" spacing={2}>
                  {(Array.isArray(v) ? v : [String(v)]).map((line, i) => (
                    <List.Item key={i}>{String(line)}</List.Item>
                  ))}
                </List>
              </div>
            ))}
          </SimpleGrid>
          <Text size="xs" c="dimmed">
            {summary.data.label}
            {summary.data.model_name ? `, модель ${summary.data.model_name}` : ', шаблон без модели'}
          </Text>
        </Stack>
      )}
    </SectionCard>
  );
}

function SummaryTab({ card }: { card: StaffCard }) {
  const auto = latestAutoDecision(card);
  const rec = auto?.recommendation;
  const f = card.form;
  return (
    <Stack gap="lg">
      {card.processing.technical_reason && (
        <Alert color="red" icon={<IconAlertTriangle aria-hidden />} title="Ошибка обработки">
          {card.processing.technical_reason.employee_text}
          {card.processing.next_retry_at ? ` Следующий повтор: ${formatDateTime(card.processing.next_retry_at)}.` : ''}
        </Alert>
      )}
      {card.status === 'EXTERNAL_SERVICE_UNAVAILABLE' && (
        <Alert color="orange" icon={<IconClockHour4 aria-hidden />} title="Источник недоступен">
          Последняя ошибка {card.processing.last_error_code ?? 'нет'}, повторов {card.processing.enrichment_retry_count}. Следующий повтор{' '}
          {formatDateTime(card.processing.next_retry_at)}. Клиент видит понятный статус о задержке.
        </Alert>
      )}
      {card.discrepancies.length > 0 && (
        <Alert color="orange" icon={<IconAlertTriangle aria-hidden />} title="Расхождения">
          <List size="sm">
            {card.discrepancies.map((d) => (
              <List.Item key={d.code}>{d.text}</List.Item>
            ))}
          </List>
        </Alert>
      )}
      {card.manual_review_reasons.length > 0 && (
        <SectionCard title="Почему нужно ручное рассмотрение">
          <Stack gap={6}>
            {card.manual_review_reasons.map((r) => (
              <Group key={r.code} gap="xs" wrap="nowrap" align="flex-start">
                <Badge variant="light" color="violet" style={{ flex: 'none' }}>
                  {r.code}
                </Badge>
                <Text size="sm">
                  {r.employee_text}
                  {r.client_text && r.client_visibility !== 'NONE' ? <Text span c="dimmed">{` Клиент видит: "${r.client_text}"`}</Text> : null}
                </Text>
              </Group>
            ))}
          </Stack>
        </SectionCard>
      )}
      <SimpleGrid cols={{ base: 1, md: 2 }} spacing="lg">
        <SectionCard title="Параметры заявки">
          <KeyValue
            cols={1}
            items={[
              { label: 'Цель', value: card.purpose_title },
              { label: 'Сумма и срок', value: `${money(f.amount)}, ${formatTerm(typeof f.term_months === 'number' ? f.term_months : null)}` },
              { label: 'Заявитель', value: `${APPLICANT_TYPES[card.applicant_type ?? ''] ?? card.applicant_type ?? ''}, ${card.client?.full_name ?? ''}` },
              { label: 'Выручка в месяц (анкета)', value: money(f.monthly_revenue_declared) },
              { label: 'Платежи по кредитам (анкета)', value: money(f.existing_monthly_payments_declared) },
              { label: 'Поручительство собственника', value: f.owner_guarantee_agreed === true ? 'согласие есть' : f.owner_guarantee_agreed === false ? 'нет' : 'не требуется', },
              { label: 'Залог', value: f.collateral_description ? `${String(f.collateral_description)}, ${money(f.collateral_value)}` : '', hidden: !f.collateral_description },
              { label: 'Проект', value: String(f.investment_project_description ?? ''), hidden: !f.investment_project_description },
              { label: 'Комментарий клиента', value: String(f.client_comment ?? ''), hidden: !f.client_comment },
            ]}
          />
        </SectionCard>
        <SectionCard
          title={
            <Group gap={6} component="span">
              <IconScale size={20} aria-hidden /> Рекомендация политики
            </Group>
          }
        >
          {!auto && <Text c="dimmed">Политика еще не применялась.</Text>}
          {auto && (
            <Stack gap="sm">
              <Group gap="xs">
                <Badge size="lg" variant="light" color={auto.outcome === 'DECLINED' ? 'red' : auto.outcome === 'APPROVED' ? 'green' : 'violet'}>
                  {OUTCOME_LABELS[auto.outcome] ?? auto.outcome}
                </Badge>
                {card.scoring && (
                  <Badge size="lg" variant="outline" color="gray">
                    Грейд {card.scoring.grade}, балл {card.scoring.score}
                  </Badge>
                )}
              </Group>
              {rec && (
                <>
                  <Text size="sm">
                    Рекомендуемый исход: <b>{OUTCOME_LABELS[rec.outcome] ?? rec.outcome}</b>. Допустимый платеж {money(rec.allowed_payment)}, максимальная сумма на запрошенный срок{' '}
                    {money(rec.max_amount_requested_term)}.
                  </Text>
                  {rec.options?.map((o, i) => (
                    <Paper key={i} withBorder p="xs" radius="md">
                      <Group justify="space-between" wrap="wrap">
                        <Text size="sm">
                          {productName(o.product_code)}: {money(o.amount)} на {formatTerm(o.term_months)}, {formatRate(o.rate_percent)}
                        </Text>
                        <Group gap={6}>
                          <Text size="sm" className="num">
                            {money(o.monthly_payment)}/мес
                          </Text>
                          {o.recommended && <Badge color="green" size="xs">рекомендуемый</Badge>}
                        </Group>
                      </Group>
                    </Paper>
                  ))}
                </>
              )}
              {auto.values && (
                <KeyValue
                  cols={2}
                  items={['allowed_payment', 'requested_payment', 'income_confirmed', 'max_amount_requested_term']
                    .filter((k) => auto.values?.[k] !== undefined)
                    .map((k) => ({ label: DECISION_VALUE_LABELS[k] ?? k, value: money(auto.values?.[k]) }))}
                />
              )}
            </Stack>
          )}
        </SectionCard>
      </SimpleGrid>
      {card.offer && (
        <SectionCard title="Предложение клиенту">
          <Text size="sm" mb="xs">
            {OUTCOME_LABELS[card.offer.outcome] ?? card.offer.outcome}, статус {card.offer.status}, действует до {card.offer.expires_text}
          </Text>
          <Stack gap={6}>
            {card.offer.options.map((o) => (
              <Paper key={o.id} withBorder p="xs" radius="md">
                <Group justify="space-between" wrap="wrap">
                  <Text size="sm">
                    {o.product_name}: {formatMoney(o.amount)} на {formatTerm(o.term_months)}, {formatRate(o.rate_percent)}
                  </Text>
                  <Group gap={6}>
                    {card.offer?.selected_option_id === o.id && <Badge color="green" size="xs">выбран клиентом</Badge>}
                    {o.recommended && <Badge size="xs" variant="light">рекомендуемый</Badge>}
                  </Group>
                </Group>
              </Paper>
            ))}
          </Stack>
        </SectionCard>
      )}
      {card.loan && (
        <Alert color="green" title="Кредит выдан">
          {formatMoney(card.loan.amount)}, договор {card.loan.contract_number}, счет {card.loan.account_number_masked}, {formatDateTime(card.loan.issued_at)}
        </Alert>
      )}
      <AiSummary card={card} />
    </Stack>
  );
}

function factorValue(v: unknown): string {
  if (v === null || v === undefined) return 'нет данных';
  if (v === 'NO') return 'нет';
  if (v === 'YES') return 'да';
  const n = typeof v === 'number' ? v : typeof v === 'string' && /^-?\d+(\.\d+)?$/.test(v) ? Number(v) : null;
  if (n !== null && Math.abs(n) >= 1000) return formatMoney(n);
  return String(v);
}

function ScoringTab({ card }: { card: StaffCard }) {
  const s = card.scoring;
  if (!s) return <EmptyState title="Скоринг еще не рассчитан" text="Скоринг считается после обогащения данными из источников." />;
  const max = Math.max(...s.factor_contributions.map((f) => Math.abs(f.points)), 1);
  return (
    <Stack gap="lg">
      <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="md">
        <Paper withBorder radius="lg" p="md">
          <Text size="xs" c="dimmed">
            Балл
          </Text>
          <Text className="money-xl">{s.score}</Text>
        </Paper>
        <Paper withBorder radius="lg" p="md">
          <Text size="xs" c="dimmed">
            Грейд
          </Text>
          <Text className="money-xl">{s.grade}</Text>
        </Paper>
        <Paper withBorder radius="lg" p="md">
          <Text size="xs" c="dimmed">
            Вероятность дефолта (PD)
          </Text>
          <Text className="money-xl">{formatShare(Number(s.pd), 2)}</Text>
        </Paper>
      </SimpleGrid>
      <SectionCard
        title={
          <Group gap={6} component="span">
            <IconChartBar size={20} aria-hidden /> Вклад факторов
          </Group>
        }
      >
        <div className="table-scroll">
          <Table striped verticalSpacing={6} style={{ minWidth: 640 }}>
            <Table.Caption>Скоринговая карта {s.scorecard_version}: балл = базовые баллы + сумма баллов факторов</Table.Caption>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Фактор</Table.Th>
                <Table.Th>Значение</Table.Th>
                <Table.Th>Интервал</Table.Th>
                <Table.Th ta="right">Баллы</Table.Th>
                <Table.Th>
                  <span className="visually-hidden">Вклад, график</span>
                </Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {s.factor_contributions.map((f) => (
                <Table.Tr key={f.factor_code}>
                  <Table.Td>{f.factor_name}</Table.Td>
                  <Table.Td className="num">{factorValue(f.value)}</Table.Td>
                  <Table.Td>{f.bin_label ?? ''}</Table.Td>
                  <Table.Td ta="right" fw={600} c={f.points < 0 ? 'red.8' : 'green.8'}>
                    {f.points > 0 ? `+${f.points}` : f.points}
                  </Table.Td>
                  <Table.Td w={140} aria-hidden>
                    <div style={{ height: 8, borderRadius: 4, background: '#eef0f3', position: 'relative' }}>
                      <div
                        style={{
                          position: 'absolute',
                          height: 8,
                          borderRadius: 4,
                          left: f.points >= 0 ? '50%' : `${50 - (Math.abs(f.points) / max) * 50}%`,
                          width: `${(Math.abs(f.points) / max) * 50}%`,
                          background: f.points >= 0 ? '#2f9e44' : '#e03131',
                        }}
                      />
                    </div>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </div>
        <Text size="xs" c="dimmed" mt="sm">
          Версия {s.scorecard_version}, sha256 {s.scorecard_sha256?.slice(0, 12)}..., рассчитан {formatDateTime(s.calculated_at)}. Скоринг оценивает риск, решение принимает
          кредитная политика (вкладка "Политика").
        </Text>
      </SectionCard>
    </Stack>
  );
}

function DecisionBlock({ d }: { d: StaffDecision }) {
  return (
    <Paper withBorder radius="lg" p="md">
      <Stack gap="sm">
        <Group justify="space-between" wrap="wrap" gap="xs">
          <Group gap="xs">
            <Badge variant="light" color={d.outcome === 'DECLINED' ? 'red' : d.outcome === 'APPROVED' ? 'green' : 'violet'}>
              {OUTCOME_LABELS[d.outcome] ?? d.outcome}
            </Badge>
            <Badge variant="outline" color="gray">
              {d.mode === 'AUTO' ? 'автоматически' : 'специалистом'}
            </Badge>
            <Badge variant="outline" color={d.status === 'PROPOSED' ? 'orange' : 'gray'}>
              {d.status === 'PROPOSED' ? 'проект, ждет 4 глаза' : d.status === 'FINAL' ? 'итоговое' : d.status}
            </Badge>
            {d.override && <Badge color="orange">переопределение</Badge>}
          </Group>
          <Text size="xs" c="dimmed">
            {formatStamp(d.created_at)}
          </Text>
        </Group>
        {d.rules_path.length > 0 && (
          <div className="table-scroll">
            <Table verticalSpacing={4} style={{ minWidth: 420 }}>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Правило</Table.Th>
                  <Table.Th>Название</Table.Th>
                  <Table.Th>Результат</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {d.rules_path.map((r) => (
                  <Table.Tr key={r.rule}>
                    <Table.Td>
                      <Code>{r.rule}</Code>
                    </Table.Td>
                    <Table.Td>{RULE_LABELS[r.rule] ?? r.rule}</Table.Td>
                    <Table.Td>
                      <Badge size="sm" variant={r.result === 'FIRE' ? 'filled' : 'light'} color={r.result === 'FIRE' ? 'brand' : 'gray'}>
                        {RULE_RESULT_LABELS[r.result] ?? r.result}
                      </Badge>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </div>
        )}
        {d.reasons.length > 0 && (
          <Stack gap={4}>
            <Text size="sm" fw={600}>
              Коды причин
            </Text>
            {d.reasons.map((r) => (
              <Text key={r.code} size="sm">
                <Code>{r.code}</Code> {r.employee_text}
              </Text>
            ))}
          </Stack>
        )}
        {d.values && Object.keys(d.values).length > 0 && (
          <KeyValue
            cols={2}
            items={Object.entries(d.values).map(([k, v]) => ({
              label: DECISION_VALUE_LABELS[k] ?? k,
              value: k === 'revenue_mismatch' || k === 'max_debt_load' ? formatShare(Number(v), 2) : k === 'rate_percent' ? formatRate(String(v)) : /payment|income|amount/.test(k) ? money(v) : String(v),
            }))}
          />
        )}
        {d.proposed_options && d.proposed_options.length > 0 && (
          <Stack gap={4}>
            <Text size="sm" fw={600}>
              Варианты решения
            </Text>
            {d.proposed_options.map((o, i) => (
              <Text key={i} size="sm">
                {productName(o.product_code)}: {money(o.amount)} на {formatTerm(o.term_months)}, {formatRate(o.rate_percent)}, платеж {money(o.monthly_payment)}
              </Text>
            ))}
          </Stack>
        )}
        {d.comment && (
          <Text size="sm">
            <b>Комментарий:</b> {d.comment}
          </Text>
        )}
        <Text size="xs" c="dimmed">
          Политика {d.policy_version ?? 'нет'}, скоринговая карта {d.scorecard_version ?? 'нет'}
          {d.decided_by ? `, решил ${d.decided_by}` : ''}
          {d.proposed_by ? `, автор проекта ${d.proposed_by}` : ''}
          {d.confirmed_by ? `, подтвердил ${d.confirmed_by}` : ''}
          {d.four_eyes_trigger ? `, 4 глаза: ${d.four_eyes_trigger === 'OVERRIDE' ? 'переопределение' : 'лимит полномочий'}` : ''}
        </Text>
      </Stack>
    </Paper>
  );
}

function PolicyTab({ card }: { card: StaffCard }) {
  if (card.decisions.length === 0) return <EmptyState title="Решений пока нет" text="Кредитная политика применяется после скоринга." />;
  return (
    <Stack gap="md">
      <Text size="sm" c="dimmed">
        Путь правил политики POL-01...POL-07 с кодами причин и значениями расчета. Новые решения сверху.
      </Text>
      {[...card.decisions].reverse().map((d) => (
        <DecisionBlock key={d.id} d={d} />
      ))}
    </Stack>
  );
}

function renderValue(v: unknown): ReactNode {
  if (v === null || v === undefined) return 'нет данных';
  if (typeof v === 'boolean') return v ? 'да' : 'нет';
  if (typeof v === 'object') return <Code block>{JSON.stringify(v, null, 2)}</Code>;
  return String(v);
}

function SourceBlock({ source }: { source: SourceInfo }) {
  const [open, setOpen] = useState(false);
  const ok = source.latest?.outcome === 'SUCCESS';
  return (
    <Paper withBorder radius="lg" p="md">
      <Group justify="space-between" wrap="wrap" gap="xs">
        <div>
          <Text fw={600}>{SOURCE_LABELS[source.source] ?? source.source}</Text>
          <Text size="xs" c="dimmed">
            {source.latest ? `ответ ${formatDateTime(source.latest.received_at)}` : 'ответа нет'}, попыток {source.attempts.length}
          </Text>
        </div>
        <Group gap="xs">
          <Badge color={ok ? 'green' : 'red'} variant="light">
            {ok ? 'получено' : (source.latest?.outcome ?? 'нет ответа')}
          </Badge>
          <Button size="xs" variant="subtle" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
            {open ? 'Скрыть' : 'Подробнее'}
          </Button>
        </Group>
      </Group>
      <Collapse in={open}>
        <Stack gap="sm" mt="sm">
          <div className="table-scroll">
            <Table verticalSpacing={4} fz="sm" style={{ minWidth: 560 }}>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>#</Table.Th>
                  <Table.Th>Этап</Table.Th>
                  <Table.Th>Результат</Table.Th>
                  <Table.Th>Ошибка</Table.Th>
                  <Table.Th>Время</Table.Th>
                  <Table.Th ta="right">Длительность</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {source.attempts.map((a, i) => (
                  <Table.Tr key={i}>
                    <Table.Td>{a.attempt}</Table.Td>
                    <Table.Td>{a.stage}</Table.Td>
                    <Table.Td>{a.outcome}</Table.Td>
                    <Table.Td>{a.error_code ?? ''}</Table.Td>
                    <Table.Td>{formatStamp(a.requested_at)}</Table.Td>
                    <Table.Td ta="right">{a.duration_ms !== null ? `${a.duration_ms} мс` : ''}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </div>
          {source.latest?.data && (
            <KeyValue cols={2} items={Object.entries(source.latest.data).map(([k, v]) => ({ label: <Code>{k}</Code>, value: renderValue(v) }))} />
          )}
        </Stack>
      </Collapse>
    </Paper>
  );
}

function SourcesTab({ card }: { card: StaffCard }) {
  return (
    <Stack gap="md">
      {card.company && <CompanyBlock company={card.company} />}
      {card.sources.length === 0 && <EmptyState title="Источники еще не опрашивались" />}
      {card.sources.map((s) => (
        <SourceBlock key={s.source} source={s} />
      ))}
    </Stack>
  );
}

function FormTab({ card }: { card: StaffCard }) {
  return (
    <Stack gap="lg">
      {card.field_changes.length > 0 && (
        <SectionCard title="Изменения анкеты после дозапросов">
          <div className="table-scroll">
            <Table verticalSpacing={4} style={{ minWidth: 560 }}>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Поле</Table.Th>
                  <Table.Th>Было</Table.Th>
                  <Table.Th>Стало</Table.Th>
                  <Table.Th>Когда</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {card.field_changes.map((c, i) => (
                  <Table.Tr key={i}>
                    <Table.Td>{c.field_label ?? c.field_name}</Table.Td>
                    <Table.Td>{c.old_value ?? ''}</Table.Td>
                    <Table.Td>{c.new_value ?? ''}</Table.Td>
                    <Table.Td>{formatStamp(c.changed_at)}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </div>
        </SectionCard>
      )}
      <SectionCard title="Документы клиента">
        {card.documents.length === 0 ? (
          <Text c="dimmed">Документов нет.</Text>
        ) : (
          <Stack gap={6}>
            {card.documents.map((d) => (
              <Group key={d.id} justify="space-between" wrap="wrap" p="xs" style={{ border: '1px solid var(--app-border)', borderRadius: 10 }}>
                <div>
                  <Text size="sm" fw={600}>
                    {d.document_title}
                  </Text>
                  <Text size="xs" c="dimmed">
                    {d.file_name}, {formatFileSize(d.size_bytes)}, {formatStamp(d.uploaded_at)}
                    {d.info_request_item_id ? ', ответ на дозапрос' : ''}
                  </Text>
                </div>
                <Button
                  size="xs"
                  variant="light"
                  leftSection={<IconDownload size={14} aria-hidden />}
                  onClick={() => void openProtectedFile(() => api.staffDocument(card.id, d.id), d.file_name).catch((e: unknown) => toast.error(e))}
                >
                  Скачать
                </Button>
              </Group>
            ))}
            <Text size="xs" c="dimmed">
              Каждое скачивание записывается в журнал аудита.
            </Text>
          </Stack>
        )}
      </SectionCard>
      <SectionCard title="Согласия клиента">
        <div className="table-scroll">
          <Table verticalSpacing={4} style={{ minWidth: 640 }}>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Согласие</Table.Th>
                <Table.Th>Версия текста</Table.Th>
                <Table.Th>Дано</Table.Th>
                <Table.Th>Действует до</Table.Th>
                <Table.Th>IP</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {card.consents.map((c) => (
                <Table.Tr key={c.consent_type}>
                  <Table.Td>{c.consent_type}</Table.Td>
                  <Table.Td>{c.text_version}</Table.Td>
                  <Table.Td>{c.revoked_at ? `отозвано ${formatStamp(c.revoked_at)}` : formatStamp(c.granted_at)}</Table.Td>
                  <Table.Td>{c.expires_at ? formatStamp(c.expires_at) : 'бессрочно'}</Table.Td>
                  <Table.Td>{c.ip_address ?? ''}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </div>
      </SectionCard>
      <SectionCard title="Анкета при отправке">
        <KeyValue cols={3} items={Object.entries(card.submitted_snapshot ?? card.form).map(([k, v]) => ({ label: <Code>{k}</Code>, value: renderValue(v) }))} />
      </SectionCard>
    </Stack>
  );
}

function InfoTab({ card }: { card: StaffCard }) {
  if (card.info_requests.length === 0) return <EmptyState title="Дозапросов не было" />;
  return (
    <Stack gap="md">
      {card.info_requests.map((r) => (
        <SectionCard
          key={r.id}
          title={`Дозапрос от ${formatDateTime(r.created_at)}`}
          actions={
            <Badge variant="light" color={r.status === 'OPEN' ? 'orange' : 'green'}>
              {r.status === 'OPEN' ? `ждем ответ до ${formatDateTime(r.due_at)}` : `ответ ${formatDateTime(r.answered_at)}`}
            </Badge>
          }
        >
          <Stack gap="sm">
            {r.items.map((it, i) => (
              <Paper key={it.id} withBorder p="sm" radius="md">
                <Text size="sm" fw={600}>
                  {i + 1}. {it.reason_code} {it.employee_text ? `: ${it.employee_text}` : ''}
                </Text>
                <Text size="sm" c="dimmed">
                  Клиенту: {it.client_text}
                </Text>
                <Text size="sm" mt={4}>
                  Ответ:{' '}
                  {it.answer_text ?? it.answer_value ?? (it.document_ids.length ? `документов: ${it.document_ids.length}` : <Text span c="dimmed">нет</Text>)}
                </Text>
              </Paper>
            ))}
          </Stack>
        </SectionCard>
      ))}
    </Stack>
  );
}

function eventSummary(e: HistoryEvent): string {
  const p = e.payload;
  if (e.event_type === 'STATUS_CHANGED') return `${String(p.from_status ?? 'нет')} -> ${String(p.to_status ?? '')} (${String(p.transition_id ?? '')})`;
  const keys = ['outcome', 'reason_code', 'source', 'attempt', 'error_code', 'view_context', 'consent_type', 'document_type'];
  return keys
    .filter((k) => p[k] !== undefined && p[k] !== null)
    .map((k) => `${k}: ${String(p[k])}`)
    .join(', ');
}

function HistoryTab({ card }: { card: StaffCard }) {
  const [onlyStatus, setOnlyStatus] = useState(false);
  const events = onlyStatus ? card.history.filter((h) => h.event_type === 'STATUS_CHANGED') : card.history;
  return (
    <Stack gap="lg">
      <SectionCard
        title={`События заявки (${events.length})`}
        actions={
          <Button size="xs" variant="subtle" onClick={() => setOnlyStatus((v) => !v)} aria-pressed={onlyStatus}>
            {onlyStatus ? 'Показать все события' : 'Только смены статуса'}
          </Button>
        }
      >
        <div className="table-scroll" style={{ maxHeight: 560 }}>
          <Table striped stickyHeader verticalSpacing={4} fz="sm" style={{ minWidth: 760 }}>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Время</Table.Th>
                <Table.Th>Событие</Table.Th>
                <Table.Th>Кто</Table.Th>
                <Table.Th>Детали</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {[...events].reverse().map((e) => (
                <Table.Tr key={e.event_id}>
                  <Table.Td style={{ whiteSpace: 'nowrap' }}>{formatStamp(e.occurred_at)}</Table.Td>
                  <Table.Td>
                    <Code>{e.event_type}</Code>
                  </Table.Td>
                  <Table.Td>{e.actor ?? ROLE_LABELS[e.actor_type] ?? e.actor_type}</Table.Td>
                  <Table.Td>{eventSummary(e)}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </div>
      </SectionCard>
      {card.audit && (
        <SectionCard title="Журнал аудита по заявке">
          <div className="table-scroll" style={{ maxHeight: 420 }}>
            <Table striped stickyHeader verticalSpacing={4} fz="sm" style={{ minWidth: 760 }}>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Время</Table.Th>
                  <Table.Th>Кто</Table.Th>
                  <Table.Th>Действие</Table.Th>
                  <Table.Th>Результат</Table.Th>
                  <Table.Th>IP</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {[...card.audit].reverse().map((a, i) => (
                  <Table.Tr key={i}>
                    <Table.Td style={{ whiteSpace: 'nowrap' }}>{formatStamp(a.occurred_at)}</Table.Td>
                    <Table.Td>
                      {a.actor_login} <Text span size="xs" c="dimmed">({ROLE_LABELS[a.actor_role ?? ''] ?? a.actor_role})</Text>
                    </Table.Td>
                    <Table.Td>
                      <Code>{a.action}</Code>
                    </Table.Td>
                    <Table.Td>{a.result}</Table.Td>
                    <Table.Td>{a.ip_address}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </div>
        </SectionCard>
      )}
    </Stack>
  );
}

function CommentsTab({ card }: { card: StaffCard }) {
  const queryClient = useQueryClient();
  const [body, setBody] = useState('');
  const add = useMutation({
    mutationFn: () => api.addComment(card.id, body.trim()),
    onSuccess: () => {
      setBody('');
      void queryClient.invalidateQueries({ queryKey: qk.bankCard(card.id) });
      toast.success('Комментарий добавлен');
    },
    onError: (e) => toast.error(e),
  });
  return (
    <Stack gap="md">
      <Text size="sm" c="dimmed">
        Внутренние комментарии сотрудников. Клиент их не видит.
      </Text>
      {card.comments.length === 0 && <Text c="dimmed">Комментариев нет.</Text>}
      {card.comments.map((c) => (
        <Paper key={c.id} withBorder radius="md" p="sm">
          <Group justify="space-between" wrap="wrap">
            <Text size="sm" fw={600}>
              {c.author ?? 'Сотрудник'}
            </Text>
            <Text size="xs" c="dimmed">
              {formatStamp(c.created_at)} {c.kind !== 'COMMENT' ? `· ${c.kind}` : ''}
            </Text>
          </Group>
          <Text size="sm" style={{ whiteSpace: 'pre-wrap' }}>
            {c.body}
          </Text>
        </Paper>
      ))}
      {card.available_actions.includes('ADD_COMMENT') && (
        <Stack gap="xs">
          <Textarea label="Новый комментарий" autosize minRows={2} maxLength={2000} value={body} onChange={(e) => setBody(e.currentTarget.value)} />
          <Group>
            <Button onClick={() => add.mutate()} loading={add.isPending} disabled={body.trim().length === 0}>
              Добавить
            </Button>
          </Group>
        </Stack>
      )}
      <Title order={3} size="h6" c="dimmed" fw={400}>
        Комментарии к решениям (одобрение, отказ, возврат) сохраняются вместе с решением и видны на вкладке "Политика".
      </Title>
    </Stack>
  );
}
