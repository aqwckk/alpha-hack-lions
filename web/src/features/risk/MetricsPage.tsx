import { Badge, Group, Paper, SegmentedControl, Select, SimpleGrid, Stack, Table, Text, Title } from '@mantine/core';
import { IconAlertTriangle, IconCircleCheck, IconInfoCircle } from '@tabler/icons-react';
import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { Bar, BarChart, CartesianGrid, Cell, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { api } from '@/shared/api/endpoints';
import { qk } from '@/shared/api/queries';
import type { Metrics } from '@/shared/api/types';
import { formatDate, formatDuration, formatMoney, formatShare } from '@/shared/lib/format';
import { OUTCOME_LABELS, PRODUCT_NAMES, SOURCE_LABELS, STOP_FACTOR_LABELS } from '@/shared/lib/labels';
import { EmptyState, ErrorState, PageHeader, PageSkeleton, SectionCard } from '@/shared/ui/components';

const ACCENT = '#c92a2a';
const NEUTRAL = '#5c7cfa';
const OUTCOME_COLORS: Record<string, string> = { APPROVED: '#2f9e44', COUNTER_OFFER: '#1c7ed6', DECLINED: '#e03131' };

type Kpi = {
  key: keyof Metrics;
  label: string;
  kind: 'share' | 'duration' | 'number';
  /** "max": the value should not exceed the target. */
  direction?: 'min' | 'max';
  hint: string;
};

const KPIS: Kpi[] = [
  { key: 'north_star', label: 'North Star', kind: 'share', hint: 'Доля начатых заявок с понятным решением в срок SLA' },
  { key: 'time_to_decision_auto_median_sec', label: 'Время до решения (авто)', kind: 'duration', hint: 'Медиана от отправки до решения' },
  { key: 'time_to_decision_manual_median_sec', label: 'Время до решения (специалист)', kind: 'duration', hint: 'Медиана для ручного рассмотрения' },
  { key: 'auto_decision_share', label: 'Доля авторешений', kind: 'share', direction: 'min', hint: 'Итоговые решения без участия специалиста' },
  { key: 'manual_review_sla_share', label: 'SLA ручного рассмотрения', kind: 'share', direction: 'min', hint: 'Ручные решения без нарушения срока' },
  { key: 'queue_wait_median_sec', label: 'Ожидание в очереди', kind: 'duration', hint: 'Медиана от постановки в очередь до "Взять в работу"' },
  { key: 'wizard_conversion', label: 'Конверсия подбора', kind: 'share', direction: 'min', hint: 'Сессии подбора, закончившиеся черновиком' },
  { key: 'fill_conversion', label: 'Конверсия заполнения', kind: 'share', direction: 'min', hint: 'Черновики, которые отправили' },
  { key: 'fill_duration_median_sec', label: 'Время заполнения', kind: 'duration', direction: 'max', hint: 'Медиана от черновика до отправки' },
  { key: 'prefill_share', label: 'Автозаполнение полей', kind: 'share', direction: 'min', hint: 'Поля, подставленные из реестров' },
  { key: 'info_request_share', label: 'Доля дозапросов', kind: 'share', direction: 'max', hint: 'Отправленные заявки хотя бы с одним дозапросом' },
  { key: 'approval_rate', label: 'Уровень одобрения', kind: 'share', hint: 'Одобрения и контрпредложения среди решений' },
  { key: 'offer_acceptance', label: 'Принятие предложений', kind: 'share', direction: 'min', hint: 'Принятые предложения банка' },
  { key: 'counter_offer_acceptance', label: 'Принятие контрпредложений', kind: 'share', direction: 'min', hint: 'Принятые контрпредложения' },
  { key: 'override_share', label: 'Переопределения', kind: 'share', hint: 'Ручные решения против рекомендации политики' },
  { key: 'integration_failed_attempt_share', label: 'Сбои источников', kind: 'share', hint: 'Неуспешные попытки к внешним источникам' },
  { key: 'end_to_end_conversion', label: 'Сквозная конверсия', kind: 'share', hint: 'Заявки, дошедшие до выдачи' },
  { key: 'grade_psi', label: 'PSI грейдов', kind: 'number', direction: 'max', hint: 'Стабильность скоринга: меньше 0,1 стабильно' },
];

function fmt(kind: Kpi['kind'], v: number | null | undefined): string {
  if (v === null || v === undefined) return 'недостаточно данных';
  if (kind === 'share') return formatShare(v);
  if (kind === 'duration') return formatDuration(v);
  return new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 4 }).format(v);
}

function KpiTile({ kpi, metrics }: { kpi: Kpi; metrics: Metrics }) {
  const value = metrics[kpi.key] as number | null | undefined;
  const target = metrics.targets[kpi.key as string];
  const hasTarget = target !== undefined && kpi.direction && typeof value === 'number';
  const ok = hasTarget ? (kpi.direction === 'max' ? value <= target : value >= target) : null;
  return (
    <Paper withBorder radius="lg" p="md">
      <Stack gap={4}>
        <Text size="sm" c="dimmed">
          {kpi.label}
        </Text>
        <Text fw={700} size="xl" className="num">
          {fmt(kpi.kind, value)}
        </Text>
        {hasTarget && (
          <Group gap={4}>
            {ok ? <IconCircleCheck size={16} color="var(--mantine-color-green-7)" aria-hidden /> : <IconAlertTriangle size={16} color="var(--mantine-color-orange-7)" aria-hidden />}
            <Text size="xs" c={ok ? 'green.8' : 'orange.8'}>
              {ok ? 'в норме' : 'узкое место'}: ориентир {kpi.direction === 'max' ? 'не выше' : 'не ниже'} {fmt(kpi.kind, target)}
            </Text>
          </Group>
        )}
        <Text size="xs" c="dimmed">
          {kpi.hint}
        </Text>
      </Stack>
    </Paper>
  );
}

interface Datum {
  name: string;
  value: number;
  color?: string;
}

/** Horizontal bar chart with the same data as an accessible table (charts never rely on color alone). */
function BarBlock({ title, data, format, caption }: { title: string; data: Datum[]; format: (v: number) => string; caption: string }) {
  if (data.length === 0) {
    return (
      <SectionCard title={title}>
        <Text c="dimmed" size="sm">
          Недостаточно данных за период
        </Text>
      </SectionCard>
    );
  }
  const height = Math.max(160, data.length * 38 + 30);
  return (
    <SectionCard title={title}>
      <div style={{ width: '100%', height }} aria-hidden>
        <ResponsiveContainer>
          <BarChart data={data} layout="vertical" margin={{ top: 4, right: 72, left: 8, bottom: 4 }}>
            <CartesianGrid horizontal={false} stroke="#eceef2" />
            <XAxis type="number" hide domain={[0, 'dataMax']} />
            <YAxis type="category" dataKey="name" width={170} tick={{ fontSize: 12, fill: '#3b4250' }} tickLine={false} axisLine={false} />
            <Tooltip formatter={(v) => format(Number(v))} cursor={{ fill: 'rgba(0,0,0,0.04)' }} />
            <Bar dataKey="value" radius={[0, 6, 6, 0]} isAnimationActive={false}>
              {data.map((d) => (
                <Cell key={d.name} fill={d.color ?? NEUTRAL} />
              ))}
              <LabelList dataKey="value" position="right" formatter={(v: unknown) => format(Number(v))} style={{ fontSize: 12, fill: '#1d2129' }} />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <Table className="visually-hidden">
        <Table.Caption>{caption}</Table.Caption>
        <Table.Tbody>
          {data.map((d) => (
            <Table.Tr key={d.name}>
              <Table.Th>{d.name}</Table.Th>
              <Table.Td>{format(d.value)}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </SectionCard>
  );
}

const FUNNEL_LABELS: Record<string, string> = {
  wizard_started: 'Начали подбор',
  created: 'Создали заявку',
  submitted: 'Отправили',
  decided: 'Получили решение',
  offer_accepted: 'Приняли предложение',
  signed: 'Подписали',
  issued: 'Выдано',
};

function entries(obj: Partial<Record<string, number>>, labels?: Record<string, string>, colors?: Record<string, string>): Datum[] {
  return Object.entries(obj)
    .filter((e): e is [string, number] => typeof e[1] === 'number')
    .map(([k, v]) => ({ name: labels?.[k] ?? k, value: v, ...(colors?.[k] ? { color: colors[k] } : {}) }));
}

export function MetricsPage() {
  const [period, setPeriod] = useState('30');
  const [product, setProduct] = useState<string | null>(null);
  const query = useQuery({
    queryKey: qk.metrics(Number(period), product ?? ''),
    queryFn: () => api.metrics(Number(period), product ?? undefined),
    placeholderData: (prev) => prev,
  });
  const m = query.data;
  const intNum = (v: number) => new Intl.NumberFormat('ru-RU').format(v);
  return (
    <>
      <PageHeader title="Метрики процесса" subtitle="Воронка клиента, скорость и качество решений, надежность интеграций. Расчет по журналу событий." />
      <Stack gap="lg">
        <Group gap="md" wrap="wrap">
          <SegmentedControl
            value={period}
            onChange={setPeriod}
            data={[
              { value: '7', label: '7 дней' },
              { value: '30', label: '30 дней' },
              { value: '90', label: '90 дней' },
            ]}
            aria-label="Период"
          />
          <Select
            placeholder="Все продукты"
            clearable
            data={Object.entries(PRODUCT_NAMES).map(([value, label]) => ({ value, label }))}
            value={product}
            onChange={setProduct}
            aria-label="Продукт"
            w={240}
          />
        </Group>
        {query.isPending && <PageSkeleton lines={3} />}
        {query.isError && <ErrorState error={query.error} onRetry={() => void query.refetch()} />}
        {m && m.applications_created === 0 && <EmptyState title="Недостаточно данных за период" text="Пройдите демо-сценарии или выберите больший период." />}
        {m && m.applications_created > 0 && (
          <>
            <Group gap="sm">
              <Badge variant="light" size="lg">
                Заявок создано: {m.applications_created}
              </Badge>
              <Text size="sm" c="dimmed">
                с {formatDate(m.period.start)} по {formatDate(m.period.end)}
              </Text>
              {!m.period.complete && (
                <Badge color="orange" variant="light" leftSection={<IconInfoCircle size={12} aria-hidden />}>
                  период не завершен
                </Badge>
              )}
            </Group>
            <SimpleGrid cols={{ base: 1, xs: 2, md: 3, lg: 4 }} spacing="md">
              {KPIS.map((k) => (
                <KpiTile key={k.key} kpi={k} metrics={m} />
              ))}
            </SimpleGrid>
            <SimpleGrid cols={{ base: 1, lg: 2 }} spacing="lg">
              <BarBlock title="Воронка" data={entries(m.funnel, FUNNEL_LABELS)} format={intNum} caption="Воронка заявок: число заявок на каждом этапе" />
              <BarBlock
                title="Структура исходов"
                data={entries(m.outcomes, OUTCOME_LABELS, OUTCOME_COLORS)}
                format={(v) => formatShare(v)}
                caption="Доли итоговых решений по исходу"
              />
              <BarBlock title="Распределение по грейдам" data={entries(m.grade_distribution)} format={(v) => formatShare(v)} caption="Доли заявок по грейдам скоринга" />
              <BarBlock
                title="Отказы по стоп-факторам"
                data={entries(m.stop_factor_codes, STOP_FACTOR_LABELS).map((d) => ({ ...d, color: ACCENT }))}
                format={intNum}
                caption="Число заявок по коду стоп-фактора"
              />
              <BarBlock
                title="Сбои внешних источников"
                data={entries(m.integration_failures_by_source, SOURCE_LABELS).map((d) => ({ ...d, color: '#f08c00' }))}
                format={intNum}
                caption="Неуспешные попытки по источникам"
              />
              <SectionCard title="Надежность и риск">
                <Table verticalSpacing={6}>
                  <Table.Tbody>
                    <Table.Tr>
                      <Table.Th>Отложенные повторы обогащения</Table.Th>
                      <Table.Td>{m.enrichment_retries ?? 0}</Table.Td>
                    </Table.Tr>
                    <Table.Tr>
                      <Table.Th>Заявки с ошибкой обработки</Table.Th>
                      <Table.Td>{m.processing_error_applications ?? 0}</Table.Td>
                    </Table.Tr>
                    <Table.Tr>
                      <Table.Th>Выбрано кредитных линий</Table.Th>
                      <Table.Td>{m.credit_line_chosen ?? 0}</Table.Td>
                    </Table.Tr>
                    <Table.Tr>
                      <Table.Th>Доля отказов по стоп-факторам</Table.Th>
                      <Table.Td>{formatShare(m.stop_factor_share)}</Table.Td>
                    </Table.Tr>
                    <Table.Tr>
                      <Table.Th>Ожидаемые потери выданных</Table.Th>
                      <Table.Td className="num">{formatMoney(m.expected_loss_issued)}</Table.Td>
                    </Table.Tr>
                  </Table.Tbody>
                </Table>
              </SectionCard>
            </SimpleGrid>
            <Title order={2} size="h6" c="dimmed" fw={400}>
              Формулы метрик: docs/analytics/metrics.md. Данные синтетические: история за 90 дней плюс заявки, созданные в демо.
            </Title>
          </>
        )}
      </Stack>
    </>
  );
}

export default MetricsPage;
