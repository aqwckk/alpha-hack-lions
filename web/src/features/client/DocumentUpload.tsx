import { ActionIcon, Button, FileButton, Group, Stack, Text } from '@mantine/core';
import { IconDownload, IconFile, IconTrash, IconUpload } from '@tabler/icons-react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { withFreshVersion } from '@/shared/api/commands';
import { api, openProtectedFile } from '@/shared/api/endpoints';
import { errorMessage } from '@/shared/api/errors';
import { storeApplication } from '@/shared/api/queries';
import type { DocumentInfo } from '@/shared/api/types';
import { formatFileSize } from '@/shared/lib/format';
import { toast } from '@/shared/ui/toast';

const MAX_BYTES = 10 * 1024 * 1024;
const ALLOWED = ['application/pdf', 'image/jpeg', 'image/png'];

/** Advisory checks only: the server validates size and the real file signature. */
export function localFileError(file: File): string | null {
  if (file.size > MAX_BYTES) return 'Файл больше 10 МБ. Сожмите его или разделите на части';
  if (file.type && !ALLOWED.includes(file.type)) return 'Можно загрузить PDF, JPG или PNG';
  return null;
}

export function DocumentUpload({
  appId,
  documentType,
  infoRequestItemId,
  label = 'Загрузить файл',
}: {
  appId: string;
  documentType: string;
  infoRequestItemId?: string;
  label?: string;
}) {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const upload = useMutation({
    mutationFn: (file: File) =>
      withFreshVersion(queryClient, appId, (version) =>
        api.uploadDocument(appId, { documentType, file, version, ...(infoRequestItemId ? { infoRequestItemId } : {}) }),
      ),
    onSuccess: (app) => {
      setError(null);
      storeApplication(queryClient, app);
      toast.success('Файл загружен');
    },
    onError: (e) => setError(errorMessage(e) || 'Не удалось загрузить файл, попробуйте еще раз'),
  });

  const onFile = (file: File | null) => {
    if (!file) return;
    const local = localFileError(file);
    if (local) {
      setError(local);
      return;
    }
    upload.mutate(file);
  };

  return (
    <Stack gap={4}>
      <Group gap="sm">
        <FileButton onChange={onFile} accept="application/pdf,image/jpeg,image/png">
          {(props) => (
            <Button {...props} variant="light" leftSection={<IconUpload size={16} aria-hidden />} loading={upload.isPending}>
              {label}
            </Button>
          )}
        </FileButton>
        <Text size="xs" c="dimmed">
          PDF, JPG или PNG, до 10 МБ
        </Text>
      </Group>
      {error && (
        <Text size="sm" c="red.8" role="alert">
          {error}
        </Text>
      )}
    </Stack>
  );
}

export function DocumentList({ appId, documents, canDelete }: { appId: string; documents: DocumentInfo[]; canDelete: boolean }) {
  const queryClient = useQueryClient();
  const remove = useMutation({
    mutationFn: (docId: string) => withFreshVersion(queryClient, appId, (version) => api.deleteDocument(appId, docId, version)),
    onSuccess: (app) => storeApplication(queryClient, app),
    onError: (e) => toast.error(e, 'Не удалось удалить файл'),
  });
  if (documents.length === 0) return null;
  return (
    <Stack gap={6} component="ul" style={{ listStyle: 'none', padding: 0, margin: 0 }}>
      {documents.map((d) => (
        <Group key={d.id} component="li" justify="space-between" wrap="nowrap" gap="xs" p="xs" style={{ border: '1px solid var(--app-border)', borderRadius: 10 }}>
          <Group gap="xs" wrap="nowrap" style={{ minWidth: 0 }}>
            <IconFile size={18} aria-hidden />
            <div style={{ minWidth: 0 }}>
              <Text size="sm" fw={600} truncate>
                {d.file_name}
              </Text>
              <Text size="xs" c="dimmed">
                {d.document_title}, {formatFileSize(d.size_bytes)}
              </Text>
            </div>
          </Group>
          <Group gap={4} wrap="nowrap">
            <ActionIcon
              variant="subtle"
              color="gray"
              aria-label={`Скачать ${d.file_name}`}
              onClick={() => void openProtectedFile(() => api.clientDocument(appId, d.id), d.file_name).catch((e: unknown) => toast.error(e))}
            >
              <IconDownload size={18} aria-hidden />
            </ActionIcon>
            {canDelete && (
              <ActionIcon variant="subtle" color="red" aria-label={`Удалить ${d.file_name}`} onClick={() => remove.mutate(d.id)} loading={remove.isPending && remove.variables === d.id}>
                <IconTrash size={18} aria-hidden />
              </ActionIcon>
            )}
          </Group>
        </Group>
      ))}
    </Stack>
  );
}
