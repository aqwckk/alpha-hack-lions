import { Center, Loader } from '@mantine/core';
import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { homeFor, useAuth } from './AuthProvider';
import type { Role } from '@/shared/api/types';

/** Route guard for UX only: the backend checks the role on every request. */
export function RequireRole({ roles }: { roles: Role[] }) {
  const { state } = useAuth();
  const location = useLocation();
  if (state.status === 'loading') {
    return (
      <Center h="60vh" role="status" aria-label="Проверяем сессию">
        <Loader />
      </Center>
    );
  }
  if (state.status === 'anonymous') {
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  }
  if (!roles.includes(state.user.role)) {
    return <Navigate to={homeFor(state.user.role)} replace />;
  }
  return <Outlet />;
}

export function RoleHome() {
  const { state } = useAuth();
  if (state.status === 'loading') {
    return (
      <Center h="60vh" role="status" aria-label="Проверяем сессию">
        <Loader />
      </Center>
    );
  }
  if (state.status === 'anonymous') return <Navigate to="/login" replace />;
  return <Navigate to={homeFor(state.user.role)} replace />;
}
