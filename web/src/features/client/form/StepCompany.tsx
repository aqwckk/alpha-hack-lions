import { Alert, Badge, Group, Paper, Select, Skeleton, Stack, Text, TextInput, Title } from '@mantine/core';
import { IconAlertTriangle, IconBuildingBank, IconCloudOff } from '@tabler/icons-react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { Controller, type UseFormReturn } from 'react-hook-form';
import type { DraftValues } from './formModel';
import { withFreshVersion } from '@/shared/api/commands';
import { api } from '@/shared/api/endpoints';
import { storeApplication, useDictionaries } from '@/shared/api/queries';
import type { ClientApplication, CompanyInfo, PrefillResponse } from '@/shared/api/types';
import { formatDate, formatDateTime } from '@/shared/lib/format';
import { GLOSSARY } from '@/shared/lib/glossary';
import { checkInn, INN_MESSAGES } from '@/shared/lib/inn';
import { APPLICANT_TYPES, COMPANY_STATUSES, SME_CATEGORIES, TAX_REGIMES } from '@/shared/lib/labels';
import { KeyValue, SectionCard } from '@/shared/ui/components';
import { Hint, Term } from '@/shared/ui/Term';
import { toast } from '@/shared/ui/toast';

export function StepCompany({ app, form }: { app: ClientApplication; form: UseFormReturn<DraftValues> }) {
  const dictionaries = useDictionaries();
  const queryClient = useQueryClient();
  const serverInn = typeof app.form.applicant_inn === 'string' ? app.form.applicant_inn : '';
  const [inn, setInn] = useState(serverInn);
  const [result, setResult] = useState<PrefillResponse['prefill'] | null>(null);
  const lastRequested = useRef<string>(app.inn_check_status === 'NOT_CHECKED' ? '' : serverInn);

  const check = inn.length === 10 || inn.length === 12 ? checkInn(inn) : null;
  const localError = inn.length > 0 && inn.length !== 10 && inn.length !== 12 && inn.length >= 10 ? INN_MESSAGES.INN_LENGTH : check && !check.ok ? INN_MESSAGES[check.code] : null;

  const prefill = useMutation({
    mutationFn: (value: string) => withFreshVersion(queryClient, app.id, (version) => api.prefill(app.id, value, version)),
    onSuccess: (res) => {
      storeApplication(queryClient, res.application);
      setResult(res.prefill);
    },
    onError: (e) => toast.error(e, 'Не удалось проверить ИНН'),
  });

  // INN is checked locally (length and checksum) before any registry request (US-05).
  useEffect(() => {
    if (!check?.ok || inn === lastRequested.current) return;
    const t = setTimeout(() => {
      lastRequested.current = inn;
      prefill.mutate(inn);
    }, 300);
    return () => clearTimeout(t);
    // prefill.mutate is stable; the effect reacts to the typed value only
  }, [inn, check?.ok]);

  const notFound = (result?.status ?? (app.inn_check_status === 'NOT_FOUND' ? 'NOT_FOUND' : null)) === 'NOT_FOUND';
  const unavailable = (result?.status ?? (app.inn_check_status === 'UNAVAILABLE' ? 'SOURCE_UNAVAILABLE' : null)) === 'SOURCE_UNAVAILABLE';
  const company = app.company as CompanyInfo | null;
  const serverError = notFound ? (result?.message ?? 'Компания или ИП с таким ИНН не найдены в госреестре. Проверьте ИНН') : null;

  return (
    <Stack gap="lg">
      <SectionCard title="Кто берет кредит">
        <Stack gap="md">
          <TextInput
            label="ИНН компании или ИП"
            description="10 цифр у компании, 12 у ИП. Сведения о компании подставятся сами"
            value={inn}
            onChange={(e) => setInn(e.currentTarget.value.replace(/\D/g, '').slice(0, 12))}
            inputMode="numeric"
            autoComplete="off"
            maw={360}
            size="md"
            error={localError ?? serverError}
            rightSection={prefill.isPending ? <Skeleton circle height={16} /> : <Hint term="ИНН" hint={GLOSSARY.inn} />}
            rightSectionPointerEvents="all"
            id="field-applicant_inn"
          />
          <Controller
            control={form.control}
            name="representative_role"
            render={({ field, fieldState }) => (
              <Select
                label="Кем вы являетесь в компании"
                placeholder="Выберите"
                data={(dictionaries.data?.representative_roles ?? []).map((r) => ({ value: r.code, label: r.title }))}
                value={field.value || null}
                onChange={(v) => field.onChange(v ?? '')}
                onBlur={field.onBlur}
                ref={field.ref}
                maw={420}
                allowDeselect={false}
                error={fieldState.error?.message}
                id="field-representative_role"
              />
            )}
          />
        </Stack>
      </SectionCard>

      {prefill.isPending && (
        <Paper withBorder radius="lg" p="lg" aria-busy="true">
          <Text size="sm" mb="sm" role="status">
            Получаем сведения из госреестров...
          </Text>
          <Stack gap="xs">
            <Skeleton height={14} width="70%" />
            <Skeleton height={14} width="50%" />
            <Skeleton height={14} width="60%" />
          </Stack>
        </Paper>
      )}

      {!prefill.isPending && unavailable && (
        <Alert color="gray" icon={<IconCloudOff aria-hidden />} radius="lg">
          Не удалось получить сведения, попробуем при обработке заявки. Можно продолжать.
        </Alert>
      )}

      {app.early_warnings.map((w) => (
        <Alert key={w.reason_code} color="yellow" icon={<IconAlertTriangle aria-hidden />} radius="lg" title="Обратите внимание">
          <Text size="sm">{w.text}</Text>
          {w.next_step && (
            <Text size="sm" mt={4} fw={600}>
              {w.next_step}
            </Text>
          )}
          <Text size="xs" c="dimmed" mt={6}>
            Отправить заявку все равно можно, окончательное решение примет банк.
          </Text>
        </Alert>
      ))}

      {!prefill.isPending && company && app.inn_check_status === 'FOUND' && <CompanyBlock company={company} />}
    </Stack>
  );
}

export function CompanyBlock({ company }: { company: CompanyInfo }) {
  const isLlc = company.applicant_type === 'LEGAL_ENTITY';
  return (
    <SectionCard
      title={
        <Group gap={6} component="span">
          <IconBuildingBank size={20} aria-hidden /> Сведения из госреестров <Hint term="Сведения из госреестров" hint={GLOSSARY.registry} />
        </Group>
      }
      actions={
        <Badge variant="light" color="gray">
          {company.source ?? 'госреестр'}, {formatDateTime(company.fetched_at)}
        </Badge>
      }
    >
      <Text fw={700} size="lg" mb="sm">
        {company.company_full_name ?? company.company_short_name}
      </Text>
      <KeyValue
        cols={3}
        items={[
          { label: 'Тип', value: APPLICANT_TYPES[company.applicant_type ?? ''] ?? company.applicant_type },
          { label: <Term k="ogrn">{isLlc ? 'ОГРН' : 'ОГРНИП'}</Term>, value: <span className="num">{company.ogrn}</span> },
          { label: 'Дата регистрации', value: formatDate(company.registration_date) },
          { label: 'Статус', value: COMPANY_STATUSES[company.company_status ?? ''] ?? company.company_status },
          { label: <Term k="okved">Вид деятельности</Term>, value: `${company.okved_main_code ?? ''} ${company.okved_main_name ?? ''}`.trim() },
          { label: isLlc ? 'Руководитель' : 'Предприниматель', value: company.director_full_name },
          {
            label: 'Учредители',
            value: (company.founders ?? []).map((f) => `${f.name}${f.share_percent ? ` (${Number(f.share_percent)}%)` : ''}`).join(', '),
            hidden: !isLlc || !company.founders?.length,
          },
          { label: <Term k="taxRegime">Налоги</Term>, value: TAX_REGIMES[company.tax_regime ?? ''] ?? company.tax_regime, hidden: !company.tax_regime },
          { label: 'Сотрудников', value: company.employees_count, hidden: company.employees_count == null },
          { label: 'Категория', value: SME_CATEGORIES[company.sme_category ?? ''] ?? company.sme_category, hidden: !company.sme_category },
          { label: 'Регион', value: company.legal_address_region, hidden: !company.legal_address_region },
        ]}
      />
      <Title order={3} size="h6" mt="md" c="dimmed" fw={400}>
        Вводить эти данные не нужно: банк получил их сам.
      </Title>
    </SectionCard>
  );
}
