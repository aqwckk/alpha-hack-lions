import { describe, expect, it } from 'vitest';
import { checkInn } from './inn';

describe('checkInn', () => {
  it.each([
    ['0010002014', { ok: true, kind: 'LEGAL_ENTITY' }],
    ['002000010193', { ok: true, kind: 'INDIVIDUAL_ENTREPRENEUR' }],
    ['0010002015', { ok: false, code: 'INN_CHECKSUM' }],
    ['002000010194', { ok: false, code: 'INN_CHECKSUM' }],
    ['00100020', { ok: false, code: 'INN_LENGTH' }],
    ['00200001019a', { ok: false, code: 'INN_LENGTH' }],
  ])('%s', (inn, expected) => {
    expect(checkInn(inn)).toEqual(expected);
  });
});
