import { Alert, Button, Checkbox, Group, Paper, PinInput, Stack, Text, Title } from '@mantine/core';
import { IconInfoCircle, IconKey, IconLoader2, IconSignature } from '@tabler/icons-react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { Navigate, useNavigate, useParams } from 'react-router-dom';
import { SigningDocs } from './SigningDocs';
import { useClientCommand } from '@/shared/api/commands';
import { api } from '@/shared/api/endpoints';
import { isApiError } from '@/shared/api/errors';
import { qk, useClientApplication } from '@/shared/api/queries';
import type { ClientApplication, SigningCodeResponse } from '@/shared/api/types';
import { formatMoney, formatRate, formatTerm } from '@/shared/lib/format';
import { GLOSSARY } from '@/shared/lib/glossary';
import { newId } from '@/shared/lib/ids';
import { ErrorState, KeyValue, PageHeader, PageSkeleton, SectionCard } from '@/shared/ui/components';
import { Hint } from '@/shared/ui/Term';
import { toast } from '@/shared/ui/toast';

export function SigningPage() {
  const { id = '' } = useParams();
  const query = useClientApplication(id);
  if (query.isPending) return <PageSkeleton lines={3} />;
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} notFoundText="Заявка не найдена или у вас нет к ней доступа" />;
  const app = query.data;
  if (app.client_status !== 'DOCUMENTS') return <Navigate to={`/client/applications/${app.id}`} replace />;
  return <Signing app={app} />;
}

function useSecondsLeft(expiresAt: string | null | undefined): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  if (!expiresAt) return 0;
  return Math.max(0, Math.round((new Date(expiresAt).getTime() - now) / 1000));
}

function Signing({ app }: { app: ClientApplication }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const signing = app.signing;
  const ready = Boolean(signing) && (app.available_actions.includes('REQUEST_SIGNING_CODE') || app.available_actions.includes('SIGN'));
  const [read, setRead] = useState(false);
  const [issued, setIssued] = useState<SigningCodeResponse | null>(null);
  const [code, setCode] = useState('');
  const [codeError, setCodeError] = useState<string | null>(null);
  const [requestKey, setRequestKey] = useState<string | null>(null);
  const expiresAt = issued?.expires_at ?? signing?.active_code?.expires_at ?? null;
  const secondsLeft = useSecondsLeft(expiresAt);
  const attemptsLeft = signing?.active_code?.attempts_left ?? issued?.attempts_left;
  const hasActiveCode = Boolean(expiresAt) && secondsLeft > 0;

  const requestCode = useMutation({
    mutationFn: (key: string) => api.requestSigningCode(app.id, key),
    retry: (count, error) => isApiError(error) && error.kind === 'network' && count < 2,
    onSuccess: (res) => {
      setIssued(res);
      setCode('');
      setCodeError(null);
      setRequestKey(null);
      void queryClient.invalidateQueries({ queryKey: qk.application(app.id) });
      void queryClient.invalidateQueries({ queryKey: qk.notifications });
    },
    onError: (e) => {
      setRequestKey(null);
      toast.error(e, 'Не удалось получить код');
    },
  });

  const sign = useClientCommand<{ code: string }>(app.id, ({ version, key, code: value }) => api.sign(app.id, version, value, key), {
    success: 'Документы подписаны. Банк перечисляет деньги.',
    onSuccess: (res) => navigate(`/client/applications/${res.id}`),
    onError: (e) => {
      if (e.code === 'SIGNING_CODE_INVALID') {
        const left = typeof e.details.attempts_left === 'number' ? e.details.attempts_left : null;
        setCodeError(left !== null ? `Неверный код, осталось попыток: ${left}` : e.message);
      } else if (e.code === 'SIGNING_ATTEMPTS_EXCEEDED') {
        setCodeError('Неверный код. Попытки закончились, получите новый код');
        setIssued(null);
      } else if (e.code === 'SIGNING_CODE_EXPIRED') {
        setCodeError('Код больше не действует, получите новый');
        setIssued(null);
      } else {
        return false;
      }
      setCode('');
      void queryClient.invalidateQueries({ queryKey: qk.application(app.id) });
      return true;
    },
  });

  const onRequest = () => {
    if (requestCode.isPending) return;
    const key = requestKey ?? newId();
    setRequestKey(key);
    requestCode.mutate(key);
  };

  const terms = app.final_terms;
  const minutes = Math.floor(secondsLeft / 60);
  const seconds = String(secondsLeft % 60).padStart(2, '0');

  return (
    <>
      <PageHeader title="Подписание документов" subtitle={`Заявка ${app.application_number}, ${app.product_name}`} back={{ to: `/client/applications/${app.id}`, label: 'К статусу заявки' }} />
      <Stack gap="lg">
        {terms && (
          <SectionCard title="Выбранные условия">
            <KeyValue
              cols={3}
              items={[
                { label: 'Сумма', value: formatMoney(terms.amount) },
                { label: 'Срок', value: formatTerm(terms.term_months) },
                { label: 'Ставка', value: formatRate(terms.rate_percent) },
                { label: 'Платеж в месяц', value: formatMoney(terms.monthly_payment) },
              ]}
            />
            {app.client_status_text.deadline_text && (
              <Text size="sm" mt="sm" fw={600}>
                {app.client_status_text.deadline_text}
              </Text>
            )}
          </SectionCard>
        )}

        {!ready || !signing ? (
          <Paper withBorder radius="lg" p="xl" role="status">
            <Group gap="sm">
              <IconLoader2 className="spin" aria-hidden />
              <Text fw={600}>Готовим документы, это займет меньше минуты</Text>
            </Group>
            <Text size="sm" c="dimmed" mt="xs">
              Страница обновится сама, когда документы будут готовы.
            </Text>
          </Paper>
        ) : (
          <>
            <SectionCard title="1. Прочитайте документы">
              <Stack gap="md">
                <SigningDocs appId={app.id} signing={signing} />
                <Checkbox checked={read} onChange={(e) => setRead(e.currentTarget.checked)} label="Я ознакомился с документами" />
              </Stack>
            </SectionCard>

            <SectionCard
              title={
                <Group gap={4} component="span">
                  2. Подпишите кодом <Hint term="Код подтверждения" hint={GLOSSARY.signingCode} />
                </Group>
              }
            >
              <Stack gap="md">
                <Alert color="gray" variant="light" icon={<IconInfoCircle aria-hidden />} radius="md">
                  {signing.note}
                </Alert>
                <Group>
                  <Button leftSection={<IconKey size={16} aria-hidden />} onClick={onRequest} loading={requestCode.isPending} disabled={!read || !app.available_actions.includes('REQUEST_SIGNING_CODE')} variant={hasActiveCode ? 'light' : 'filled'}>
                    {hasActiveCode ? 'Получить новый код' : 'Получить код'}
                  </Button>
                  {!read && (
                    <Text size="sm" c="dimmed">
                      Сначала отметьте, что ознакомились с документами
                    </Text>
                  )}
                </Group>

                {issued?.code && hasActiveCode && (
                  <Paper withBorder radius="md" p="md" bg="yellow.0" role="status">
                    <Text size="sm">Ваш код подтверждения (в прототипе показывается здесь вместо SMS):</Text>
                    <Group justify="space-between" wrap="wrap">
                      <Text className="code-box" aria-label={`Код ${issued.code.split('').join(' ')}`}>
                        {issued.code}
                      </Text>
                      <Button variant="subtle" size="compact-sm" onClick={() => setCode(issued.code ?? '')}>
                        Подставить код
                      </Button>
                    </Group>
                    <Text size="xs" c="dimmed">
                      Код также есть в уведомлениях. Никому его не сообщайте.
                    </Text>
                  </Paper>
                )}
                {!issued?.code && hasActiveCode && (
                  <Text size="sm">Код отправлен в уведомления (значок колокольчика вверху).</Text>
                )}

                {hasActiveCode && (
                  <Stack gap="xs">
                    <Text size="sm" fw={600} id="code-label">
                      Код из 6 цифр
                    </Text>
                    <PinInput
                      length={6}
                      type="number"
                      oneTimeCode
                      value={code}
                      onChange={(v) => {
                        setCode(v);
                        if (v.length > 0) setCodeError(null);
                      }}
                      error={Boolean(codeError)}
                      aria-labelledby="code-label"
                      size="md"
                    />
                    <Text size="sm" c="dimmed">
                      Код действует еще {minutes}:{seconds}
                      {attemptsLeft !== undefined ? `, осталось попыток: ${attemptsLeft}` : ''}
                    </Text>
                    {codeError && (
                      <Text size="sm" c="red.8" role="alert">
                        {codeError}
                      </Text>
                    )}
                    <Group>
                      <Button size="lg" leftSection={<IconSignature size={18} aria-hidden />} disabled={code.length !== 6 || !app.available_actions.includes('SIGN')} loading={sign.isPending} onClick={() => sign.trigger({ code })}>
                        Подписать
                      </Button>
                    </Group>
                  </Stack>
                )}
                {!hasActiveCode && expiresAt && (
                  <Text size="sm" c="orange.8">
                    Код больше не действует, получите новый
                  </Text>
                )}
                {codeError && !hasActiveCode && (
                  <Text size="sm" c="red.8" role="alert">
                    {codeError}
                  </Text>
                )}
              </Stack>
            </SectionCard>
            <Title order={2} size="h6" c="dimmed" fw={400}>
              Подписание в прототипе смоделировано. Деньги поступят на счет сразу после подписания.
            </Title>
          </>
        )}
      </Stack>
    </>
  );
}
