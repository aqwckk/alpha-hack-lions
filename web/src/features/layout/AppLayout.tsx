import { ActionIcon, Badge, Burger, Button, Drawer, Group, Menu, Stack, Text, UnstyledButton } from '@mantine/core';
import { IconChevronDown, IconLogout } from '@tabler/icons-react';
import { useEffect, useState } from 'react';
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { NotificationsBell } from './NotificationsBell';
import { useAuth, useUser } from '@/features/auth/AuthProvider';
import { useMeta } from '@/shared/api/queries';
import type { Role } from '@/shared/api/types';
import { ROLE_LABELS } from '@/shared/lib/labels';
import { NetworkBanner } from '@/shared/ui/components';

interface NavItem {
  to: string;
  label: string;
  roles: Role[];
  demoOnly?: boolean;
}

const NAV: NavItem[] = [
  { to: '/client/applications', label: 'Мои заявки', roles: ['CLIENT'] },
  { to: '/client/wizard', label: 'Подобрать кредит', roles: ['CLIENT'] },
  { to: '/bank/queue', label: 'Очередь', roles: ['UNDERWRITER', 'RISK_MANAGER'] },
  { to: '/bank/applications', label: 'Все заявки', roles: ['RISK_MANAGER'] },
  { to: '/bank/metrics', label: 'Метрики', roles: ['RISK_MANAGER'] },
  { to: '/bank/configs', label: 'Скоринг и политика', roles: ['UNDERWRITER', 'RISK_MANAGER'] },
  { to: '/bank/audit', label: 'Аудит', roles: ['RISK_MANAGER'] },
  { to: '/bank/demo', label: 'Демо-панель', roles: ['UNDERWRITER', 'RISK_MANAGER'], demoOnly: true },
];

export function AppLayout() {
  const user = useUser();
  const { logout } = useAuth();
  const meta = useMeta();
  const navigate = useNavigate();
  const [menuOpen, setMenuOpen] = useState(false);
  const { pathname } = useLocation();
  // A new screen starts at the top (the browser keeps the old scroll position in a SPA).
  useEffect(() => {
    window.scrollTo({ top: 0 });
  }, [pathname]);
  const items = NAV.filter((n) => n.roles.includes(user.role) && (!n.demoOnly || meta.data?.demo_mode));
  const workspace = user.role === 'CLIENT' ? 'Кредитный кабинет' : 'Рабочее место банка';

  const doLogout = async () => {
    await logout();
    navigate('/login', { replace: true });
  };

  const links = (onClick?: () => void) =>
    items.map((item) => (
      <NavLink key={item.to} to={item.to} onClick={onClick} className={({ isActive }) => (isActive ? 'active' : undefined)}>
        {item.label}
      </NavLink>
    ));

  return (
    <>
      <a href="#main" className="skip-link">
        Перейти к содержимому
      </a>
      <NetworkBanner />
      <header className="app-header">
        <div className="app-header-inner">
          <Burger opened={menuOpen} onClick={() => setMenuOpen(true)} className="show-mobile" size="sm" aria-label="Открыть меню" />
          <Link to={items[0]?.to ?? '/'} className="app-logo">
            <span className="app-logo-mark" aria-hidden>
              ₽
            </span>
            <span>{workspace}</span>
            <Badge size="xs" variant="outline" color="gray" className="hide-mobile">
              прототип
            </Badge>
          </Link>
          <nav className="app-nav app-nav-desktop" aria-label="Основное меню">
            {links()}
          </nav>
          <Group gap={6} wrap="nowrap" ml="auto">
            <NotificationsBell role={user.role} />
            <Menu position="bottom-end" width={240}>
              <Menu.Target>
                <UnstyledButton aria-label={`Профиль: ${user.full_name}`} className="hide-mobile">
                  <Group gap={6} wrap="nowrap">
                    <Stack gap={0} align="flex-end">
                      <Text size="sm" fw={600} lineClamp={1}>
                        {user.full_name}
                      </Text>
                      <Text size="xs" c="dimmed">
                        {ROLE_LABELS[user.role]}
                      </Text>
                    </Stack>
                    <IconChevronDown size={16} aria-hidden />
                  </Group>
                </UnstyledButton>
              </Menu.Target>
              <Menu.Dropdown>
                <Menu.Label>{user.login}</Menu.Label>
                <Menu.Item leftSection={<IconLogout size={16} aria-hidden />} onClick={() => void doLogout()}>
                  Выйти
                </Menu.Item>
              </Menu.Dropdown>
            </Menu>
            <ActionIcon variant="subtle" color="gray" className="show-mobile" onClick={() => void doLogout()} aria-label="Выйти">
              <IconLogout size={20} aria-hidden />
            </ActionIcon>
          </Group>
        </div>
      </header>
      <Drawer opened={menuOpen} onClose={() => setMenuOpen(false)} title={workspace} size="80%">
        <Stack gap="md">
          <Text size="sm" c="dimmed">
            {user.full_name}, {ROLE_LABELS[user.role]}
          </Text>
          <nav className="app-nav" aria-label="Меню" style={{ flexDirection: 'column' }}>
            {links(() => setMenuOpen(false))}
          </nav>
          <Button variant="default" leftSection={<IconLogout size={16} aria-hidden />} onClick={() => void doLogout()}>
            Выйти
          </Button>
        </Stack>
      </Drawer>
      <main className="app-main" id="main">
        <Outlet />
      </main>
      <footer className="app-footer">
        Прототип для хакатона на синтетических данных. Не является продуктом какого-либо банка. Уведомления и коды подтверждения
        показываются только здесь.
      </footer>
    </>
  );
}
