import { Badge, Button, Code, Collapse, Group, Stack, Table, Tabs, Text } from '@mantine/core';
import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { api } from '@/shared/api/endpoints';
import { qk } from '@/shared/api/queries';
import { formatDate, formatDateTime, formatMoney, formatRate, formatShare } from '@/shared/lib/format';
import { ErrorState, KeyValue, PageHeader, PageSkeleton, SectionCard } from '@/shared/ui/components';

type Json = Record<string, unknown>;
const obj = (v: unknown): Json => (typeof v === 'object' && v !== null && !Array.isArray(v) ? (v as Json) : {});
const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
const s = (v: unknown): string => (v === null || v === undefined ? '' : Array.isArray(v) ? v.join(', ') : String(v));

function RawJson({ value }: { value: unknown }) {
  const [open, setOpen] = useState(false);
  return (
    <Stack gap="xs">
      <Group>
        <Button size="xs" variant="subtle" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
          {open ? 'Скрыть JSON' : 'Показать весь конфиг (JSON, только чтение)'}
        </Button>
      </Group>
      <Collapse in={open}>{open && <pre className="json-view">{JSON.stringify(value, null, 2)}</pre>}</Collapse>
    </Stack>
  );
}

function PolicyView({ content }: { content: Json }) {
  const products = obj(content.products);
  const debt = obj(content.max_debt_load_by_grade);
  const premium = obj(content.rate_premium_by_grade);
  const stop = obj(content.stop_factors);
  const authority = obj(content.authority);
  return (
    <Stack gap="lg">
      <SectionCard title="Продукты и пороги">
        <div className="table-scroll">
          <Table striped verticalSpacing={6} fz="sm" style={{ minWidth: 900 }}>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Продукт</Table.Th>
                <Table.Th>Сумма</Table.Th>
                <Table.Th>Срок, мес.</Table.Th>
                <Table.Th>Базовая ставка</Table.Th>
                <Table.Th>Режим</Table.Th>
                <Table.Th>Грейды: авто / серые / отказ</Table.Th>
                <Table.Th>Возраст бизнеса</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {Object.entries(products).map(([code, raw]) => {
                const p = obj(raw);
                return (
                  <Table.Tr key={code}>
                    <Table.Td>
                      <Text fw={600} size="sm">
                        {s(p.name)}
                      </Text>
                      <Code>{code}</Code>
                    </Table.Td>
                    <Table.Td className="num">
                      от {formatMoney(s(p.amount_min))} до {formatMoney(s(p.amount_max))}
                    </Table.Td>
                    <Table.Td>
                      от {s(p.term_min_months)} до {s(p.term_max_months)}
                    </Table.Td>
                    <Table.Td>{formatRate(s(p.base_rate_percent))}</Table.Td>
                    <Table.Td>{s(p.review_mode)}</Table.Td>
                    <Table.Td>
                      {s(p.green_grades) || 'нет'} / {s(p.gray_grades) || 'нет'} / {s(p.decline_grades) || 'нет'}
                    </Table.Td>
                    <Table.Td>от {s(p.min_business_age_months)} мес.</Table.Td>
                  </Table.Tr>
                );
              })}
            </Table.Tbody>
          </Table>
        </div>
      </SectionCard>
      <SectionCard title="Матрица по грейдам">
        <Table verticalSpacing={6} fz="sm" maw={520}>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Грейд</Table.Th>
              <Table.Th>Предельная долговая нагрузка</Table.Th>
              <Table.Th>Надбавка к ставке</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {Object.keys(debt).map((g) => (
              <Table.Tr key={g}>
                <Table.Td fw={700}>{g}</Table.Td>
                <Table.Td>{formatShare(Number(debt[g]), 0)}</Table.Td>
                <Table.Td>+{formatRate(s(premium[g]))}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </SectionCard>
      <SectionCard title="Стоп-факторы и полномочия">
        <KeyValue
          cols={2}
          items={[
            { label: 'Блокирующие статусы компании', value: s(stop.blocked_company_statuses) },
            { label: 'Признаки недостоверности', value: s(stop.unreliable_flags) },
            { label: 'Текущая просрочка, дней от', value: s(stop.current_delinquency_min_days) },
            { label: 'Налоговая недоимка от', value: formatMoney(s(stop.tax_arrears_stop_amount)) },
            { label: 'Лимит полномочий андеррайтера', value: formatMoney(s(authority.underwriter_authority_limit)) },
            { label: 'Переопределение требует 4 глаз', value: authority.override_requires_risk_approval ? 'да' : 'нет' },
          ]}
        />
      </SectionCard>
      <SectionCard title="Правила политики">
        <Stack gap={6}>
          {arr(content.rules).map((raw) => {
            const r = obj(raw);
            return (
              <Group key={s(r.id)} gap="xs" wrap="nowrap" align="flex-start">
                <Code>{s(r.id)}</Code>
                <Text size="sm">
                  <b>{s(r.name)}</b>: {s(r.outcome)}. Коды: {s(r.reason_codes) || 'нет'}
                </Text>
              </Group>
            );
          })}
        </Stack>
      </SectionCard>
      <RawJson value={content} />
    </Stack>
  );
}

function ScorecardView({ content }: { content: Json }) {
  const pd = obj(content.pd_by_grade);
  return (
    <Stack gap="lg">
      <SectionCard title="Грейды">
        <Text size="sm" mb="sm">
          Балл = базовые баллы ({s(content.base_points)}) + сумма баллов факторов. Чем выше балл, тем ниже риск.
        </Text>
        <Table verticalSpacing={6} fz="sm" maw={520}>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Грейд</Table.Th>
              <Table.Th>Балл от</Table.Th>
              <Table.Th>PD</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {arr(content.grade_bands).map((raw) => {
              const g = obj(raw);
              return (
                <Table.Tr key={s(g.grade)}>
                  <Table.Td fw={700}>{s(g.grade)}</Table.Td>
                  <Table.Td>{g.min_score === null ? 'ниже' : s(g.min_score)}</Table.Td>
                  <Table.Td>{formatShare(Number(pd[s(g.grade)]), 2)}</Table.Td>
                </Table.Tr>
              );
            })}
          </Table.Tbody>
        </Table>
      </SectionCard>
      <SectionCard title="Факторы">
        <div className="table-scroll">
          <Table striped verticalSpacing={6} fz="sm" style={{ minWidth: 760 }}>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Фактор</Table.Th>
                <Table.Th>IV</Table.Th>
                <Table.Th>Интервалы и баллы</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {arr(content.factors).map((raw) => {
                const f = obj(raw);
                const bins = arr(f.bins).map(obj);
                const missing = obj(f.missing);
                return (
                  <Table.Tr key={s(f.code)}>
                    <Table.Td>
                      <Text size="sm">{s(f.name)}</Text>
                      <Code>{s(f.code)}</Code>
                    </Table.Td>
                    <Table.Td>{s(f.iv)}</Table.Td>
                    <Table.Td>
                      <Group gap={4}>
                        {bins.map((b) => (
                          <Badge key={s(b.id)} variant="light" color={Number(b.points) < 0 ? 'red' : 'green'} tt="none">
                            {s(b.label)}: {Number(b.points) > 0 ? '+' : ''}
                            {s(b.points)}
                          </Badge>
                        ))}
                        {missing.label !== undefined && (
                          <Badge variant="outline" color="gray" tt="none">
                            {s(missing.label)}: {s(missing.points)}
                          </Badge>
                        )}
                      </Group>
                    </Table.Td>
                  </Table.Tr>
                );
              })}
            </Table.Tbody>
          </Table>
        </div>
      </SectionCard>
      <RawJson value={content} />
    </Stack>
  );
}

function ConfigContent({ type }: { type: 'POLICY' | 'SCORECARD' }) {
  const query = useQuery({ queryKey: qk.configContent(type), queryFn: () => api.configContent(type), staleTime: Infinity });
  if (query.isPending) return <PageSkeleton lines={2} />;
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  const content = obj(query.data.content);
  return type === 'POLICY' ? <PolicyView content={content} /> : <ScorecardView content={content} />;
}

export function ConfigsPage() {
  const query = useQuery({ queryKey: qk.configs, queryFn: api.configs });
  return (
    <>
      <PageHeader title="Скоринг и политика" subtitle="Активные версии скоринговой карты и кредитной политики. Версии записываются в каждое решение." />
      <Stack gap="lg">
        {query.isPending && <PageSkeleton lines={2} />}
        {query.isError && <ErrorState error={query.error} onRetry={() => void query.refetch()} />}
        {query.data && (
          <SectionCard title="Активные версии">
            <div className="table-scroll">
              <Table verticalSpacing={6} style={{ minWidth: 720 }}>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Конфиг</Table.Th>
                    <Table.Th>Версия</Table.Th>
                    <Table.Th>Действует с</Table.Th>
                    <Table.Th>Автор</Table.Th>
                    <Table.Th>sha256</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {query.data.active.map((c) => (
                    <Table.Tr key={c.config_type}>
                      <Table.Td>{c.config_type === 'POLICY' ? 'Кредитная политика' : 'Скоринговая карта'}</Table.Td>
                      <Table.Td>
                        <Code>{c.version}</Code>
                      </Table.Td>
                      <Table.Td>{formatDate(c.effective_from)}</Table.Td>
                      <Table.Td>{c.author}</Table.Td>
                      <Table.Td>
                        <Code>{c.sha256.slice(0, 16)}...</Code>
                      </Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </div>
            {query.data.history.length > 0 && (
              <Text size="xs" c="dimmed" mt="sm">
                История загрузок:{' '}
                {query.data.history.map((h) => `${h.version} (первая загрузка ${formatDateTime(h.first_loaded_at)})`).join('; ')}
              </Text>
            )}
          </SectionCard>
        )}
        <Tabs defaultValue="POLICY" keepMounted={false}>
          <Tabs.List>
            <Tabs.Tab value="POLICY">Кредитная политика</Tabs.Tab>
            <Tabs.Tab value="SCORECARD">Скоринговая карта</Tabs.Tab>
          </Tabs.List>
          <Tabs.Panel value="POLICY" pt="md">
            <ConfigContent type="POLICY" />
          </Tabs.Panel>
          <Tabs.Panel value="SCORECARD" pt="md">
            <ConfigContent type="SCORECARD" />
          </Tabs.Panel>
        </Tabs>
      </Stack>
    </>
  );
}

export default ConfigsPage;
