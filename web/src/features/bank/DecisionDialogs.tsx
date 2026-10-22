import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Checkbox,
  Group,
  Modal,
  MultiSelect,
  NumberInput,
  Paper,
  SegmentedControl,
  Select,
  Stack,
  Text,
  Textarea,
} from '@mantine/core';
import { useDebouncedValue } from '@mantine/hooks';
import { IconAlertTriangle, IconEye, IconPlus, IconTrash } from '@tabler/icons-react';
import { useQuery } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';
import { useStaffCommand } from '@/shared/api/commands';
import { api } from '@/shared/api/endpoints';
import { useBankDictionaries, useProduct } from '@/shared/api/queries';
import type { InfoItemInput, ProposedOption, StaffCard, StaffDecision } from '@/shared/api/types';
import { formatMoney, formatRate, formatTerm } from '@/shared/lib/format';
import { newId } from '@/shared/lib/ids';
import { OUTCOME_LABELS, productName } from '@/shared/lib/labels';
import { KeyValue } from '@/shared/ui/components';

export type DialogKind =
  | 'TAKE'
  | 'RELEASE'
  | 'APPROVE'
  | 'MAKE_COUNTER_OFFER'
  | 'REQUEST_INFO'
  | 'DECLINE'
  | 'CONFIRM_DECISION'
  | 'RETURN_DECISION'
  | 'RETRY_PROCESSING';

export function latestAutoDecision(card: StaffCard): StaffDecision | undefined {
  return [...card.decisions].reverse().find((d) => d.mode === 'AUTO');
}

export function latestProposal(card: StaffCard): StaffDecision | undefined {
  return [...card.decisions].reverse().find((d) => d.status === 'PROPOSED');
}

function requested(card: StaffCard): { amount: number; term: number } {
  const amount = Number(card.form.amount ?? 0);
  const term = Number(card.form.term_months ?? 0);
  return { amount, term };
}

function CommentField({ value, onChange, required, label = 'Комментарий' }: { value: string; onChange: (v: string) => void; required: boolean; label?: string }) {
  return (
    <Textarea
      label={label}
      description={required ? 'Обязательно: комментарий попадет в журнал решения' : 'Необязательно'}
      withAsterisk={required}
      autosize
      minRows={3}
      maxLength={2000}
      value={value}
      onChange={(e) => onChange(e.currentTarget.value)}
      data-autofocus
    />
  );
}

function DialogFooter({ onClose, onSubmit, label, disabled, loading, danger }: { onClose: () => void; onSubmit: () => void; label: string; disabled?: boolean; loading: boolean; danger?: boolean }) {
  return (
    <Group justify="flex-end" gap="sm" mt="sm">
      <Button variant="default" onClick={onClose}>
        Отмена
      </Button>
      <Button onClick={onSubmit} disabled={disabled} loading={loading} color={danger ? 'red' : undefined}>
        {label}
      </Button>
    </Group>
  );
}

const SUCCESS_TEXT: Record<'TAKE' | 'RELEASE' | 'APPROVE' | 'CONFIRM_DECISION' | 'RETURN_DECISION' | 'RETRY_PROCESSING', string> = {
  TAKE: 'Заявка закреплена за вами',
  RELEASE: 'Заявка возвращена в очередь',
  APPROVE: 'Решение принято. Если нужны 4 глаза, заявка ушла риск-менеджеру',
  CONFIRM_DECISION: 'Решение подтверждено, клиент видит предложение',
  RETURN_DECISION: 'Решение возвращено андеррайтеру',
  RETRY_PROCESSING: 'Обработка запущена повторно',
};

/** One dialog for every command that takes only a comment (with optional context above it). */
function CommentCommandDialog({
  card,
  kind,
  onClose,
  title,
  submitLabel,
  commentRequired,
  children,
  danger,
}: {
  card: StaffCard;
  kind: 'TAKE' | 'RELEASE' | 'APPROVE' | 'CONFIRM_DECISION' | 'RETURN_DECISION' | 'RETRY_PROCESSING';
  onClose: () => void;
  title: string;
  submitLabel: string;
  commentRequired: boolean;
  children?: ReactNode;
  danger?: boolean;
}) {
  const [comment, setComment] = useState('');
  const run = ({ version, key, comment: c }: { version: number; key: string; comment: string }) => {
    switch (kind) {
      case 'TAKE':
        return api.take(card.id, version, key);
      case 'RELEASE':
        return api.release(card.id, version, c, key);
      case 'APPROVE':
        return api.approve(card.id, version, c, key);
      case 'CONFIRM_DECISION':
        return api.confirm(card.id, version, c, key);
      case 'RETURN_DECISION':
        return api.returnDecision(card.id, version, c, key);
      case 'RETRY_PROCESSING':
        return api.retry(card.id, version, key);
    }
  };
  const cmd = useStaffCommand<{ comment: string }>(card.id, run, { success: SUCCESS_TEXT[kind], onSuccess: onClose });
  const withComment = kind !== 'TAKE' && kind !== 'RETRY_PROCESSING';
  return (
    <Modal opened onClose={onClose} title={title} size="lg" centered>
      <Stack gap="md">
        {children}
        {withComment && <CommentField value={comment} onChange={setComment} required={commentRequired} />}
        <DialogFooter
          onClose={onClose}
          onSubmit={() => cmd.trigger({ comment: comment.trim() }, card.version)}
          label={submitLabel}
          disabled={withComment && commentRequired && comment.trim().length < 3}
          loading={cmd.isPending}
          danger={danger}
        />
      </Stack>
    </Modal>
  );
}

function OptionSummary({ options }: { options: ProposedOption[] }) {
  return (
    <Stack gap={6}>
      {options.map((o, i) => (
        <Paper key={i} withBorder p="xs" radius="md">
          <Group justify="space-between" wrap="wrap" gap="xs">
            <Text size="sm" fw={600}>
              {productName(o.product_code)}: {formatMoney(o.amount)} на {formatTerm(o.term_months)}, {formatRate(o.rate_percent)}
            </Text>
            <Text size="sm" className="num">
              платеж {formatMoney(o.monthly_payment)}
            </Text>
          </Group>
        </Paper>
      ))}
    </Stack>
  );
}

function ApproveDialog({ card, onClose }: { card: StaffCard; onClose: () => void }) {
  const auto = latestAutoDecision(card);
  const rec = auto?.recommendation ?? null;
  const req = requested(card);
  const maxAmount = rec?.max_amount_requested_term ? Number(rec.max_amount_requested_term) : null;
  const override = Boolean(rec && (rec.outcome !== 'APPROVED' || (maxAmount !== null && req.amount > maxAmount)));
  const values = auto?.values ?? {};
  return (
    <CommentCommandDialog card={card} kind="APPROVE" onClose={onClose} title="Одобрить на запрошенных условиях" submitLabel="Одобрить" commentRequired>
      <KeyValue
        cols={2}
        items={[
          { label: 'Продукт', value: card.product_name },
          { label: 'Сумма и срок', value: `${formatMoney(req.amount)}, ${formatTerm(req.term)}` },
          { label: 'Ставка по матрице грейда', value: values.rate_percent ? formatRate(String(values.rate_percent)) : 'по матрице' },
          { label: 'Платеж по запросу', value: values.requested_payment ? formatMoney(String(values.requested_payment)) : 'рассчитается' },
          { label: 'Допустимый платеж', value: values.allowed_payment ? formatMoney(String(values.allowed_payment)) : 'нет данных' },
        ]}
      />
      {override ? (
        <Alert color="orange" icon={<IconAlertTriangle aria-hidden />} title="Решение отличается от рекомендации политики">
          Политика рекомендует: {OUTCOME_LABELS[rec?.outcome ?? ''] ?? rec?.outcome}
          {maxAmount !== null ? `, максимум ${formatMoney(maxAmount)} на ${formatTerm(req.term)}` : ''}. Это переопределение: решение уйдет на подтверждение риск-менеджеру (4 глаза).
        </Alert>
      ) : (
        <Text size="sm" c="dimmed">
          Если сумма выше лимита полномочий андеррайтера, решение автоматически уйдет на подтверждение риск-менеджеру.
        </Text>
      )}
    </CommentCommandDialog>
  );
}

interface OptionRow {
  id: string;
  product_code: string;
  amount: number | '';
  term_months: number | '';
}

function OptionRowEditor({ row, card, onChange, onRemove, canRemove, rateHint }: { row: OptionRow; card: StaffCard; onChange: (r: OptionRow) => void; onRemove: () => void; canRemove: boolean; rateHint: string | null }) {
  const product = useProduct(row.product_code);
  const [debounced] = useDebouncedValue(row, 300);
  const inBounds =
    product &&
    typeof debounced.amount === 'number' &&
    typeof debounced.term_months === 'number' &&
    debounced.amount >= Number(product.amount_min) &&
    debounced.amount <= Number(product.amount_max) &&
    debounced.term_months >= product.term_min_months &&
    debounced.term_months <= product.term_max_months;
  const rate = row.product_code === card.product_code ? rateHint : null;
  const calc = useQuery({
    queryKey: ['catalog', 'calculate', debounced.product_code, debounced.amount, debounced.term_months, rate],
    queryFn: () =>
      api.calculate({ product_code: debounced.product_code, amount: String(debounced.amount), term_months: Number(debounced.term_months), ...(rate ? { rate_percent: rate } : {}) }),
    enabled: Boolean(inBounds),
    retry: false,
  });
  return (
    <Paper withBorder radius="md" p="sm">
      <Group align="flex-end" gap="sm" wrap="wrap">
        <Select
          label="Продукт"
          data={[card.product_code, 'CREDIT_LINE'].filter((v, i, a) => a.indexOf(v) === i).map((v) => ({ value: v, label: productName(v) }))}
          value={row.product_code}
          onChange={(v) => v && onChange({ ...row, product_code: v })}
          w={210}
          allowDeselect={false}
        />
        <NumberInput
          label="Сумма"
          value={row.amount}
          onChange={(v) => onChange({ ...row, amount: typeof v === 'number' ? v : '' })}
          thousandSeparator=" "
          suffix=" ₽"
          allowDecimal={false}
          allowNegative={false}
          hideControls
          w={190}
          error={product && typeof row.amount === 'number' && (row.amount < Number(product.amount_min) || row.amount > Number(product.amount_max)) ? `от ${formatMoney(product.amount_min)} до ${formatMoney(product.amount_max)}` : undefined}
        />
        <NumberInput
          label="Срок, мес."
          value={row.term_months}
          onChange={(v) => onChange({ ...row, term_months: typeof v === 'number' ? v : '' })}
          allowDecimal={false}
          allowNegative={false}
          w={120}
          error={product && typeof row.term_months === 'number' && (row.term_months < product.term_min_months || row.term_months > product.term_max_months) ? `${product.term_min_months}-${product.term_max_months}` : undefined}
        />
        {canRemove && (
          <ActionIcon variant="subtle" color="red" onClick={onRemove} aria-label="Удалить вариант" mb={4}>
            <IconTrash size={18} aria-hidden />
          </ActionIcon>
        )}
      </Group>
      <Text size="sm" mt={6} c="dimmed" aria-live="polite">
        {calc.data
          ? `Платеж около ${formatMoney(calc.data.monthly_payment)} в месяц при ставке ${formatRate(calc.data.rate_percent)}${rate ? ' (матрица грейда)' : ' (базовая, итоговая по матрице грейда)'}`
          : 'Укажите сумму и срок в границах продукта'}
      </Text>
    </Paper>
  );
}

function CounterOfferDialog({ card, onClose }: { card: StaffCard; onClose: () => void }) {
  const auto = latestAutoDecision(card);
  const rec = auto?.recommendation;
  const req = requested(card);
  const initial: OptionRow[] =
    rec?.options && rec.options.length > 0
      ? rec.options.slice(0, 3).map((o) => ({ id: newId(), product_code: o.product_code, amount: Number(o.amount), term_months: o.term_months }))
      : [{ id: newId(), product_code: card.product_code, amount: req.amount, term_months: req.term }];
  const [rows, setRows] = useState<OptionRow[]>(initial);
  const [comment, setComment] = useState('');
  const rateHint = auto?.values?.rate_percent ? String(auto.values.rate_percent) : null;
  const cmd = useStaffCommand<{ comment: string; options: { product_code: string; amount: string; term_months: number }[] }>(
    card.id,
    ({ version, key, comment: c, options }) => api.counterOffer(card.id, version, options, c, key),
    { success: 'Контрпредложение сохранено', onSuccess: onClose },
  );
  const valid = rows.every((r) => typeof r.amount === 'number' && r.amount > 0 && typeof r.term_months === 'number' && r.term_months > 0);
  const differs = rec && rec.outcome !== 'COUNTER_OFFER';
  return (
    <Modal opened onClose={onClose} title="Изменить условия (контрпредложение)" size="xl" centered>
      <Stack gap="md">
        <Text size="sm">
          Клиент просил {formatMoney(req.amount)} на {formatTerm(req.term)}. Задайте от 1 до 3 вариантов, ставка назначится по матрице грейда.
        </Text>
        {rec?.options && rec.options.length > 0 && (
          <Alert color="blue" variant="light" title="Рекомендация политики">
            <OptionSummary options={rec.options} />
          </Alert>
        )}
        {differs && (
          <Alert color="orange" icon={<IconAlertTriangle aria-hidden />}>
            Это решение отличается от рекомендации политики ({OUTCOME_LABELS[rec.outcome] ?? rec.outcome}). Может потребоваться подтверждение риск-менеджера.
          </Alert>
        )}
        {rows.map((row) => (
          <OptionRowEditor
            key={row.id}
            row={row}
            card={card}
            rateHint={rateHint}
            onChange={(r) => setRows((all) => all.map((x) => (x.id === r.id ? r : x)))}
            onRemove={() => setRows((all) => all.filter((x) => x.id !== row.id))}
            canRemove={rows.length > 1}
          />
        ))}
        {rows.length < 3 && (
          <Group>
            <Button variant="subtle" leftSection={<IconPlus size={16} aria-hidden />} onClick={() => setRows((all) => [...all, { id: newId(), product_code: card.product_code, amount: req.amount, term_months: req.term }])}>
              Добавить вариант
            </Button>
          </Group>
        )}
        <CommentField value={comment} onChange={setComment} required />
        <DialogFooter
          onClose={onClose}
          label="Отправить клиенту"
          disabled={!valid || comment.trim().length < 3}
          loading={cmd.isPending}
          onSubmit={() =>
            cmd.trigger(
              {
                comment: comment.trim(),
                options: rows.map((r) => ({
                  product_code: r.product_code,
                  amount: String(r.amount),
                  term_months: Number(r.term_months),
                })),
              },
              card.version,
            )
          }
        />
      </Stack>
    </Modal>
  );
}

interface InfoRow {
  id: string;
  reason_code: string;
  answer_type: 'TEXT' | 'FIELD' | 'DOCUMENT';
  field_name: string | null;
  document_type: string | null;
  client_text: string;
  required: boolean;
}

function RequestInfoDialog({ card, onClose }: { card: StaffCard; onClose: () => void }) {
  const dict = useBankDictionaries();
  const [rows, setRows] = useState<InfoRow[]>([
    { id: newId(), reason_code: '', answer_type: 'TEXT', field_name: null, document_type: null, client_text: '', required: true },
  ]);
  const [comment, setComment] = useState('');
  const [preview, setPreview] = useState(false);
  const cmd = useStaffCommand<{ comment: string; items: InfoItemInput[] }>(card.id, ({ version, key, comment: c, items }) => api.requestInfo(card.id, version, items, c, key), {
    success: 'Запрос отправлен клиенту',
    onSuccess: onClose,
  });
  const template = (code: string, docType: string | null): string => {
    const t = dict.data?.info_reason_codes.find((r) => r.code === code)?.client_text_template ?? '';
    const doc = dict.data?.document_types.find((d) => d.code === docType);
    return t.replace('{document_name}', doc?.title ?? 'документ').replace('{document_purpose}', doc?.purpose ?? 'оценить заявку');
  };
  const update = (id: string, patch: Partial<InfoRow>) =>
    setRows((all) =>
      all.map((r) => {
        if (r.id !== id) return r;
        const next = { ...r, ...patch };
        if (patch.reason_code !== undefined || patch.document_type !== undefined) next.client_text = template(next.reason_code, next.document_type);
        return next;
      }),
    );
  const valid = rows.every(
    (r) => r.reason_code && (r.answer_type !== 'FIELD' || r.field_name) && (r.answer_type !== 'DOCUMENT' || r.document_type),
  );
  const items: InfoItemInput[] = rows.map((r) => ({
    reason_code: r.reason_code,
    answer_type: r.answer_type,
    required: r.required,
    ...(r.answer_type === 'FIELD' && r.field_name ? { field_name: r.field_name } : {}),
    ...(r.answer_type === 'DOCUMENT' && r.document_type ? { document_type: r.document_type } : {}),
    ...(r.client_text.trim() ? { client_text: r.client_text.trim() } : {}),
  }));

  return (
    <Modal opened onClose={onClose} title="Запросить данные у клиента" size="xl" centered>
      <Stack gap="md">
        <Text size="sm" c="dimmed">
          Один запрос на все уточнения: клиент ответит за один раз. Тексты для клиента можно поправить.
        </Text>
        {rows.map((row, idx) => (
          <Paper key={row.id} withBorder radius="md" p="sm">
            <Stack gap="xs">
              <Group justify="space-between">
                <Text fw={600} size="sm">
                  Пункт {idx + 1}
                </Text>
                {rows.length > 1 && (
                  <ActionIcon variant="subtle" color="red" aria-label={`Удалить пункт ${idx + 1}`} onClick={() => setRows((all) => all.filter((r) => r.id !== row.id))}>
                    <IconTrash size={16} aria-hidden />
                  </ActionIcon>
                )}
              </Group>
              <Select
                label="Причина"
                placeholder="Выберите"
                data={(dict.data?.info_reason_codes ?? []).map((r) => ({ value: r.code, label: `${r.code}: ${r.employee_text}` }))}
                value={row.reason_code || null}
                onChange={(v) => update(row.id, { reason_code: v ?? '' })}
                searchable
              />
              <SegmentedControl
                value={row.answer_type}
                onChange={(v) => update(row.id, { answer_type: v as InfoRow['answer_type'] })}
                data={[
                  { value: 'TEXT', label: 'Текстовый ответ' },
                  { value: 'FIELD', label: 'Поле анкеты' },
                  { value: 'DOCUMENT', label: 'Документ' },
                ]}
                aria-label="Тип ответа"
              />
              {row.answer_type === 'FIELD' && (
                <Select
                  label="Поле анкеты"
                  data={(dict.data?.requestable_fields ?? []).map((f) => ({ value: f.field_name, label: f.label }))}
                  value={row.field_name}
                  onChange={(v) => update(row.id, { field_name: v })}
                />
              )}
              {row.answer_type === 'DOCUMENT' && (
                <Select
                  label="Документ"
                  data={(dict.data?.document_types ?? []).map((d) => ({ value: d.code, label: d.title }))}
                  value={row.document_type}
                  onChange={(v) => update(row.id, { document_type: v })}
                />
              )}
              <Textarea label="Текст для клиента" autosize minRows={2} value={row.client_text} onChange={(e) => update(row.id, { client_text: e.currentTarget.value })} />
              <Checkbox label="Обязательный пункт" checked={row.required} onChange={(e) => update(row.id, { required: e.currentTarget.checked })} />
            </Stack>
          </Paper>
        ))}
        {rows.length < 10 && (
          <Group>
            <Button
              variant="subtle"
              leftSection={<IconPlus size={16} aria-hidden />}
              onClick={() => setRows((all) => [...all, { id: newId(), reason_code: '', answer_type: 'TEXT', field_name: null, document_type: null, client_text: '', required: true }])}
            >
              Добавить пункт
            </Button>
            <Button variant="subtle" leftSection={<IconEye size={16} aria-hidden />} onClick={() => setPreview((v) => !v)} aria-expanded={preview}>
              Так клиент увидит запрос
            </Button>
          </Group>
        )}
        {preview && (
          <Paper withBorder radius="md" p="md" bg="gray.0">
            <Text fw={700} mb="xs">
              Нужны данные от вас
            </Text>
            <Stack gap={6}>
              {rows.map((r, i) => (
                <Text key={r.id} size="sm">
                  {i + 1}. {r.client_text || '(текст по шаблону причины)'} {r.required ? <Badge size="xs">обязательно</Badge> : null}
                </Text>
              ))}
            </Stack>
          </Paper>
        )}
        <CommentField value={comment} onChange={setComment} required label="Внутренний комментарий" />
        <DialogFooter onClose={onClose} label="Отправить запрос" disabled={!valid || comment.trim().length < 3} loading={cmd.isPending} onSubmit={() => cmd.trigger({ comment: comment.trim(), items }, card.version)} />
      </Stack>
    </Modal>
  );
}

function DeclineDialog({ card, onClose }: { card: StaffCard; onClose: () => void }) {
  const dict = useBankDictionaries();
  const [codes, setCodes] = useState<string[]>([]);
  const [comment, setComment] = useState('');
  const cmd = useStaffCommand<{ comment: string; codes: string[] }>(card.id, ({ version, key, comment: c, codes: list }) => api.decline(card.id, version, list, c, key), {
    success: 'Отказ оформлен',
    onSuccess: onClose,
  });
  const options = (dict.data?.decline_reason_codes ?? []).filter((r) => r.code !== 'DCL_AFFORDABILITY');
  const selected = options.filter((o) => codes.includes(o.code));
  return (
    <Modal opened onClose={onClose} title="Отказать" size="lg" centered>
      <Stack gap="md">
        <MultiSelect
          label="Причины отказа"
          withAsterisk
          placeholder="Выберите одну или несколько"
          data={options.map((o) => ({ value: o.code, label: `${o.code}: ${o.employee_text}` }))}
          value={codes}
          onChange={setCodes}
          searchable
        />
        {selected.length > 0 && (
          <Paper withBorder radius="md" p="md" bg="gray.0">
            <Text fw={700} size="sm" mb={4}>
              Так клиент увидит причину
            </Text>
            {selected.map((o) => (
              <Text key={o.code} size="sm">
                {o.client_text ?? 'Причина не раскрывается клиенту, он увидит общий текст.'}
              </Text>
            ))}
          </Paper>
        )}
        <CommentField value={comment} onChange={setComment} required />
        <DialogFooter onClose={onClose} label="Отказать" danger disabled={codes.length === 0 || comment.trim().length < 3} loading={cmd.isPending} onSubmit={() => cmd.trigger({ comment: comment.trim(), codes }, card.version)} />
      </Stack>
    </Modal>
  );
}

function ProposalSummary({ card }: { card: StaffCard }) {
  const proposal = latestProposal(card);
  if (!proposal) return <Text size="sm">Проект решения не найден, обновите карточку.</Text>;
  return (
    <Stack gap="xs">
      <KeyValue
        cols={2}
        items={[
          { label: 'Исход', value: OUTCOME_LABELS[proposal.outcome] ?? proposal.outcome },
          { label: 'Автор проекта', value: proposal.proposed_by ?? 'не указан' },
          { label: 'Причина 4 глаз', value: proposal.four_eyes_trigger === 'OVERRIDE' ? 'переопределение рекомендации политики' : proposal.four_eyes_trigger === 'AUTHORITY_LIMIT' ? 'сумма выше лимита полномочий' : (proposal.four_eyes_trigger ?? 'нет') },
          { label: 'Переопределение', value: proposal.override ? 'да' : 'нет' },
        ]}
      />
      {proposal.proposed_options && <OptionSummary options={proposal.proposed_options} />}
      {proposal.comment && (
        <Alert color="gray" variant="light" title="Комментарий андеррайтера">
          {proposal.comment}
        </Alert>
      )}
    </Stack>
  );
}

export function DecisionDialog({ kind, card, onClose }: { kind: DialogKind; card: StaffCard; onClose: () => void }) {
  switch (kind) {
    case 'TAKE':
      return (
        <CommentCommandDialog card={card} kind="TAKE" onClose={onClose} title="Взять заявку в работу" submitLabel="Взять в работу" commentRequired={false}>
          <Text size="sm">Заявка закрепится за вами. Если ее одновременно возьмет коллега, мы сообщим, кто успел первым.</Text>
        </CommentCommandDialog>
      );
    case 'RELEASE':
      return (
        <CommentCommandDialog card={card} kind="RELEASE" onClose={onClose} title="Вернуть заявку в очередь" submitLabel="Вернуть в очередь" commentRequired>
          <Text size="sm">Заявку сможет взять другой андеррайтер. Срок SLA не меняется.</Text>
        </CommentCommandDialog>
      );
    case 'APPROVE':
      return <ApproveDialog card={card} onClose={onClose} />;
    case 'MAKE_COUNTER_OFFER':
      return <CounterOfferDialog card={card} onClose={onClose} />;
    case 'REQUEST_INFO':
      return <RequestInfoDialog card={card} onClose={onClose} />;
    case 'DECLINE':
      return <DeclineDialog card={card} onClose={onClose} />;
    case 'CONFIRM_DECISION':
      return (
        <CommentCommandDialog card={card} kind="CONFIRM_DECISION" onClose={onClose} title="Подтвердить решение (4 глаза)" submitLabel="Подтвердить" commentRequired={false}>
          <ProposalSummary card={card} />
        </CommentCommandDialog>
      );
    case 'RETURN_DECISION':
      return (
        <CommentCommandDialog card={card} kind="RETURN_DECISION" onClose={onClose} title="Вернуть решение андеррайтеру" submitLabel="Вернуть решение" commentRequired danger>
          <ProposalSummary card={card} />
        </CommentCommandDialog>
      );
    case 'RETRY_PROCESSING':
      return (
        <CommentCommandDialog card={card} kind="RETRY_PROCESSING" onClose={onClose} title="Повторить обработку" submitLabel="Повторить" commentRequired={false}>
          <KeyValue
            cols={2}
            items={[
              { label: 'Этап с ошибкой', value: card.processing.failed_stage ?? 'нет' },
              { label: 'Код ошибки', value: card.processing.last_error_code ?? 'нет' },
            ]}
          />
          <Text size="sm">Заявка вернется на этап с ошибкой, задача этапа выполнится снова. Ответы источников, полученные ранее, будут переиспользованы.</Text>
        </CommentCommandDialog>
      );
  }
}
