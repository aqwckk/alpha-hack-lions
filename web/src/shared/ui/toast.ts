import { notifications } from '@mantine/notifications';
import { errorMessage, errorReference } from '@/shared/api/errors';

export const toast = {
  success(message: string, title?: string): void {
    notifications.show({ color: 'green', title, message, autoClose: 5000 });
  },
  info(message: string, title?: string): void {
    notifications.show({ color: 'blue', title, message, autoClose: 6000 });
  },
  warning(message: string, title?: string): void {
    notifications.show({ color: 'orange', title, message, autoClose: 8000 });
  },
  error(error: unknown, title = 'Не получилось'): void {
    const ref = errorReference(error);
    notifications.show({ color: 'red', title, message: ref ? `${errorMessage(error)}. ${ref}` : errorMessage(error), autoClose: 10000 });
  },
};
