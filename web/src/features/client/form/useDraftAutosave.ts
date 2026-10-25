import { useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useRef, useState } from 'react';
import type { UseFormReturn } from 'react-hook-form';
import { DRAFT_FIELDS, snapshot, type DraftField, type DraftValues, type PatchValue } from './formModel';
import { api } from '@/shared/api/endpoints';
import { isApiError } from '@/shared/api/errors';
import { currentVersion, putApplication } from '@/shared/api/queries';
import type { DraftUpdateRequest } from '@/shared/api/types';
import { newId } from '@/shared/lib/ids';

export type SaveStatus =
  | { state: 'idle' }
  | { state: 'saving' }
  | { state: 'saved'; at: Date }
  | { state: 'retrying' }
  | { state: 'error'; message: string };

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
type PendingRequest = { body: DraftUpdateRequest; patch: Partial<Record<DraftField, PatchValue>>; key: string };

/** A flush drains edits made even while a previous PATCH was awaiting its response. */
export function useDraftAutosave(appId: string, form: UseFormReturn<DraftValues>, initial: DraftValues) {
  const queryClient = useQueryClient();
  const saved = useRef(snapshot(initial));
  const request = useRef<PendingRequest | null>(null);
  const inFlight = useRef<Promise<boolean> | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [status, setStatus] = useState<SaveStatus>({ state: 'idle' });

  const pendingPatch = useCallback(() => {
    const current = snapshot(form.getValues());
    const patch: Partial<Record<DraftField, PatchValue>> = {};
    for (const f of DRAFT_FIELDS) if (current[f] !== saved.current[f]) patch[f] = current[f];
    return patch;
  }, [form]);

  const drain = useCallback(async (): Promise<boolean> => {
    let conflicts = 0;
    let networkFailures = 0;
    try {
      for (;;) {
        const patch = request.current?.patch ?? pendingPatch();
        if (Object.keys(patch).length === 0) return true;
        setStatus({ state: 'saving' });
        if (!request.current) {
          const version = currentVersion(queryClient, appId);
          if (version === undefined) throw new Error('Не удалось получить версию заявки. Повторите сохранение.');
          request.current = { body: { expected_version: version, ...patch } as DraftUpdateRequest, patch, key: newId() };
        }
        const active = request.current;
        try {
          const res = await api.updateDraft(appId, active.body, active.key);
          putApplication(queryClient, res.application);
          request.current = null;
          networkFailures = 0;
          const errors = new Map((res.field_errors ?? []).map((e) => [e.field, e]));
          for (const f of DRAFT_FIELDS) {
            const err = errors.get(f);
            if (err) form.setError(f, { type: 'server', message: err.message ?? 'Проверьте значение' });
            else if (f in active.patch) {
              saved.current[f] = active.patch[f] ?? null;
              if (snapshot(form.getValues())[f] === active.patch[f] && form.getFieldState(f).error?.type === 'server') form.clearErrors(f);
            }
          }
          if (errors.size > 0) {
            setStatus({ state: 'error', message: 'Есть несохраненные поля. Исправьте ошибки и повторите сохранение.' });
            return false;
          }
          // Only report success after the current values, including edits during the request, are saved.
          if (Object.keys(pendingPatch()).length === 0) {
            setStatus({ state: 'saved', at: new Date() });
            return true;
          }
        } catch (error) {
          if (isApiError(error) && error.code === 'VERSION_CONFLICT' && conflicts < 2) {
            conflicts += 1;
            request.current = null;
            putApplication(queryClient, await api.getApplication(appId));
            continue;
          }
          if (isApiError(error) && (error.kind === 'network' || error.status >= 500)) {
            // Preserve both body and key, even after automatic retries are exhausted.
            if (networkFailures < 2) {
              networkFailures += 1;
              setStatus({ state: 'retrying' });
              await sleep(1500);
              continue;
            }
          } else {
            request.current = null;
          }
          if (isApiError(error)) {
            for (const err of error.fields) {
              if (DRAFT_FIELDS.includes(err.field as DraftField)) form.setError(err.field as DraftField, { type: 'server', message: err.message ?? 'Проверьте значение' });
            }
          }
          throw error;
        }
      }
    } catch (error) {
      setStatus({ state: 'error', message: error instanceof Error ? error.message : 'Не удалось сохранить' });
      return false;
    }
  }, [appId, form, pendingPatch, queryClient]);

  const flush = useCallback((): Promise<boolean> => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    if (!inFlight.current) {
      inFlight.current = Promise.resolve().then(drain).finally(() => { inFlight.current = null; });
    }
    return inFlight.current;
  }, [drain]);

  const hasPending = useCallback(() => Boolean(request.current || inFlight.current || Object.keys(pendingPatch()).length), [pendingPatch]);

  useEffect(() => {
    const sub = form.watch((_values, info) => {
      if (info.type !== 'change') return;
      setStatus((prev) => prev.state === 'saved' ? { state: 'idle' } : prev);
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => void flush(), 1500);
    });
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      if (hasPending()) {
        void flush();
        event.preventDefault();
        event.returnValue = '';
      }
    };
    window.addEventListener('beforeunload', onBeforeUnload);
    return () => {
      sub.unsubscribe();
      window.removeEventListener('beforeunload', onBeforeUnload);
      if (timer.current) clearTimeout(timer.current);
    };
  }, [form, flush, hasPending]);

  return { status, flush, hasPending };
}
