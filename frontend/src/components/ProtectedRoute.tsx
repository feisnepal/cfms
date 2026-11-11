/** ProtectedRoute — redirects unauthenticated users to the login page. */
import React from 'react';
import { Link, Navigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { useT } from '../i18n/hooks';

interface ProtectedRouteProps {
  children: React.ReactNode;
  /** The profile page itself must open for someone whose profile is still empty. */
  allowIncompleteProfile?: boolean;
  allowedRoles?: Array<'guest' | 'user' | 'org_admin' | 'super_admin' | 'template_designer'>;
}

/** True if the person was already sent to the profile form in this browser session; marks it as sent otherwise. */
const profileNudged = (): boolean => {
  try {
    if (sessionStorage.getItem('profileNudged')) return true;
    sessionStorage.setItem('profileNudged', '1');
  } catch {
    return true; // no storage: never loop them back to the form
  }
  return false;
};

const ProtectedRoute: React.FC<ProtectedRouteProps> = ({ children, allowedRoles, allowIncompleteProfile }) => {
  const { user, isAuthenticated, isLoading } = useAuth();
  const t = useT();

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <p className="text-gray-500">{t('common.loading')}</p>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  if (allowedRoles && user && !allowedRoles.includes(user.role)) {
    return <Navigate to="/my-uploads" replace />;
  }

  // Limited tier (signed in, not yet approved by a super admin). An unapproved account that never
  // said who it is — a Facebook sign-in — is asked first. Approved accounts, which include every
  // account that existed before sign-up verification, are never forced through the form.
  const limited = !!user && user.is_approved === false;
  const incomplete = !!user && user.profile_complete === false;
  // A reminder, not a wall: sent to the form once per browser session, then only the banner below.
  if (limited && incomplete && !allowIncompleteProfile && !profileNudged()) {
    return <Navigate to="/complete-profile" replace />;
  }

  return (
    <>
      {limited && (
        <div className="bg-amber-50 border-b border-amber-200 px-4 py-2 text-center text-sm text-amber-900" role="status">
          {t('auth.limitedBanner')}
        </div>
      )}
      {incomplete && !allowIncompleteProfile && (
        <div className="bg-emerald-50 border-b border-emerald-200 px-4 py-2 text-center text-sm text-emerald-900" role="status">
          {t('auth.profileReminder')}{' '}
          <Link to="/complete-profile" className="font-semibold underline">{t('auth.profileReminderLink')}</Link>
        </div>
      )}
      {user?.access_level === 'read_only' && (
        <div className="bg-sky-50 border-b border-sky-200 px-4 py-2 text-center text-sm text-sky-900" role="status">
          {t('auth.readOnlyBanner')}
          {user.access_expires_at && ` ${t('auth.accessEnds', { date: user.access_expires_at.slice(0, 10) })}`}
        </div>
      )}
      {children}
    </>
  );
};

export default ProtectedRoute;
