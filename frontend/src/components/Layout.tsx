/** Layout — main app shell with sidebar navigation and content area. */
import React, { useState } from 'react';
import { Link, Outlet, useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { useT } from '../i18n/hooks';
import { Dropdown } from 'antd';
import LanguageSelector from './LanguageSelector';

// Super-admin pages, grouped under one "Admin" menu instead of one nav link each.
const ADMIN_LINKS: [string, string][] = [
  ['/admin/users', 'navigation.users'],
  ['/admin/translations', 'navigation.translations'],
  ['/admin/chat', 'navigation.adminChat'],
  ['/admin/costs', 'navigation.costs'],
  ['/admin/cba-rates', 'navigation.adminCostBenefit'],
  ['/admin/soil-erosion-profiles', 'navigation.adminSoilErosion'],
  ['/admin/hazard-vuln-profiles', 'navigation.adminHazard'],
  ['/admin/sfm-profiles', 'navigation.adminSfmProfiles'],
  ['/admin/sfm-prescriptions', 'navigation.adminSfmPrescriptions'],
  ['/templates?tab=manage&sub=admin', 'navigation.adminTemplates'],
  ['/cache', 'navigation.adminCache'],
];

const Layout: React.FC = () => {
  const t = useT();
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  return (
    <div className="min-h-screen bg-gray-50">
      <nav className="sticky top-0 z-40 bg-green-600 shadow-lg rounded-b-xl">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 py-3">
            <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
              <div className="flex-shrink-0 flex items-center gap-2">
                <Link to="/my-uploads" className="flex items-center gap-2">
                  {/* White badge behind the mark: the logo is transparent-background
                      dark-green line art, which has poor contrast directly on the
                      green nav bar (bg-green-600) without it. */}
                  <span className="flex-shrink-0 bg-white rounded-full p-0.5 flex items-center justify-center">
                    <img src="/cfms-logo.png" alt="" className="h-7 w-7" />
                  </span>
                  <span className="text-white text-lg font-semibold leading-tight max-w-[12rem]">
                    {t('common.appName')}
                  </span>
                </Link>
              </div>
              <div className="flex flex-wrap items-center gap-x-5 gap-y-1">
                <Link
                  to="/my-uploads"
                  className="border-transparent text-white hover:border-white hover:text-white inline-flex items-center px-1 pt-1 border-b-2 text-sm font-medium"
                >
                  {t('navigation.myCfs')}
                </Link>
                <Link
                  to="/forests"
                  className="border-transparent text-white hover:border-white hover:text-white inline-flex items-center px-1 pt-1 border-b-2 text-sm font-medium"
                >
                  {t('navigation.communityForests')}
                </Link>
                <Link
                  to="/templates"
                  className="border-transparent text-white hover:border-white hover:text-white inline-flex items-center px-1 pt-1 border-b-2 text-sm font-medium"
                >
                  {t('navigation.templates')}
                </Link>
                <Link
                  to="/forum"
                  className="border-transparent text-white hover:border-white hover:text-white inline-flex items-center px-1 pt-1 border-b-2 text-sm font-medium"
                >
                  {t('navigation.forum')}
                </Link>
                {user?.org_member_role === 'owner' && (
                  <Link
                    to="/organization"
                    className="border-transparent text-white hover:border-white hover:text-white inline-flex items-center px-1 pt-1 border-b-2 text-sm font-medium"
                  >
                    {t('navigation.organization')}
                  </Link>
                )}
                {user?.role === 'super_admin' && (
                  <Dropdown
                    trigger={['click']}
                    menu={{
                      items: ADMIN_LINKS.map(([to, key]) => ({ key: to, label: t(key) })),
                      onClick: ({ key }) => navigate(key),
                    }}
                  >
                    <button
                      type="button"
                      className="border-transparent text-white hover:border-white inline-flex items-center px-1 pt-1 border-b-2 text-sm font-medium bg-transparent"
                    >
                      {t('navigation.admin')} ▾
                    </button>
                  </Dropdown>
                )}
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <LanguageSelector compact />
              <span className="hidden md:inline text-white text-sm">{user?.email}</span>
              <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${user?.role === 'super_admin' ? 'bg-yellow-300 text-yellow-900' : 'bg-blue-300 text-blue-900'}`}>
                {user?.role === 'super_admin' ? t('auth.roleAdmin') : t('auth.roleUser')}
              </span>
              <button
                onClick={handleLogout}
                className="relative inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-green-600 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-green-500"
              >
                {t('navigation.logout')}
              </button>
            </div>
          </div>
        </div>
      </nav>
      <main className="pt-4">
        <Outlet />
      </main>
    </div>
  );
};

export default Layout;