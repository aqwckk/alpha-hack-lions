import { Alert, Button, Checkbox, Group, NumberInput, Select, SimpleGrid, Stack, Text, Textarea } from '@mantine/core';
import { useDebouncedValue } from '@mantine/hooks';
import { IconAlertTriangle, IconCalculator } from '@tabler/icons-react';
import { useQuery } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { Controller, useWatch, type UseFormReturn } from 'react-hook-form';
import { Link } from 'react-router-dom';
import type { DraftField, DraftValues } from './formModel';
import { api } from '@/shared/api/endpoints';
import { useDictionaries, useProduct } from '@/shared/api/queries';
import type { ClientApplication, CompanyInfo } from '@/shared/api/types';
import { formatMoney, formatRate } from '@/shared/lib/format';
import { GLOSSARY } from '@/shared/lib/glossary';
import { SectionCard } from '@/shared/ui/components';
import { Hint } from '@/shared/ui/Term';

function Label({ children, term, hint }: { children: ReactNode; term?: string; hint?: string }) {
  return (
    <Group gap={4} component="span" wrap="nowrap" style={{ display: 'inline-flex' }}>
      {children}
      {term && hint && <Hint term={term} hint={hint} />}
    </Group>
  );
}

const toNumber = (v: string | number): number | '' => (typeof v === 'number' ? v : v === '' ? '' : Number(String(v).replace(/[^\d]/g, '')) || '');

export function StepTerms({ app, form }: { app: ClientApplication; form: UseFormReturn<DraftValues> }) {
  const product = useProduct(app.product_code);
  const dictionaries = useDictionaries();
  const company = app.company as CompanyInfo | null;
  const values = useWatch({ control: form.control });
  const [debounced] = useDebouncedValue({ amount: values.amount, term: values.term_months }, 300);
  const serverWarning = (field: DraftField) => app.warnings.find((w) => w.field === field)?.message ?? undefined;

  const amountOk =
    typeof debounced.amount === 'number' && product && debounced.amount >= Number(product.amount_min) && debounced.amount <= Number(product.amount_max);
  const termOk = typeof debounced.term === 'number' && product && debounced.term >= product.term_min_months && debounced.term <= product.term_max_months;
  const calc = useQuery({
    queryKey: ['catalog', 'calculate', app.product_code, debounced.amount, debounced.term],
    queryFn: () => api.calculate({ product_code: app.product_code, amount: String(debounced.amount), term_months: Number(debounced.term) }),
    enabled: Boolean(amountOk && termOk),
    placeholderData: (prev) => prev,
  });

  const needsGuarantee = Boolean(product && app.applicant_type && product.requires_owner_guarantee_for.includes(app.applicant_type));
  const needsCollateral = Boolean(product?.requires_collateral);
  const revenue = typeof values.monthly_revenue_declared === 'number' ? values.monthly_revenue_declared : null;
  const payments = typeof values.existing_monthly_payments_declared === 'number' ? values.existing_monthly_payments_declared : null;
  const paymentsAboveRevenue = revenue !== null && payments !== null && payments > revenue;

  const money = (name: DraftField, label: string, opts: { description?: string; required?: boolean; hint?: { term: string; text: string } } = {}) => (
    <Controller
      control={form.control}
      name={name}
      render={({ field, fieldState }) => (
        <NumberInput
          id={`field-${name}`}
          label={label}
          description={opts.description}
          value={field.value as number | ''}
          onChange={(v) => field.onChange(toNumber(v))}
          onBlur={field.onBlur}
          ref={field.ref}
          thousandSeparator=" "
          suffix=" ₽"
          allowDecimal={false}
          allowNegative={false}
          hideControls
          withAsterisk={opts.required}
          rightSection={opts.hint ? <Hint term={opts.hint.term} hint={opts.hint.text} /> : undefined}
          rightSectionPointerEvents="all"
          error={fieldState.error?.message ?? serverWarning(name)}
        />
      )}
    />
  );

  return (
    <Stack gap="lg">
      <SectionCard
        title="Кредит"
        actions={
          <Button component={Link} to="/client/wizard" variant="subtle" size="compact-sm">
            Выбрать другой продукт
          </Button>
        }
      >
        <Stack gap="md">
          <div>
            <Text fw={700}>{app.product_name}</Text>
            {product && (
              <Text size="sm" c="dimmed">
                {product.description}. Сумма от {formatMoney(product.amount_min)} до {formatMoney(product.amount_max)}, срок от {product.term_min_months} до{' '}
                {product.term_max_months} месяцев.
              </Text>
            )}
          </div>
          <Controller
            control={form.control}
            name="purpose"
            render={({ field, fieldState }) => (
              <Select
                id="field-purpose"
                label="На что нужны деньги"
                data={(dictionaries.data?.purposes ?? [])
                  .filter((p) => !product || product.allowed_purposes.includes(p.code))
                  .map((p) => ({ value: p.code, label: p.title }))}
                value={field.value || null}
                onChange={(v) => field.onChange(v ?? '')}
                onBlur={field.onBlur}
                allowDeselect={false}
                maw={460}
                error={fieldState.error?.message ?? serverWarning('purpose')}
              />
            )}
          />
          <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="md">
            <Controller
              control={form.control}
              name="amount"
              render={({ field, fieldState }) => (
                <NumberInput
                  id="field-amount"
                  label="Сумма"
                  value={field.value}
                  onChange={(v) => field.onChange(toNumber(v))}
                  onBlur={field.onBlur}
                  thousandSeparator=" "
                  suffix=" ₽"
                  allowDecimal={false}
                  allowNegative={false}
                  step={product ? Number(product.amount_step) : 10000}
                  error={fieldState.error?.message ?? serverWarning('amount') ?? (product && field.value !== '' && !amountOkNow(field.value, product.amount_min, product.amount_max) ? `Допустимо от ${formatMoney(product.amount_min)} до ${formatMoney(product.amount_max)}` : undefined)}
                />
              )}
            />
            <Controller
              control={form.control}
              name="term_months"
              render={({ field, fieldState }) => (
                <NumberInput
                  id="field-term_months"
                  label="Срок, месяцев"
                  rightSection={<Hint term="Срок" hint={GLOSSARY.term} />}
                  rightSectionPointerEvents="all"
                  hideControls
                  value={field.value}
                  onChange={(v) => field.onChange(toNumber(v))}
                  onBlur={field.onBlur}
                  allowDecimal={false}
                  allowNegative={false}
                  min={product?.term_min_months}
                  max={product?.term_max_months}
                  error={fieldState.error?.message ?? serverWarning('term_months')}
                />
              )}
            />
          </SimpleGrid>
          <Alert color="gray" variant="light" icon={<IconCalculator aria-hidden />} radius="md" aria-live="polite">
            {calc.data ? (
              <Text size="sm">
                Платеж около <b className="num">{formatMoney(calc.data.monthly_payment)}</b> в месяц при ставке от {formatRate(calc.data.rate_percent)}, переплата за
                весь срок около {formatMoney(calc.data.overpayment)}. Точные условия банк рассчитает после проверки.
              </Text>
            ) : (
              <Text size="sm">Укажите сумму и срок в границах продукта, и мы посчитаем платеж.</Text>
            )}
          </Alert>
        </Stack>
      </SectionCard>

      <SectionCard title="Финансы бизнеса">
        <Stack gap="md">
          <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="md">
            {money('monthly_revenue_declared', 'Средняя выручка в месяц за последние 12 месяцев', { required: true, hint: { term: 'Выручка в месяц', text: GLOSSARY.revenue } })}
            {money('existing_monthly_payments_declared', 'Сколько бизнес сейчас платит по кредитам и займам в месяц', {
              required: true,
              hint: { term: 'Текущие платежи по кредитам', text: GLOSSARY.existingPayments },
              description: 'Если кредитов нет, укажите 0',
            })}
          </SimpleGrid>
          {paymentsAboveRevenue && (
            <Alert color="yellow" icon={<IconAlertTriangle aria-hidden />} radius="md">
              Проверьте сумму: платежи больше выручки
            </Alert>
          )}
          {needsGuarantee && (
            <Controller
              control={form.control}
              name="owner_guarantee_agreed"
              render={({ field, fieldState }) => (
                <Group gap={4} align="flex-start" wrap="nowrap">
                <Checkbox
                  id="field-owner_guarantee_agreed"
                  checked={field.value}
                  onChange={(e) => field.onChange(e.currentTarget.checked)}
                  label="Собственник согласен стать поручителем по кредиту"
                  description={
                    company?.guarantor_full_name || company?.director_full_name
                      ? `Поручитель по данным реестра: ${company.guarantor_full_name ?? company.director_full_name ?? ''}`
                      : 'Для компаний этот кредит выдается с поручительством собственника'
                  }
                  error={fieldState.error?.message ?? serverWarning('owner_guarantee_agreed')}
                />
                  <Hint term="Поручительство собственника" hint={GLOSSARY.guarantee} />
                </Group>
              )}
            />
          )}
        </Stack>
      </SectionCard>

      {needsCollateral && (
        <SectionCard title={<Label term="Залог" hint={GLOSSARY.collateral}>Залог и проект</Label>}>
          <Stack gap="md">
            <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="md">
              <Controller
                control={form.control}
                name="collateral_type"
                render={({ field, fieldState }) => (
                  <Select
                    id="field-collateral_type"
                    label="Что будет в залоге"
                    withAsterisk
                    data={(dictionaries.data?.collateral_types ?? []).map((c) => ({ value: c.code, label: c.title }))}
                    value={field.value || null}
                    onChange={(v) => field.onChange(v ?? '')}
                    error={fieldState.error?.message ?? serverWarning('collateral_type')}
                  />
                )}
              />
              <Controller
                control={form.control}
                name="collateral_owner"
                render={({ field, fieldState }) => (
                  <Select
                    id="field-collateral_owner"
                    label="Кому принадлежит имущество"
                    withAsterisk
                    data={(dictionaries.data?.collateral_owners ?? []).map((c) => ({ value: c.code, label: c.title }))}
                    value={field.value || null}
                    onChange={(v) => field.onChange(v ?? '')}
                    error={fieldState.error?.message ?? serverWarning('collateral_owner')}
                  />
                )}
              />
            </SimpleGrid>
            <Textarea
              id="field-collateral_description"
              label="Описание имущества"
              withAsterisk
              autosize
              minRows={2}
              placeholder="Например: линия упаковки, приобретаемая по договору поставки"
              {...form.register('collateral_description')}
              error={form.formState.errors.collateral_description?.message ?? serverWarning('collateral_description')}
            />
            <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="md">
              {money('collateral_value', 'Примерная стоимость имущества', { required: true })}
              {money('own_contribution_amount', 'Собственные средства в проекте', { description: 'Необязательно' })}
            </SimpleGrid>
            <Textarea
              id="field-investment_project_description"
              label="О проекте"
              description="Что покупаете, зачем и когда вложения окупятся"
              withAsterisk
              autosize
              minRows={3}
              {...form.register('investment_project_description')}
              error={form.formState.errors.investment_project_description?.message ?? serverWarning('investment_project_description')}
            />
          </Stack>
        </SectionCard>
      )}

      <SectionCard title="Что еще важно знать банку">
        <Textarea
          id="field-client_comment"
          label="Комментарий"
          description="Необязательно. Например, сезонность продаж или крупный новый контракт"
          autosize
          minRows={2}
          maxLength={1000}
          {...form.register('client_comment', { maxLength: { value: 1000, message: 'Не более 1000 символов' } })}
          error={form.formState.errors.client_comment?.message}
        />
      </SectionCard>
    </Stack>
  );
}

function amountOkNow(value: number | '', min: string, max: string): boolean {
  return typeof value === 'number' && value >= Number(min) && value <= Number(max);
}
