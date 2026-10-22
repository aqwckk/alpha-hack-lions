import {
  Alert,
  Anchor,
  Badge,
  Button,
  Group,
  Modal,
  Paper,
  Skeleton,
  Stack,
  Text,
  ThemeIcon,
  Title,
} from '@mantine/core';
import {
  IconAlertTriangle,
  IconCircleCheck,
  IconCircleX,
  IconClockHour4,
  IconFileText,
  IconHourglassHigh,
  IconLoader2,
  IconLock,
  IconPencil,
  IconSearch,
  IconSend,
  IconSignature,
  IconUserSearch,
  IconWifiOff,
  IconCash,
} from '@tabler/icons-react';
import { useEffect, useRef, useSyncExternalStore, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { connectivity } from '@/shared/api/client';
import { errorMessage, errorReference, isApiError } from '@/shared/api/errors';
import { clientStatusMeta, internalStatus, type Tone } from '@/shared/lib/labels';

const CLIENT_ICONS: Record<string, typeof IconPencil> = {
  FILLING: IconPencil,
  SENT: IconSend,
  CHECKING: IconSearch,
  ACTION_REQUIRED: IconAlertTriangle,
  SPECIALIST_REVIEW: IconUserSearch,
  DECISION_READY: IconFileText,
  DOCUMENTS: IconSignature,
  PAYOUT: IconCash,
  COMPLETED: IconCircleCheck,
  REJECTED: IconCircleX,
  WITHDRAWN: IconLock,
  EXPIRED: IconHourglassHigh,
};

export function clientStatusIcon(status: string) {
  return CLIENT_ICONS[status] ?? IconClockHour4;
}

/** Status is never conveyed by color alone: icon + text. */
export function ClientStatusBadge({ status, title }: { status: string; title?: string | null }) {
  const meta = clientStatusMeta(status);
  const Icon = clientStatusIcon(status);
  return (
    <Badge color={meta.tone} variant="light" size="lg" radius="sm" leftSection={<Icon size={14} aria-hidden />} className="status-badge">
      {title ?? meta.label}
    </Badge>
  );
}

export function InternalStatusBadge({ status }: { status: string }) {
  const meta = internalStatus(status);
  return (
    <Badge
      color={meta.tone}
      variant="light"
      radius="sm"
      className="status-badge"
      styles={{ root: { height: 'auto', paddingBlock: 3, maxWidth: '100%' }, label: { whiteSpace: 'normal', overflow: 'visible' } }}
    >
      {meta.label}
    </Badge>
  );
}

export function ToneIcon({ tone, children }: { tone: Tone; children: ReactNode }) {
  return (
    <ThemeIcon color={tone} variant="light" size={44} radius="md" aria-hidden>
      {children}
    </ThemeIcon>
  );
}

/** Page title: sets document.title and moves focus to the heading after navigation. */
export function PageHeader({
  title,
  subtitle,
  back,
  actions,
  focus = true,
}: {
  title: string;
  subtitle?: ReactNode;
  back?: { to: string; label: string };
  actions?: ReactNode;
  focus?: boolean;
}) {
  const ref = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    document.title = `${title} | Кредитный кабинет`;
    if (focus) ref.current?.focus({ preventScroll: true });
  }, [title, focus]);
  return (
    <Stack gap={4} mb="lg">
      {back && (
        <Anchor component={Link} to={back.to} size="sm" className="back-link">
          ← {back.label}
        </Anchor>
      )}
      <Group justify="space-between" align="flex-start" wrap="wrap" gap="sm">
        <Stack gap={4} style={{ minWidth: 0, flex: '1 1 320px' }}>
          <Title order={1} ref={ref} tabIndex={-1} className="page-title">
            {title}
          </Title>
          {subtitle && (
            <Text c="dimmed" size="md">
              {subtitle}
            </Text>
          )}
        </Stack>
        {actions && <Group gap="sm">{actions}</Group>}
      </Group>
    </Stack>
  );
}

export function SectionCard({ title, children, actions, id }: { title?: ReactNode; children: ReactNode; actions?: ReactNode; id?: string }) {
  return (
    <Paper withBorder radius="lg" p={{ base: 'md', sm: 'lg' }} className="section-card" id={id}>
      {(title || actions) && (
        <Group justify="space-between" mb="md" gap="xs" wrap="wrap">
          {title && (
            <Title order={2} size="h4">
              {title}
            </Title>
          )}
          {actions}
        </Group>
      )}
      {children}
    </Paper>
  );
}

/** Definition list: label/value pairs, semantic for screen readers. */
export function KeyValue({ items, cols = 2 }: { items: { label: ReactNode; value: ReactNode; hidden?: boolean }[]; cols?: 1 | 2 | 3 }) {
  return (
    <dl className={`kv kv-${cols}`}>
      {items
        .filter((i) => !i.hidden)
        .map((item, idx) => (
          <div className="kv-row" key={idx}>
            <dt>{item.label}</dt>
            <dd>{item.value}</dd>
          </div>
        ))}
    </dl>
  );
}

export function PageSkeleton({ lines = 4 }: { lines?: number }) {
  return (
    <Stack gap="md" aria-busy="true" aria-live="polite">
      <Text className="visually-hidden">Загрузка...</Text>
      <Skeleton height={36} width="60%" radius="md" />
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton key={i} height={i === 0 ? 140 : 72} radius="lg" />
      ))}
    </Stack>
  );
}

/** Error state with the right meaning for 403/404 and a retry for everything else. */
export function ErrorState({ error, onRetry, notFoundText }: { error: unknown; onRetry?: () => void; notFoundText?: string }) {
  const notFound = isApiError(error) && (error.kind === 'not_found' || error.kind === 'forbidden');
  const ref = errorReference(error);
  return (
    <Alert
      color={notFound ? 'gray' : 'red'}
      variant="light"
      radius="lg"
      icon={notFound ? <IconLock aria-hidden /> : <IconAlertTriangle aria-hidden />}
      title={notFound ? (notFoundText ?? 'Не найдено или у вас нет доступа') : 'Не удалось загрузить данные'}
      role="alert"
    >
      <Stack gap="xs">
        {!notFound && <Text size="sm">{errorMessage(error)}</Text>}
        {ref && (
          <Text size="xs" c="dimmed">
            {ref}
          </Text>
        )}
        {onRetry && !notFound && (
          <Group>
            <Button size="xs" variant="light" onClick={onRetry}>
              Повторить
            </Button>
          </Group>
        )}
      </Stack>
    </Alert>
  );
}

export function EmptyState({ title, text, action, icon }: { title: string; text?: ReactNode; action?: ReactNode; icon?: ReactNode }) {
  return (
    <Paper withBorder radius="lg" p="xl" className="empty-state">
      <Stack align="center" gap="sm" ta="center">
        {icon}
        <Title order={2} size="h4">
          {title}
        </Title>
        {text && (
          <Text c="dimmed" maw={520}>
            {text}
          </Text>
        )}
        {action}
      </Stack>
    </Paper>
  );
}

export function ConfirmModal({
  opened,
  onClose,
  onConfirm,
  title,
  children,
  confirmLabel,
  danger,
  loading,
}: {
  opened: boolean;
  onClose: () => void;
  onConfirm: () => void;
  title: string;
  children: ReactNode;
  confirmLabel: string;
  danger?: boolean;
  loading?: boolean;
}) {
  return (
    <Modal opened={opened} onClose={onClose} title={title} centered radius="lg">
      <Stack gap="md">
        <div>{children}</div>
        <Group justify="flex-end" gap="sm">
          {/* The safe action gets focus first: destructive confirmation is never the default. */}
          <Button variant="default" onClick={onClose} data-autofocus>
            Отмена
          </Button>
          <Button color={danger ? 'red' : undefined} onClick={onConfirm} loading={loading}>
            {confirmLabel}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

export function NetworkBanner() {
  const offline = useSyncExternalStore(connectivity.subscribe, connectivity.isOffline, connectivity.isOffline);
  if (!offline) return null;
  return (
    <Alert color="orange" radius={0} icon={<IconWifiOff aria-hidden />} role="status" className="network-banner">
      Нет связи с сервером, повторяем...
    </Alert>
  );
}

export function Spinner({ label }: { label: string }) {
  return (
    <Group gap="xs" role="status">
      <IconLoader2 className="spin" size={18} aria-hidden />
      <Text size="sm">{label}</Text>
    </Group>
  );
}
