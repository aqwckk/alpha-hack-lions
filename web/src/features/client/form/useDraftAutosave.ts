import { useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useRef, useState } from 'react';
import type { UseFormReturn } from 'react-hook-form';
import { DRAFT_FIELDS, snapshot, type DraftField, type DraftValues, type PatchValue } from './formModel';
import { api } from '@/shared/api/endpoints';
import { isApiError } from '@/shared/api/errors';
import { currentVersion, putApplication, qk } from '@/shared/api/queries';
import type { DraftUpdateRequest } from '@/shared/api/types';
import { newId } from '@/shared/lib/ids';

export type SaveStatus =
  | { state: 'idle' }
  | { state: 'saving' }
  | { state: 'saved'; at: Date }
  | { state: 'retrying' }
  | { state: 'error'; message: string };

const DEBOUNCE_MS = 1500;
const NETWORK_RETRY_MS = 3000;
const MAX_NETWORK_RETRIES = 5;

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * Autosave of the draft (US-04): only changed fields are sent, with expected_version from the latest
 * server response. Saves are serialized; a network failure is retried with the same Idempotency-Key,
 * a version conflict re-reads the application and repeats with the fresh version.
 */
export function useDraftAutosave(appId: string, form: UseFormReturn<DraftValues>, initial: DraftValues) {
  const queryClient = useQueryClient();
  const saved = useRef<Record<DraftField, PatchValue>>(snapshot(initial));
  const inFlight = useRef<Promise<void> | null>(null);
  const again = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [status, setStatus] = useState<SaveStatus>({ state: 'idle' });

  const pendingPatch = useCallback((): Partial<Record<DraftField, PatchValue>> => {
    const current = snapshot(form.getValues());
    const patch: Partial<Record<DraftField, PatchValue>> = {};
    for (const f of DRAFT_FIELDS) {
      if (current[f] !== saved.current[f]) patch[f] = current[f];
    }
    return patch;
  }, [form]);

  const runSave = useCallback(async (): Promise<void> => {
    const patch = pendingPatch();
    const fields = Object.keys(patch) as DraftField[];
    if (fields.length === 0) return;
    setStatus({ state: 'saving' });
    let key = newId();
    let conflicts = 0;
    let networkFailures = 0;
    for (;;) {
      const version = currentVersion(queryClient, appId);
      if (version === undefined) return;
      try {
        const body = { expected_version: version, ...patch } as DraftUpdateRequest;
        const res = await api.updateDraft(appId, body, key);
        putApplication(queryClient, res.application);
        const errors = new Map((res.field_errors ?? []).map((e) => [e.field, e]));
        for (const f of fields) {
          const err = errors.get(f);
          if (err) {
            form.setError(f, { type: 'server', message: err.message ?? 'Проверьте значение' });
          } else {
            saved.current[f] = patch[f] ?? null;
            if (form.getFieldState(f).error?.type === 'server') form.clearErrors(f);
          }
        }
        setStatus({ state: 'saved', at: new Date() });
        return;
      } catch (error) {
        if (isApiError(error) && error.code === 'VERSION_CONFLICT' && conflicts < 2) {
          conflicts += 1;
          key = newId();
          await queryClient.refetchQueries({ queryKey: qk.application(appId), exact: true });
          continue;
        }
        if (isApiError(error) && error.kind === 'network' && networkFailures < MAX_NETWORK_RETRIES) {
          networkFailures += 1;
          setStatus({ state: 'retrying' });
          await sleep(NETWORK_RETRY_MS);
          continue;
        }
        setStatus({ state: 'error', message: isApiError(error) ? error.message : 'Не удалось сохранить' });
        return;
      }
    }
  }, [appId, form, pendingPatch, queryClient]);

  const save = useCallback((): Promise<void> => {
    if (timer.current) {
      clearTimeout(timer.current);
      timer.current = null;
    }
    if (inFlight.current) {
      again.current = true;
      return inFlight.current;
    }
    const p = runSave().finally(() => {
      inFlight.current = null;
      if (again.current) {
        again.current = false;
        void save();
      }
    });
    inFlight.current = p;
    return p;
  }, [runSave]);

  useEffect(() => {
    const sub = form.watch((_values, info) => {
      if (info.type !== 'change') return;
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => void save(), DEBOUNCE_MS);
    });
    return () => sub.unsubscribe();
  }, [form, save]);

  // Leaving the page with unsaved edits: save now and ask the browser to confirm closing.
  useEffect(() => {
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      if (Object.keys(pendingPatch()).length > 0 || inFlight.current) {
        void save();
        event.preventDefault();
      }
    };
    window.addEventListener('beforeunload', onBeforeUnload);
    return () => {
      window.removeEventListener('beforeunload', onBeforeUnload);
      if (timer.current) clearTimeout(timer.current);
      if (Object.keys(pendingPatch()).length > 0) void runSave();
    };
  }, [pendingPatch, runSave, save]);

  /** Saves pending edits right away (on blur, before moving to another step, before submit). */
  const flush = useCallback(async () => {
    await save();
    if (inFlight.current) await inFlight.current;
  }, [save]);

  return { status, flush };
}
