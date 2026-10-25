const PREFIX = 'credit-cabinet:draft:';

export function readSessionDraft(key: string): unknown {
  try {
    const value = sessionStorage.getItem(PREFIX + key);
    return value ? JSON.parse(value) : null;
  } catch {
    return null;
  }
}

export function writeSessionDraft(key: string, value: unknown): boolean {
  try {
    sessionStorage.setItem(PREFIX + key, JSON.stringify(value));
    return true;
  } catch {
    return false;
  }
}

export function removeSessionDraft(key: string): void {
  try { sessionStorage.removeItem(PREFIX + key); } catch { /* Storage may be disabled. */ }
}

export function clearSessionDrafts(): void {
  try {
    for (const key of Object.keys(sessionStorage)) if (key.startsWith(PREFIX)) sessionStorage.removeItem(key);
  } catch { /* Storage may be disabled. */ }
}
