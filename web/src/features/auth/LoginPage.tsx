import { zodResolver } from '@hookform/resolvers/zod';
import { Alert, Badge, Button, Paper, PasswordInput, Stack, Table, Text, TextInput, Title } from '@mantine/core';
import { IconAlertTriangle, IconInfoCircle } from '@tabler/icons-react';
import { useEffect, useRef, useState } from 'react';
import { useForm } from 'react-hook-form';
import { Navigate, useLocation, useNavigate } from 'react-router-dom';
import { z } from 'zod';
import { homeFor, safeReturnPath, useAuth } from './AuthProvider';
import { DEMO_ACCOUNTS, DEMO_EXTRA_INNS, DEMO_SCENARIOS } from '@/features/demo/demoData';
import { isApiError } from '@/shared/api/errors';
import { useMeta } from '@/shared/api/queries';
import { ROLE_LABELS } from '@/shared/lib/labels';

const schema = z.object({
  login: z.string().trim().min(1, 'Введите логин'),
  password: z.string().min(1, 'Введите пароль'),
});
type Values = z.infer<typeof schema>;

export function LoginPage() {
  const { state, login } = useAuth();
  const meta = useMeta();
  const navigate = useNavigate();
  const location = useLocation();
  const [formError, setFormError] = useState<string | null>(null);
  const titleRef = useRef<HTMLHeadingElement>(null);
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: { login: '', password: '' } });
  const from = (location.state as { from?: unknown } | null)?.from;

  useEffect(() => {
    document.title = 'Вход | Кредитный кабинет';
    titleRef.current?.focus();
  }, []);

  if (state.status === 'authenticated') {
    return <Navigate to={safeReturnPath(from, state.user.role) ?? homeFor(state.user.role)} replace />;
  }

  const onSubmit = form.handleSubmit(async (values) => {
    setFormError(null);
    try {
      const user = await login(values.login, values.password);
      navigate(safeReturnPath(from, user.role) ?? homeFor(user.role), { replace: true });
    } catch (e) {
      if (isApiError(e) && e.status === 401) setFormError('Неверный логин или пароль');
      else if (isApiError(e) && e.status === 429) setFormError(e.message || 'Слишком много попыток. Подождите минуту и попробуйте снова');
      else if (isApiError(e)) setFormError(e.message);
      else setFormError('Не удалось войти, попробуйте еще раз');
    }
  });

  const fill = (loginValue: string, password: string) => {
    form.setValue('login', loginValue, { shouldValidate: true });
    form.setValue('password', password, { shouldValidate: true });
    form.setFocus('password');
  };

  return (
    <main className="login-wrap" id="main">
      <Stack w="100%" maw={demoWidth(meta.data?.demo_mode)} gap="lg">
        <Stack gap={6} align="center" ta="center">
          <div className="app-logo">
            <span className="app-logo-mark" aria-hidden>
              ₽
            </span>
            <span>Кредитный кабинет</span>
          </div>
          <Text c="dimmed" size="sm">
            Кредиты для малого бизнеса: от задачи до денег на счете в одном окне
          </Text>
        </Stack>
        <div style={{ display: 'grid', gap: 20, gridTemplateColumns: meta.data?.demo_mode ? 'repeat(auto-fit, minmax(300px, 1fr))' : '1fr' }}>
          <Paper withBorder radius="lg" p="xl" shadow="sm">
            <form onSubmit={onSubmit} noValidate>
              <Stack gap="md">
                <Title order={1} size="h3" ref={titleRef} tabIndex={-1} className="page-title">
                  Вход
                </Title>
                {state.status === 'anonymous' && state.reason === 'expired' && (
                  <Alert color="orange" icon={<IconInfoCircle aria-hidden />} role="status">
                    Сессия истекла, войдите снова. Введенные данные заявки сохранены.
                  </Alert>
                )}
                {formError && (
                  <Alert color="red" icon={<IconAlertTriangle aria-hidden />} role="alert">
                    {formError}
                  </Alert>
                )}
                <TextInput label="Логин" autoComplete="username" {...form.register('login')} error={form.formState.errors.login?.message} />
                <PasswordInput label="Пароль" autoComplete="current-password" {...form.register('password')} error={form.formState.errors.password?.message} />
                <Button type="submit" size="md" loading={form.formState.isSubmitting}>
                  Войти
                </Button>
                <Text size="xs" c="dimmed">
                  Это прототип на синтетических данных, не продукт банка. Тестовые учетные записи перечислены в README.
                </Text>
              </Stack>
            </form>
          </Paper>
          {meta.data?.demo_mode && (
            <Paper withBorder radius="lg" p="lg" shadow="sm">
              <Stack gap="sm">
                <Title order={2} size="h4">
                  Тестовые учетные записи
                </Title>
                <Text size="sm" c="dimmed">
                  Демо-режим. Нажмите на логин, чтобы подставить его в форму. Пароли публичные и синтетические.
                </Text>
                <div className="table-scroll" style={{ maxHeight: 420 }}>
                  <Table verticalSpacing={6} striped highlightOnHover style={{ minWidth: 0 }}>
                    <Table.Thead>
                      <Table.Tr>
                        <Table.Th>Логин</Table.Th>
                        <Table.Th>Роль и сценарий</Table.Th>
                      </Table.Tr>
                    </Table.Thead>
                    <Table.Tbody>
                      {DEMO_ACCOUNTS.map((a) => (
                        <Table.Tr key={a.login}>
                          <Table.Td>
                            <Button variant="subtle" size="compact-sm" onClick={() => fill(a.login, a.password)} aria-label={`Подставить логин ${a.login}`}>
                              {a.login}
                            </Button>
                          </Table.Td>
                          <Table.Td>
                            <Text size="sm">
                              <Badge size="xs" variant="light" mr={6} color={a.role === 'CLIENT' ? 'blue' : a.role === 'UNDERWRITER' ? 'violet' : 'orange'}>
                                {ROLE_LABELS[a.role]}
                              </Badge>
                              {a.who}: {a.scenario}
                              {DEMO_SCENARIOS[a.login] ? `, ИНН ${DEMO_SCENARIOS[a.login]?.inn ?? ''}` : ''}
                            </Text>
                          </Table.Td>
                        </Table.Tr>
                      ))}
                    </Table.Tbody>
                  </Table>
                </div>
                <Text size="xs" c="dimmed">
                  Пароль клиентов Demo-Client-2026, андеррайтеров Demo-Uw-2026, риск-менеджера Demo-Risk-2026. Для client.demo подойдут ИНН:{' '}
                  {DEMO_EXTRA_INNS.slice(0, 4)
                    .map((x) => x.inn)
                    .join(', ')}{' '}
                  и любой корректный ИНН.
                </Text>
              </Stack>
            </Paper>
          )}
        </div>
      </Stack>
    </main>
  );
}

function demoWidth(demo: boolean | undefined): number {
  return demo ? 1040 : 440;
}
