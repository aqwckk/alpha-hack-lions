import { Alert, Button, Group, Stack, Stepper, Text } from '@mantine/core';
import { IconAlertTriangle, IconArrowLeft, IconArrowRight, IconCloudCheck, IconCloudUpload } from '@tabler/icons-react';
import { useEffect } from 'react';
import { useForm } from 'react-hook-form';
import { Link, Navigate, useNavigate, useParams, useBlocker } from 'react-router-dom';
import { STEPS, isStep, resumeStep, valuesFromServer, type DraftValues } from './formModel';
import { StepCompany } from './StepCompany';
import { StepDocuments } from './StepDocuments';
import { StepReview } from './StepReview';
import { StepTerms } from './StepTerms';
import { useDraftAutosave, type SaveStatus } from './useDraftAutosave';
import { useInnConfirmation } from './useInnConfirmation';
import { DemoHint } from '@/features/demo/DemoHint';
import { useClientApplication } from '@/shared/api/queries';
import type { ClientApplication } from '@/shared/api/types';
import { formatTime } from '@/shared/lib/format';
import type { FormStep } from '@/shared/lib/labels';
import { ErrorState, PageHeader, PageSkeleton } from '@/shared/ui/components';

export function ApplicationFormPage() {
  const { id = '', step } = useParams();
  const query = useClientApplication(id);
  if (query.isPending) return <PageSkeleton lines={4} />;
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} notFoundText="Заявка не найдена или у вас нет к ней доступа" />;
  const app = query.data;
  if (app.client_status !== 'FILLING') return <Navigate to={`/client/applications/${app.id}`} replace />;
  if (!isStep(step)) return <Navigate to={`/client/applications/${app.id}/edit/${resumeStep(app)}`} replace />;
  return <DraftForm key={app.id} app={app} step={step} />;
}

function SaveIndicator({ status }: { status: SaveStatus }) {
  switch (status.state) {
    case 'saving':
      return (
        <Group gap={6} role="status">
          <IconCloudUpload size={16} aria-hidden />
          <Text size="sm" c="dimmed">
            Сохраняем...
          </Text>
        </Group>
      );
    case 'saved':
      return (
        <Group gap={6} role="status">
          <IconCloudCheck size={16} color="var(--mantine-color-green-7)" aria-hidden />
          <Text size="sm" c="dimmed">
            Сохранено в {formatTime(status.at.toISOString())}
          </Text>
        </Group>
      );
    case 'retrying':
      return (
        <Group gap={6} role="status">
          <IconAlertTriangle size={16} color="var(--mantine-color-orange-7)" aria-hidden />
          <Text size="sm" c="orange.8">
            Не удалось сохранить, повторим автоматически
          </Text>
        </Group>
      );
    case 'error':
      return (
        <Group gap={6} role="alert">
          <IconAlertTriangle size={16} color="var(--mantine-color-red-7)" aria-hidden />
          <Text size="sm" c="red.8">
            {status.message}
          </Text>
        </Group>
      );
    default:
      return (
        <Text size="sm" c="dimmed">
          Все, что вы вводите, сохраняется автоматически
        </Text>
      );
  }
}

function DraftForm({ app, step }: { app: ClientApplication; step: FormStep }) {
  const navigate = useNavigate();
  const initial: DraftValues = valuesFromServer(app.form as Record<string, unknown>);
  const form = useForm<DraftValues>({ defaultValues: initial, mode: 'onTouched' });
  const { status, flush, hasPending } = useDraftAutosave(app.id, form, initial);
  const inn = useInnConfirmation(app);
  const blocker = useBlocker(() => hasPending() || inn.dirty);
  useEffect(() => {
    if (blocker.state !== 'blocked') return;
    let active = true;
    void flush().then((ok) => {
      if (!active) return;
      if (ok && (!inn.dirty || inn.ready)) blocker.proceed();
      else blocker.reset();
    });
    return () => { active = false; };
  }, [blocker, flush, inn.dirty, inn.ready]);
  const index = STEPS.findIndex((s) => s.key === step);

  const go = async (target: FormStep) => {
    if (target !== 'company' && !inn.isReady()) return;
    if (!(await flush())) return;
    if (target !== 'company' && !inn.isReady()) return;
    navigate(`/client/applications/${app.id}/edit/${target}`);
    window.scrollTo({ top: 0 });
  };

  const prev = STEPS[index - 1];
  const next = STEPS[index + 1];

  return (
    <>
      <PageHeader
        title={`Заявка ${app.application_number}`}
        subtitle={`${app.product_name}. Шаг ${index + 1} из ${STEPS.length}: ${STEPS[index]?.title ?? ''}`}
        back={{ to: '/client/applications', label: 'Мои заявки' }}
        focus={false}
      />
      <Stack gap="lg">
        <Group justify="space-between" wrap="wrap" gap="xs">
          <Group gap="xs" w={{ base: '100%', sm: 'auto' }} mih={44}>
            <SaveIndicator status={status} />
            {status.state === 'error' && <Button variant="subtle" size="compact-sm" onClick={() => void flush()}>Повторить сохранение</Button>}
          </Group>
          <Button component={Link} to={`/client/applications/${app.id}`} variant="subtle" size="compact-sm">
            Статус и отмена заявки
          </Button>
        </Group>
        <Stepper
          active={index}
          onStepClick={(i) => {
            const target = STEPS[i];
            if (target) void go(target.key);
          }}
          allowNextStepsSelect
          size="sm"
          iconSize={30}
          aria-label="Шаги заявки"
        >
          {STEPS.map((s) => (
            <Stepper.Step key={s.key} label={s.short} aria-current={s.key === step ? 'step' : undefined} />
          ))}
        </Stepper>
        <DemoHint />
        {app.client_status_text.notes.length > 0 && (
          <Alert color="blue" variant="light" radius="lg">
            {app.client_status_text.notes.join(' ')}
          </Alert>
        )}
        <form
          onSubmit={(e) => e.preventDefault()}
          onBlur={() => void flush()}
          noValidate
          aria-label={STEPS[index]?.title}
        >
          {step === 'company' && <StepCompany app={app} form={form} inn={inn} />}
          {step === 'terms' && <StepTerms app={app} form={form} />}
          {step === 'documents' && <StepDocuments app={app} />}
          {step === 'review' && <StepReview app={app} form={form} flush={flush} goTo={go} innReady={inn.ready} confirmInn={inn.isReady} />}
        </form>
        {!inn.ready && <Alert color="orange" radius="lg">Укажите корректный ИНН на шаге «Компания» и дождитесь проверки. Если госреестр недоступен, после сохранения ИНН можно продолжить.</Alert>}
        <Group justify="space-between">
          {prev ? (
            <Button variant="default" leftSection={<IconArrowLeft size={16} aria-hidden />} onClick={() => void go(prev.key)}>
              Назад
            </Button>
          ) : (
            <span />
          )}
          {next && (
            <Button size="md" rightSection={<IconArrowRight size={16} aria-hidden />} disabled={!inn.ready} onClick={() => void go(next.key)}>
              Далее
            </Button>
          )}
        </Group>
      </Stack>
    </>
  );
}
