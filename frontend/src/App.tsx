/**
 * App — root React component.
 *
 * Sets up browser routing, React Query cache provider, and authentication
 * context. Lazy-loads page components for code-splitting.
 */
import React, { Suspense, useState, useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate, useParams, useNavigate, useLocation } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ConfigProvider } from 'antd';
import { forestApi } from './services/api';
import { AuthProvider } from './contexts/AuthContext';
import { BoundaryPreviewProvider } from './contexts/BoundaryPreviewContext';
import ProtectedRoute from './components/ProtectedRoute';
import { FocusModeClassManager } from './components/FocusModeClassManager';
import { FocusModeExitButton } from './components/FocusModeExitButton';
import Layout from './components/Layout';
import ChatDock from './features/chat/ChatDock';
import { useAntdLocale } from './i18n/LocaleSync';
import { useResourceLoading } from './hooks/usePerformance';
import './utils/chartSetup';
import { toSurfaceId } from './lib/calcSurface';

const Login = React.lazy(() => import('./pages/Login'));
const ForumShell = React.lazy(() => import('./features/forum/ForumShell'));
const ForumListPage = React.lazy(() => import('./features/forum/ForumListPage'));
const ForumQuestionPage = React.lazy(() => import('./features/forum/ForumQuestionPage'));
const ForumAskPage = React.lazy(() => import('./features/forum/ForumAskPage'));
const ForumProfilePage = React.lazy(() => import('./features/forum/ForumProfilePage'));
const ForumModerationPage = React.lazy(() => import('./features/forum/ForumModerationPage'));
const ForumSettingsPage = React.lazy(() => import('./features/forum/ForumSettingsPage'));
const Register = React.lazy(() => import('./pages/Register'));
const ForgotPassword = React.lazy(() => import('./pages/ForgotPassword'));
const ResetPassword = React.lazy(() => import('./pages/ResetPassword'));
const VerifyEmail = React.lazy(() => import('./pages/VerifyEmail'));
const CompleteProfile = React.lazy(() => import('./pages/CompleteProfile'));
const MyUploads = React.lazy(() => import('./pages/MyUploads'));
const CalculationDetailTabbed = React.lazy(() => import('./pages/CalculationDetailTabbed'));
const BlockNaming = React.lazy(() => import('./pages/BlockNaming'));
const CacheManagementPanel = React.lazy(() => import('./components/CacheManagementPanel'));
const DraftResume = React.lazy(() => import('./pages/DraftResume'));
const YearlyActivitiesPage = React.lazy(() => import('./components/YearlyActivities/YearlyActivitiesPage'));
const TemplateDesignerPage = React.lazy(() => import('./pages/TemplateDesignerPage'));
const TemplatesLandingPage = React.lazy(() => import('./pages/TemplatesLandingPage'));
const MapVariablesPage = React.lazy(() => import('./pages/MapVariablesPage'));
const HazardVariablesPage = React.lazy(() => import('./pages/HazardVariablesPage'));
const SfmVariablesPage = React.lazy(() => import('./pages/SfmVariablesPage'));
const AdminTranslationsPage = React.lazy(() => import('./pages/AdminTranslationsPage'));
const AdminCostsPage = React.lazy(() => import('./pages/AdminCostsPage'));
const OrganizationPage = React.lazy(() => import('./pages/OrganizationPage'));
const AdminUsersPage = React.lazy(() => import('./pages/AdminUsersPage'));
const AdminChatPage = React.lazy(() => import('./pages/AdminChatPage'));
const AdminSoilErosionProfilesPage = React.lazy(() => import('./pages/AdminSoilErosionProfilesPage'));
const AdminHazardVulnProfilesPage = React.lazy(() => import('./pages/AdminHazardVulnProfilesPage'));
const AdminSfmProfilesPage = React.lazy(() => import('./pages/AdminSfmProfilesPage'));
const AdminSfmPrescriptionsPage = React.lazy(() => import('./pages/AdminSfmPrescriptionsPage'));
const AdminCbaRatesPage = React.lazy(() => import('./pages/AdminCbaRatesPage'));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5 * 60 * 1000,
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

const LoadingFallback = () => (
  <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}>
    <div style={{ textAlign: 'center' }}>
      <div style={{ fontSize: '1.2rem', color: '#666' }}>Loading...</div>
    </div>
  </div>
);

/**
 * Phase 8 — global slow-resource watcher (PerformanceObserver). Mounted once
 * under the router; renders nothing.
 */
const PerformanceMonitor: React.FC = () => {
  useResourceLoading();
  return null;
};

/**
 * Single Workspace (A4/A5b) — `/calculations/:id` is the one shell. The old
 * `/tabbed` and standalone `/operational-plan` URLs now always redirect into it.
 */
const TabbedRoute = () => {
  const { id } = useParams<{ id: string }>();
  const location = useLocation();
  return <Navigate to={`/calculations/${id}${location.search}`} replace />;
};

/**
 * `/calculations/:id/yearly-activities` — the standalone yearly-activities page. The page needs the
 * calculation id (and shows the forest's name and area), which the bare route never passed: it opened as an
 * empty shell with nothing to plan.
 */
const YearlyActivitiesRoute = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [forest, setForest] = useState<{ name?: string; area?: number }>({});

  useEffect(() => {
    if (!id) return undefined;
    let cancelled = false;
    forestApi
      .getCalculation(id)
      .then((calc) => {
        if (cancelled) return;
        const data = (calc.result_data ?? {}) as { area_hectares?: number | string };
        setForest({ name: calc.forest_name, area: Number(data.area_hectares) || undefined });
      })
      .catch(() => {
        /* the page still works without the name and area; they are only shown in its header */
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  if (!id) return <Navigate to="/my-uploads" replace />;
  return (
    <YearlyActivitiesPage
      calculationId={id}
      forestName={forest.name}
      area={forest.area}
      onClose={() => navigate(`/calculations/${id}`)}
    />
  );
};

const OperationalPlanRoute = () => {
  const { id } = useParams<{ id: string }>();
  return (
    <Navigate
      to={`/calculations/${id}?surface=${toSurfaceId('plan', 'mgmtplan')}`}
      replace
    />
  );
};

/**
 * Phase 7 — legacy calculation-workspace URL → canonical target.
 * Uses a params-aware wrapper (react-router v7 `<Navigate to>` accepts only a
 * static `To`, not a function).
 * Updated Phase 14: targets new 4-tab architecture with forest-data default.
 */
const LegacyCalcWorkspaceRedirect = () => {
  const location = useLocation();
  const { id } = useParams<{ id: string }>();

  // Preserve context param (e.g., ?context=block_naming)
  const params = new URLSearchParams(location.search);
  const context = params.get('context') || 'unified';
  const to = `/calculations/${id}?surface=${toSurfaceId('base', context)}`;

  useEffect(() => {
    const gtag = (window as any).gtag;
    if (typeof gtag === 'function') {
      gtag('event', 'legacy_redirect', { from_path: location.pathname, to_path: to });
    }
  }, [location.pathname, to]);

  return <Navigate to={to} replace />;
};

/**
 * Phase 0 — Legacy Workspace redirect.
 * Forwards old /workspace/:id URLs to the canonical tabbed route
 * /calculations/:id/tabbed?tab=forest-data&context=..., preserving any safe query params and
 * logging the hit to GA4 (gtag) so the legacy route can be retired later.
 */
const LegacyWorkspaceRedirect = () => {
  const location = useLocation();

  // Preserve context param (e.g., ?context=block_naming)
  const params = new URLSearchParams(location.search);
  const context = params.get('context') || 'unified';

  const id = location.pathname.split('/')[2];
  const to = `/calculations/${id}?surface=${toSurfaceId('base', context)}`;

  useEffect(() => {
    // Track how long legacy routes are hit before retiring them
    const gtag = (window as any).gtag;
    if (typeof gtag === 'function') {
      gtag('event', 'legacy_redirect', { from_path: location.pathname, to_path: to });
    }
  }, [location.pathname, to]);

  return <Navigate to={to} replace />;
};

const App: React.FC = () => {
  const antdLocale = useAntdLocale();

  // H3.8 — DEV-only crash hook, so the root ErrorBoundary can actually be
  // tested. `__crashWorkspace` (WorkspaceTab) proves tab-level isolation; this
  // proves the boundary of last resort, which by definition nothing else can
  // trigger on purpose. URL-driven rather than console-driven (`?__crash=1`)
  // because the person verifying it is not necessarily at a devtools prompt.
  // import.meta.env.DEV is compile-time, so this whole block is dropped from
  // production bundles by dead-code elimination — it cannot fire for a user.
  if (import.meta.env.DEV) {
    const forced =
      new URLSearchParams(window.location.search).has('__crash') ||
      (window as unknown as { __crashApp?: boolean }).__crashApp;
    if (forced) {
      throw new Error('DEV crash hook: forced root render failure (H3.8)');
    }
  }

  return (
<QueryClientProvider client={queryClient}>
    <AuthProvider>
      <BoundaryPreviewProvider>
      <ConfigProvider locale={antdLocale}>
      <BrowserRouter>
        <Suspense fallback={<LoadingFallback />}>
          <FocusModeClassManager />
          <FocusModeExitButton />
          <ChatDock />
          <PerformanceMonitor />
          <Routes>
            {/* Public routes */}
            <Route path="/login" element={<Login />} />
            <Route path="/register" element={<Register />} />
            <Route path="/forgot-password" element={<ForgotPassword />} />
            <Route path="/reset-password" element={<ResetPassword />} />
            <Route path="/verify-email" element={<VerifyEmail />} />
            {/* Community forum: readable without an account (owner, 2026-10-27); asking, answering and voting sign in first */}
            <Route path="/forum" element={<ForumShell />}>
              <Route index element={<ForumListPage />} />
              <Route path="ask" element={<ForumAskPage />} />
              <Route path="q/:id" element={<ForumQuestionPage />} />
              <Route path="users/:id" element={<ForumProfilePage />} />
              <Route path="me" element={<ForumProfilePage self />} />
              <Route path="moderation" element={<ForumModerationPage />} />
              <Route path="settings" element={<ForumSettingsPage />} />
            </Route>
            <Route
              path="/complete-profile"
              element={
                <ProtectedRoute allowIncompleteProfile>
                  <CompleteProfile />
                </ProtectedRoute>
              }
            />

            {/* Protected routes */}
            <Route
              path="/"
              element={
                <ProtectedRoute>
                  <Layout />
                </ProtectedRoute>
              }
            >
              {/* Default route - redirect to My CFOPs */}
              <Route index element={<Navigate to="/my-uploads" replace />} />

              {/* Main routes */}
              <Route path="my-uploads" element={<MyUploads />} />
              <Route path="upload" element={<Navigate to="/my-uploads" replace />} />
              <Route path="drafts/:draftId/resume" element={<DraftResume />} />
              <Route path="calculations/:id" element={<CalculationDetailTabbed />} />
              <Route path="calculations/:id/tabbed" element={<TabbedRoute />} />
              <Route path="calculations/:id/block-naming" element={<BlockNaming />} />
              {/* One workspace address: /calculations/:id (+ ?surface=group/context). The older addresses below redirect to it. */}
              <Route path="calculations/:id/unified" element={<LegacyCalcWorkspaceRedirect />} />
              <Route path="calculations/:id/yearly-activities" element={<YearlyActivitiesRoute />} />
              <Route path="workspace/:id" element={<LegacyWorkspaceRedirect />} />
              <Route path="calculations/:id/map" element={<LegacyCalcWorkspaceRedirect />} />
              <Route path="calculations/:id/operational-plan" element={<OperationalPlanRoute />} />
              {/* Phase 0/7: legacy calculation workspace URL → canonical tabbed page target */}
              <Route
                path="calculations/:id/workspace"
                element={<LegacyCalcWorkspaceRedirect />}
              />
              <Route path="forests" element={<MyUploads />} />
              <Route path="forests/:id" element={<MyUploads />} />

              {/* The old stand-alone inventory pages were removed (2026-10-17): Tree Mapping, a step of each forest, does the same. */}
              <Route path="inventory/*" element={<Navigate to="/my-uploads" replace />} />

              {/* Template routes — one landing page with Browse & Use / Manage
                  tabs (OP_TEMPLATE_MANAGEMENT_PLAN.md T5). Old URLs redirect. */}
              <Route path="templates" element={<TemplatesLandingPage />} />
              <Route path="templates/mine" element={
                <Navigate to="/templates?tab=manage&sub=mine" replace />
              } />
              <Route path="templates/map-variables" element={
                <ProtectedRoute allowedRoles={['super_admin', 'template_designer']}>
                  <MapVariablesPage />
                </ProtectedRoute>
              } />
              <Route path="templates/hazard-variables" element={
                <ProtectedRoute allowedRoles={['super_admin', 'template_designer']}>
                  <HazardVariablesPage />
                </ProtectedRoute>
              } />
              <Route path="templates/sfm-variables" element={
                <ProtectedRoute allowedRoles={['super_admin', 'template_designer']}>
                  <SfmVariablesPage />
                </ProtectedRoute>
              } />
              <Route path="templates/designer/:templateId" element={
                <ProtectedRoute allowedRoles={['super_admin', 'template_designer']}>
                  <TemplateDesignerPage />
                </ProtectedRoute>
              } />
              <Route path="admin/templates" element={
                <Navigate to="/templates?tab=manage&sub=admin" replace />
              } />
              <Route path="admin/translations" element={
                <ProtectedRoute allowedRoles={['super_admin']}>
                  <AdminTranslationsPage />
                </ProtectedRoute>
              } />
              <Route path="organization" element={
                <ProtectedRoute>
                  <OrganizationPage />
                </ProtectedRoute>
              } />
              <Route path="admin/users" element={
                <ProtectedRoute allowedRoles={['super_admin']}>
                  <AdminUsersPage />
                </ProtectedRoute>
              } />
              <Route path="admin/chat" element={
                <ProtectedRoute allowedRoles={['super_admin']}>
                  <AdminChatPage />
                </ProtectedRoute>
              } />
              <Route path="admin/costs" element={
                <ProtectedRoute allowedRoles={['super_admin']}>
                  <AdminCostsPage />
                </ProtectedRoute>
              } />
              <Route path="admin/soil-erosion-profiles" element={
                <ProtectedRoute allowedRoles={['super_admin']}>
                  <AdminSoilErosionProfilesPage />
                </ProtectedRoute>
              } />
              <Route path="admin/hazard-vuln-profiles" element={
                <ProtectedRoute allowedRoles={['super_admin']}>
                  <AdminHazardVulnProfilesPage />
                </ProtectedRoute>
              } />
              <Route path="admin/cba-rates" element={
                <ProtectedRoute allowedRoles={['super_admin']}>
                  <AdminCbaRatesPage />
                </ProtectedRoute>
              } />
              <Route path="admin/sfm-profiles" element={
                <ProtectedRoute allowedRoles={['super_admin']}>
                  <AdminSfmProfilesPage />
                </ProtectedRoute>
              } />
              <Route path="admin/sfm-prescriptions" element={
                <ProtectedRoute allowedRoles={['super_admin']}>
                  <AdminSfmPrescriptionsPage />
                </ProtectedRoute>
              } />

              {/* Legacy routes (redirects for backward compatibility) */}
              <Route path="dashboard" element={<Navigate to="/my-uploads" replace />} />
              <Route path="my-forests" element={<Navigate to="/my-uploads" replace />} />
              <Route path="fieldbook" element={<Navigate to="/my-uploads" replace />} />
              <Route path="sampling" element={<Navigate to="/my-uploads" replace />} />
              <Route path="cache" element={
                <ProtectedRoute allowedRoles={['super_admin']}>
                  <CacheManagementPanel />
                </ProtectedRoute>
              } />
            </Route>

            {/* Catch all - redirect to My CFOPs */}
            <Route path="*" element={<Navigate to="/my-uploads" replace />} />
          </Routes>
        </Suspense>
      </BrowserRouter>
      </ConfigProvider>
      </BoundaryPreviewProvider>
    </AuthProvider>
    </QueryClientProvider>
  );
};

export default App;
