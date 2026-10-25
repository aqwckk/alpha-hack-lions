/** Date pickers select whole Moscow days; API upper bounds remain exclusive datetimes. */
export function moscowDateBoundary(value: string | undefined, nextDay = false): string | undefined {
  if (!value) return undefined;
  // Existing datetime deep links already follow the API contract.
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
  if (!nextDay) return `${value}T00:00:00+03:00`;
  const date = new Date(`${value}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + 1);
  return `${date.toISOString().slice(0, 10)}T00:00:00+03:00`;
}
