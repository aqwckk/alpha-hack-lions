import { Alert, Badge, Group, Paper, Select, Stack, Text, Title } from '@mantine/core';
import { IconAlertTriangle, IconCircleCheck, IconInfoCircle } from '@tabler/icons-react';
import { useState } from 'react';
import { DocumentList, DocumentUpload } from '@/features/client/DocumentUpload';
import { useDictionaries } from '@/shared/api/queries';
import type { ClientApplication } from '@/shared/api/types';
import { SectionCard } from '@/shared/ui/components';

export function StepDocuments({ app }: { app: ClientApplication }) {
  const dictionaries = useDictionaries();
  const [otherType, setOtherType] = useState<string | null>(null);
  const canUpload = app.available_actions.includes('UPLOAD_DOCUMENT');
  const canDelete = app.available_actions.includes('DELETE_DOCUMENT');
  const required = app.required_documents;
  const requiredTypes = new Set(required.map((d) => d.document_type));
  const missing = required.filter((d) => !d.uploaded);
  const others = app.documents.filter((d) => !requiredTypes.has(d.document_type));

  return (
    <Stack gap="lg">
      {required.length === 0 ? (
        <Alert color="green" variant="light" radius="lg" icon={<IconCircleCheck aria-hidden />} title="Для этого кредита документы не нужны">
          Сведения о бизнесе банк получит сам из госреестров, налоговой и бюро кредитных историй. Можно переходить к отправке.
        </Alert>
      ) : (
        <SectionCard title="Нужные документы">
          <Stack gap="md">
            {required.map((doc) => (
              <Paper key={doc.document_type} withBorder radius="md" p="md">
                <Stack gap="sm">
                  <Group justify="space-between" wrap="wrap" gap="xs">
                    <Title order={3} size="h5">
                      {doc.title}
                    </Title>
                    {doc.uploaded ? (
                      <Badge color="green" variant="light" leftSection={<IconCircleCheck size={12} aria-hidden />}>
                        Загружен
                      </Badge>
                    ) : (
                      <Badge color="orange" variant="light" leftSection={<IconAlertTriangle size={12} aria-hidden />}>
                        Нужно загрузить
                      </Badge>
                    )}
                  </Group>
                  <Text size="sm" c="dimmed">
                    Зачем: {doc.purpose}
                  </Text>
                  <DocumentList appId={app.id} documents={app.documents.filter((d) => d.document_type === doc.document_type)} canDelete={canDelete} />
                  {canUpload && <DocumentUpload appId={app.id} documentType={doc.document_type} label={doc.uploaded ? 'Добавить еще файл' : 'Загрузить файл'} />}
                </Stack>
              </Paper>
            ))}
            {missing.length > 0 && (
              <Alert color="yellow" icon={<IconAlertTriangle aria-hidden />} radius="md">
                Без этих документов рассмотрение начнется только после их загрузки. Банк попросит их в кабинете.
              </Alert>
            )}
          </Stack>
        </SectionCard>
      )}

      <SectionCard title="Другие документы">
        <Stack gap="sm">
          <Text size="sm" c="dimmed">
            Необязательно. Например, контракт с заказчиком или выписка по счету в другом банке.
          </Text>
          <DocumentList appId={app.id} documents={others} canDelete={canDelete} />
          {canUpload && (
            <Group align="flex-end" gap="sm" wrap="wrap">
              <Select
                label="Тип документа"
                placeholder="Выберите"
                data={(dictionaries.data?.document_types ?? []).filter((t) => !requiredTypes.has(t.code)).map((t) => ({ value: t.code, label: t.title }))}
                value={otherType}
                onChange={setOtherType}
                w={340}
                maw="100%"
              />
              {otherType && <DocumentUpload appId={app.id} documentType={otherType} />}
            </Group>
          )}
          <Group gap={6}>
            <IconInfoCircle size={14} aria-hidden />
            <Text size="xs" c="dimmed">
              Файлы хранятся в кабинете и доступны только вам и сотрудникам банка, которые рассматривают заявку.
            </Text>
          </Group>
        </Stack>
      </SectionCard>
    </Stack>
  );
}
