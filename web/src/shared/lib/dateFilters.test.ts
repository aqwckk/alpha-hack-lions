import { describe, expect, it } from 'vitest';
import { moscowDateBoundary } from './dateFilters';

describe('Moscow date filters', () => {
  it.each([
    ['2026-10-25', false, '2026-10-25T00:00:00+03:00'],
    ['2026-10-25', true, '2026-10-26T00:00:00+03:00'],
    ['2026-12-31', true, '2027-01-01T00:00:00+03:00'],
    ['2028-02-29', true, '2028-03-01T00:00:00+03:00'],
    ['2026-10-25T13:30:00Z', true, '2026-10-25T13:30:00Z'],
    [undefined, true, undefined],
  ])('maps %s (exclusive upper bound: %s) to %s', (value, nextDay, expected) => {
    expect(moscowDateBoundary(value, nextDay)).toBe(expected);
  });
});
