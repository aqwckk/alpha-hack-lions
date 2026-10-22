import { Button } from '@mantine/core';
import { Link } from 'react-router-dom';
import { EmptyState, PageHeader } from '@/shared/ui/components';

export function NotFoundPage() {
  return (
    <main className="app-main" id="main">
      <PageHeader title="Страница не найдена" />
      <EmptyState title="Такой страницы нет" text="Возможно, ссылка устарела. Вернитесь на главную." action={<Button component={Link} to="/">На главную</Button>} />
    </main>
  );
}
