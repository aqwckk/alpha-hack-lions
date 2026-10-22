import { zodResolver } from '@hookform/resolvers/zod';
import { Button, Group, NumberInput, Paper, SegmentedControl, Slider, Stack, Text, TextInput, Title } from '@mantine/core';
import { IconArrowRight } from '@tabler/icons-react';
import { useEffect, useState } from 'react';
import { Controller, useForm } from 'react-hook-form';
import { useLocation, useNavigate } from 'react-router-dom';
import { z } from 'zod';
import { DemoHint } from '@/features/demo/DemoHint';
import { api } from '@/shared/api/endpoints';
import { useDictionaries } from '@/shared/api/queries';
import { formatMoney, formatTerm } from '@/shared/lib/format';
import { newId } from '@/shared/lib/ids';
import { innError } from '@/shared/lib/inn';
import { ErrorState, PageHeader, PageSkeleton } from '@/shared/ui/components';
import { Hint } from '@/shared/ui/Term';
import { GLOSSARY } from '@/shared/lib/glossary';

export const AMOUNT_MIN = 300_000;
export const AMOUNT_MAX = 100_000_000;
export const TERM_MIN = 3;
export const TERM_MAX = 84;

const schema = z.object({
  purpose: z.string().min(1, 'Выберите, на что нужны деньги'),
  amount: z
    .number({ error: 'Укажите сумму' })
    .min(AMOUNT_MIN, `Минимальная сумма ${formatMoney(AMOUNT_MIN)}`)
    .max(AMOUNT_MAX, `Максимальная сумма ${formatMoney(AMOUNT_MAX)}`),
  term_months: z.number({ error: 'Укажите срок' }).int().min(TERM_MIN, `От ${TERM_MIN} месяцев`).max(TERM_MAX, `До ${TERM_MAX} месяцев`),
  applicant_type: z.enum(['ANY', 'INDIVIDUAL_ENTREPRENEUR', 'LEGAL_ENTITY']),
  inn: z.string().trim().refine((v) => v === '' || innError(v) === null, { message: 'Проверьте ИНН: 10 цифр у компании, 12 у ИП' }),
});

export type WizardRequest = z.infer<typeof schema>;

export interface WizardState {
  request: WizardRequest;
  wizardId: string;
}

const DEFAULTS: WizardRequest = { purpose: '', amount: 1_200_000, term_months: 24, applicant_type: 'ANY', inn: '' };

// Log scale: the slider is equally comfortable for 500 thousand and for 50 million.
const RATIO = Math.log(AMOUNT_MAX / AMOUNT_MIN);
function sliderToAmount(v: number): number {
  const raw = AMOUNT_MIN * Math.exp((v / 1000) * RATIO);
  const step = raw < 3_000_000 ? 50_000 : raw < 20_000_000 ? 100_000 : 1_000_000;
  return Math.min(AMOUNT_MAX, Math.max(AMOUNT_MIN, Math.round(raw / step) * step));
}
function amountToSlider(amount: number): number {
  const a = Math.min(AMOUNT_MAX, Math.max(AMOUNT_MIN, amount || AMOUNT_MIN));
  return Math.round((Math.log(a / AMOUNT_MIN) / RATIO) * 1000);
}

const tracked = new Set<string>();

export function WizardPage() {
  const dictionaries = useDictionaries();
  const navigate = useNavigate();
  const location = useLocation();
  const prev = location.state as WizardState | null;
  const form = useForm<WizardRequest>({ resolver: zodResolver(schema), defaultValues: prev?.request ?? DEFAULTS, mode: 'onTouched' });
  const [sessionId] = useState(() => prev?.wizardId ?? newId());

  useEffect(() => {
    if (tracked.has(sessionId)) return;
    tracked.add(sessionId);
    void api.trackWizard({ event_type: 'PRODUCT_WIZARD_STARTED', wizard_session_id: sessionId }).catch(() => undefined);
  }, [sessionId]);

  const onSubmit = form.handleSubmit((request) => {
    const state: WizardState = { request, wizardId: sessionId };
    navigate('/client/wizard/results', { state });
  });

  const purpose = form.watch('purpose');
  const errors = form.formState.errors;

  return (
    <>
      <PageHeader title="Подбор кредита" subtitle="Расскажите о задаче, а мы подберем подходящий кредит. Знать названия продуктов не нужно." />
      <Stack gap="lg">
        <DemoHint />
        {dictionaries.isPending && <PageSkeleton lines={2} />}
        {dictionaries.isError && <ErrorState error={dictionaries.error} onRetry={() => void dictionaries.refetch()} />}
        {dictionaries.data && (
          <form onSubmit={onSubmit} noValidate>
            <Stack gap="lg">
              <Paper withBorder radius="lg" p={{ base: 'md', sm: 'lg' }}>
                <fieldset style={{ border: 0, padding: 0, margin: 0 }} aria-describedby={errors.purpose ? 'purpose-error' : undefined}>
                  <legend>
                    <Title order={2} size="h4" mb="sm">
                      1. На что нужны деньги?
                    </Title>
                  </legend>
                  <div className="choice-grid">
                    {dictionaries.data.purposes.map((p) => (
                      <label key={p.code} className="choice-card" data-checked={purpose === p.code}>
                        <input type="radio" value={p.code} {...form.register('purpose')} />
                        <span>
                          <Text fw={600} size="sm">
                            {p.title}
                          </Text>
                          <Text size="xs" c="dimmed">
                            {p.hint}
                          </Text>
                        </span>
                      </label>
                    ))}
                  </div>
                  {errors.purpose && (
                    <Text id="purpose-error" c="red.8" size="sm" mt="xs" role="alert">
                      {errors.purpose.message}
                    </Text>
                  )}
                </fieldset>
              </Paper>

              <Paper withBorder radius="lg" p={{ base: 'md', sm: 'lg' }}>
                <Stack gap="lg">
                  <Controller
                    control={form.control}
                    name="amount"
                    render={({ field, fieldState }) => (
                      <Stack gap="xs">
                        <Title order={2} size="h4">
                          2. Сколько нужно?
                        </Title>
                        <NumberInput
                          label="Сумма"
                          description="От 300 000 до 100 000 000 ₽"
                          value={field.value}
                          onChange={(v) => field.onChange(typeof v === 'number' ? v : Number(String(v).replace(/\D/g, '')) || 0)}
                          onBlur={field.onBlur}
                          thousandSeparator=" "
                          suffix=" ₽"
                          allowDecimal={false}
                          allowNegative={false}
                          min={0}
                          hideControls
                          size="md"
                          maw={360}
                          error={fieldState.error?.message}
                        />
                        <div className="slider-wrap">
                        <Slider
                          aria-label="Сумма, ползунок"
                          value={amountToSlider(field.value)}
                          onChange={(v) => field.onChange(sliderToAmount(v))}
                          min={0}
                          max={1000}
                          step={1}
                          label={(v) => formatMoney(sliderToAmount(v))}
                          marks={[
                            { value: amountToSlider(1_000_000), label: '1 млн' },
                            { value: amountToSlider(10_000_000), label: '10 млн' },
                            { value: amountToSlider(100_000_000), label: '100 млн' },
                          ]}
                          mb="md"
                        />
                        </div>
                      </Stack>
                    )}
                  />
                  <Controller
                    control={form.control}
                    name="term_months"
                    render={({ field, fieldState }) => (
                      <Stack gap="xs">
                        <Title order={2} size="h4">
                          3. На какой срок?
                        </Title>
                        <Group gap={4} align="flex-end">
                          <NumberInput
                            label="Срок, месяцев"
                            description="Чем дольше срок, тем меньше платеж в месяц, но больше переплата"
                            value={field.value}
                            onChange={(v) => field.onChange(typeof v === 'number' ? v : Number(v) || 0)}
                            onBlur={field.onBlur}
                            suffix=" мес."
                            allowDecimal={false}
                            allowNegative={false}
                            min={TERM_MIN}
                            max={TERM_MAX}
                            size="md"
                            maw={360}
                            error={fieldState.error?.message}
                          />
                          <Hint term="Срок" hint={GLOSSARY.term} />
                        </Group>
                        <div className="slider-wrap">
                        <Slider
                          aria-label="Срок в месяцах, ползунок"
                          value={field.value || TERM_MIN}
                          onChange={field.onChange}
                          min={TERM_MIN}
                          max={TERM_MAX}
                          step={1}
                          label={(v) => formatTerm(v)}
                          marks={[12, 24, 36, 60, 84].map((m) => ({ value: m, label: String(m) }))}
                          mb="md"
                        />
                        </div>
                      </Stack>
                    )}
                  />
                </Stack>
              </Paper>

              <Paper withBorder radius="lg" p={{ base: 'md', sm: 'lg' }}>
                <Stack gap="md">
                  <Title order={2} size="h4">
                    4. Кто вы? <Text span c="dimmed" size="sm" fw={400}>(необязательно)</Text>
                  </Title>
                  <Controller
                    control={form.control}
                    name="applicant_type"
                    render={({ field }) => (
                      <SegmentedControl
                        value={field.value}
                        onChange={(v) => field.onChange(v)}
                        data={[
                          { value: 'ANY', label: 'Пока не важно' },
                          { value: 'INDIVIDUAL_ENTREPRENEUR', label: 'ИП' },
                          { value: 'LEGAL_ENTITY', label: 'ООО' },
                        ]}
                        aria-label="Тип бизнеса"
                        maw={420}
                      />
                    )}
                  />
                  <TextInput
                    label="ИНН"
                    description="Чтобы сразу проверить, какие продукты вам доступны"
                    inputMode="numeric"
                    maxLength={12}
                    autoComplete="off"
                    maw={360}
                    {...form.register('inn', { setValueAs: (v: string) => v.replace(/\D/g, '') })}
                    error={errors.inn?.message}
                  />
                </Stack>
              </Paper>

              <Group>
                <Button type="submit" size="lg" rightSection={<IconArrowRight size={18} aria-hidden />}>
                  Показать варианты
                </Button>
              </Group>
            </Stack>
          </form>
        )}
      </Stack>
    </>
  );
}
