/** ForumShell - the forum's own page frame. The forum is readable without an account, so it cannot sit inside the signed-in Layout. */
import React from 'react';
import { Link, Outlet, useLocation } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { useAuth } from '../../contexts/AuthContext';
import { forumApi } from './forumApi';
import { useT } from '../../i18n/hooks';
import LanguageSelector from '../../components/LanguageSelector';

const ForumShell: React.FC = () => {
  const t = useT();
  const { user } = useAuth();
  const location = useLocation();
  const me = useQuery({ queryKey: ['forum', 'me'], queryFn: forumApi.me, enabled: !!user, staleTime: 30_000 });
  const next = encodeURIComponent(location.pathname + location.search);
  return (
    <div className="min-h-screen bg-gray-50">
      <nav className="sticky top-0 z-40 bg-green-600 shadow-lg rounded-b-xl">
        <div className="max-w-5xl mx-auto px-4 sm:px-6 py-3 flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
            <Link to="/forum" className="flex items-center gap-2">
              <span className="flex-shrink-0 bg-white rounded-full p-0.5 flex items-center justify-center">
                <img src="/cfms-logo.png" alt="" className="h-7 w-7" />
              </span>
              <span className="text-white text-lg font-semibold leading-tight">{t('forum.title')}</span>
            </Link>
            {user && <Link to="/my-uploads" className="text-white text-sm font-medium hover:underline">{t('forum.backToApp')}</Link>}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <LanguageSelector compact />
            {me.data?.is_moderator && <Link to="/forum/moderation" className="text-white text-sm font-medium hover:underline">{t('forum.moderation')}</Link>}
            {user && me.data && (
              <>
              <Link to="/forum/settings" className="text-white text-sm font-medium hover:underline">{t('forum.emailSettings')}</Link>
              <Link to="/forum/me" className="text-white text-sm font-medium hover:underline" title={t('forum.reputationHistory')}>
                {me.data.name} · {me.data.reputation}
              </Link>
              </>
            )}
            {!user && (
              <>
                <Link to={`/login?next=${next}`} className="text-white text-sm font-medium hover:underline">{t('forum.signIn')}</Link>
                <Link to="/register" className="px-3 py-1.5 rounded-md text-sm font-medium text-green-700 bg-white hover:bg-gray-50">{t('forum.register')}</Link>
              </>
            )}
          </div>
        </div>
      </nav>
      <main className="max-w-5xl mx-auto px-4 sm:px-6 py-6">
        <Outlet />
      </main>
    </div>
  );
};

export default ForumShell;
