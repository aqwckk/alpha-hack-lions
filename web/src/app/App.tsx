import { MantineProvider } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { QueryClientProvider } from '@tanstack/react-query';
import { lazy, Suspense, useState, type ReactNode } from 'react';
import { createBrowserRouter, Navigate, Route, RouterProvider, Routes } from 'react-router-dom';
import { NotFoundPage } from './NotFoundPage';
import { createQueryClient } from './queryClient';
import { theme } from './theme';
import { AuthProvider } from '@/features/auth/AuthProvider';
import { LoginPage } from '@/features/auth/LoginPage';
import { RequireRole, RoleHome } from '@/features/auth/RequireRole';
import { ApplicationPage } from '@/features/client/ApplicationPage';
import { ApplicationsListPage } from '@/features/client/ApplicationsListPage';
import { ApplicationFormPage } from '@/features/client/form/ApplicationFormPage';
import { InfoRequestPage } from '@/features/client/InfoRequestPage';
import { OfferPage } from '@/features/client/OfferPage';
import { SigningPage } from '@/features/client/SigningPage';
import { WizardPage } from '@/features/client/WizardPage';
import { WizardResultsPage } from '@/features/client/WizardResultsPage';
import { AppLayout } from '@/features/layout/AppLayout';
import { PageSkeleton } from '@/shared/ui/components';

// The bank workplace and risk screens are separate chunks: clients never download them (or the charts library).
const QueuePage = lazy(() => import('@/features/bank/QueuePage').then((m) => ({ default: m.QueuePage })));
const CardPage = lazy(() => import('@/features/bank/CardPage').then((m) => ({ default: m.CardPage })));
const MetricsPage = lazy(() => import('@/features/risk/MetricsPage'));
const ConfigsPage = lazy(() => import('@/features/risk/ConfigsPage'));
const AuditPage = lazy(() => import('@/features/risk/AuditPage'));
const DemoPanelPage = lazy(() => import('@/features/demo/DemoPanelPage'));

function Lazy({ children }: { children: ReactNode }) {
  return <Suspense fallback={<PageSkeleton lines={3} />}>{children}</Suspense>;
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<RoleHome />} />
      <Route path="/login" element={<LoginPage />} />
      <Route element={<RequireRole roles={['CLIENT']} />}>
        <Route element={<AppLayout />}>
          <Route path="/client" element={<Navigate to="/client/applications" replace />} />
          <Route path="/client/applications" element={<ApplicationsListPage />} />
          <Route path="/client/wizard" element={<WizardPage />} />
          <Route path="/client/wizard/results" element={<WizardResultsPage />} />
          <Route path="/client/applications/:id" element={<ApplicationPage />} />
          <Route path="/client/applications/:id/edit" element={<ApplicationFormPage />} />
          <Route path="/client/applications/:id/edit/:step" element={<ApplicationFormPage />} />
          <Route path="/client/applications/:id/info-request" element={<InfoRequestPage />} />
          <Route path="/client/applications/:id/offer" element={<OfferPage />} />
          <Route path="/client/applications/:id/signing" element={<SigningPage />} />
        </Route>
      </Route>
      <Route element={<RequireRole roles={['UNDERWRITER', 'RISK_MANAGER']} />}>
        <Route element={<AppLayout />}>
          <Route path="/bank" element={<Navigate to="/bank/queue" replace />} />
          <Route path="/bank/queue" element={<Lazy><QueuePage /></Lazy>} />
          <Route path="/bank/applications/:id" element={<Lazy><CardPage /></Lazy>} />
          <Route path="/bank/configs" element={<Lazy><ConfigsPage /></Lazy>} />
          <Route path="/bank/demo" element={<Lazy><DemoPanelPage /></Lazy>} />
        </Route>
      </Route>
      <Route element={<RequireRole roles={['RISK_MANAGER']} />}>
        <Route element={<AppLayout />}>
          <Route path="/bank/applications" element={<Lazy><QueuePage defaultTab="all" /></Lazy>} />
          <Route path="/bank/metrics" element={<Lazy><MetricsPage /></Lazy>} />
          <Route path="/bank/audit" element={<Lazy><AuditPage /></Lazy>} />
        </Route>
      </Route>
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}

const router = createBrowserRouter([{ path: '*', element: <AuthProvider><AppRoutes /></AuthProvider> }]);

export function App() {
  const [queryClient] = useState(createQueryClient);
  return (
    <MantineProvider theme={theme} forceColorScheme="light">
      <Notifications position="top-right" zIndex={1000} limit={4} />
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </MantineProvider>
  );
}
