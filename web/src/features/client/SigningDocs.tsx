import { Button, Group, Modal, Stack, Text } from '@mantine/core';
import { IconFileText } from '@tabler/icons-react';
import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { api } from '@/shared/api/endpoints';
import type { SigningView } from '@/shared/api/types';
import { ErrorState, PageSkeleton } from '@/shared/ui/components';

function DocumentText({ appId, docId }: { appId: string; docId: string }) {
  const query = useQuery({ queryKey: ['client', 'signing-doc', appId, docId], queryFn: () => api.signingDocument(appId, docId), staleTime: Infinity });
  if (query.isPending) return <PageSkeleton lines={2} />;
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  return <div className="doc-text" tabIndex={0} aria-label="Текст документа">{query.data}</div>;
}

/** Signing package documents with a reader (text from the EDO simulator). */
export function SigningDocs({ appId, signing }: { appId: string; signing: SigningView }) {
  const [openDoc, setOpenDoc] = useState<{ id: string; title: string } | null>(null);
  return (
    <>
      <Stack gap={6} component="ul" style={{ listStyle: 'none', padding: 0, margin: 0 }}>
        {signing.documents.map((d) => (
          <Group key={d.id} component="li" justify="space-between" wrap="nowrap" p="sm" style={{ border: '1px solid var(--app-border)', borderRadius: 10 }}>
            <Group gap="xs" wrap="nowrap">
              <IconFileText size={20} aria-hidden />
              <Text size="sm" fw={600}>
                {d.title}
              </Text>
            </Group>
            <Button
              variant="light"
              size="xs"
              onClick={() => {
                setOpenDoc({ id: d.id, title: d.title });
              }}
              aria-label={`Открыть: ${d.title}`}
            >
              Открыть
            </Button>
          </Group>
        ))}
      </Stack>
      <Modal opened={openDoc !== null} onClose={() => setOpenDoc(null)} title={openDoc?.title ?? ''} size="xl">
        {openDoc && <DocumentText appId={appId} docId={openDoc.id} />}
        <Text size="xs" c="dimmed" mt="sm">
          Договор {signing.contract_number}. Документ сформирован симулятором ЭДО на синтетических данных.
        </Text>
      </Modal>
    </>
  );
}
