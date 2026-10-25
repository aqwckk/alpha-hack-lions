import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useRef, useState } from 'react';
import { withFreshVersion } from '@/shared/api/commands';
import { api } from '@/shared/api/endpoints';
import { storeApplication } from '@/shared/api/queries';
import type { ClientApplication } from '@/shared/api/types';
import { checkInn, INN_MESSAGES } from '@/shared/lib/inn';
import { toast } from '@/shared/ui/toast';

/** The typed INN remains owned by the whole form when its company step is unmounted. */
export function useInnConfirmation(app: ClientApplication) {
  const queryClient = useQueryClient();
  const serverInn = typeof app.form.applicant_inn === 'string' ? app.form.applicant_inn : '';
  const [value, setValue] = useState(serverInn);
  const attempted = useRef<string | null>(null);
  const check = checkInn(value);
  const prefill = useMutation({
    mutationFn: (inn: string) => withFreshVersion(queryClient, app.id, (version) => api.prefill(app.id, inn, version)),
    onSuccess: (res) => storeApplication(queryClient, res.application),
    onError: (error) => toast.error(error, 'Не удалось проверить ИНН. Повторите проверку.'),
  });
  const confirmed = value === serverInn && (app.inn_check_status === 'FOUND' || app.inn_check_status === 'UNAVAILABLE');
  const ready = check.ok && confirmed && !prefill.isPending && !(prefill.isError && prefill.variables === value);
  const dirty = value !== serverInn || prefill.isPending;
  const readiness = useRef(ready);
  readiness.current = ready;
  const isReady = useCallback(() => readiness.current, []);

  useEffect(() => {
    if (!check.ok || confirmed || prefill.isPending || attempted.current === value) return;
    const timer = setTimeout(() => {
      attempted.current = value;
      prefill.mutate(value);
    }, 300);
    return () => clearTimeout(timer);
  }, [value, check.ok, confirmed, prefill.isPending, prefill.mutate]);

  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if (dirty) {
        event.preventDefault();
        event.returnValue = '';
      }
    };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);

  const change = (next: string) => {
    const normalized = next.replace(/\D/g, '').slice(0, 12);
    if (normalized === value) return;
    readiness.current = false;
    attempted.current = null;
    setValue(normalized);
  };
  const retry = () => {
    if (!check.ok || prefill.isPending) return;
    readiness.current = false;
    attempted.current = value;
    prefill.mutate(value);
  };
  const error = !check.ok ? (value ? INN_MESSAGES[check.code] : 'Укажите ИНН компании или ИП')
    : value === serverInn && app.inn_check_status === 'NOT_FOUND' ? 'Компания или ИП с таким ИНН не найдены в госреестре. Проверьте ИНН'
    : prefill.isError && prefill.variables === value ? 'Не удалось проверить ИНН. Повторите проверку.' : null;

  return { value, change, retry, ready, isReady, dirty, error, isPending: prefill.isPending, canRetry: check.ok && !prefill.isPending };
}

export type InnConfirmation = ReturnType<typeof useInnConfirmation>;
