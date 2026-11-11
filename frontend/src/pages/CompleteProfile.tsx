/** CompleteProfile — the one thing a Facebook sign-in is asked for: who the person is in the sub-division. */
import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { useT } from '../i18n/hooks';
import LanguageSelector from '../components/LanguageSelector';
import { authApi } from '../services/api';
import { apiErrorText } from '../lib/apiErrorText';
import UserTypeFields, { typePayload, typeReady, type TypeValue } from '../components/auth/UserTypeFields';

const input =
  'mt-1 block w-full px-3 py-2 border border-gray-300 placeholder-gray-500 text-gray-900 rounded-md focus:outline-none focus:ring-green-500 focus:border-green-500 sm:text-sm';

const CompleteProfile: React.FC = () => {
  const t = useT();
  const navigate = useNavigate();
  const { user, refreshUser } = useAuth();
  const [fullName, setFullName] = useState(user?.full_name ?? '');
  const [typeValue, setTypeValue] = useState<TypeValue>({
    userType: user?.user_type ?? '',
    designation: user?.designation ?? '',
    subDivision: user?.sub_division ?? '',
    details: (user?.type_details as Record<string, string>) ?? {},
  });
  const [instagram, setInstagram] = useState(user?.instagram_handle ?? '');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!typeReady(typeValue)) return;
    setError('');
    setBusy(true);
    try {
      await authApi.updateProfile({
        full_name: fullName,
        ...typePayload(typeValue),
        instagram_handle: instagram || undefined,
      });
      await refreshUser();
      navigate('/dashboard');
    } catch (err) {
      setError(apiErrorText(err, t('auth.registrationFailed')));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 py-12 px-4 sm:px-6 lg:px-8">
      <form className="max-w-md w-full space-y-6" onSubmit={submit}>
        <LanguageSelector />
        <div>
          <h2 className="text-center text-2xl font-extrabold text-gray-900">{t('auth.completeProfileTitle')}</h2>
          <p className="mt-2 text-center text-sm text-gray-600">{t('auth.completeProfileHelp')}</p>
        </div>
        {error && <div className="rounded-md bg-red-50 p-4 text-sm text-red-800" role="alert">{error}</div>}
        <div className="space-y-4">
          <div>
            <label htmlFor="full_name" className="block text-sm font-medium text-gray-700">{t('auth.fullName')}</label>
            <input id="full_name" required minLength={2} className={input} value={fullName}
              onChange={(e) => setFullName(e.target.value)} />
          </div>
          <UserTypeFields value={typeValue} onChange={setTypeValue} />
          <div>
            <label htmlFor="instagram" className="block text-sm font-medium text-gray-700">{t('auth.instagramHandle')}</label>
            <input id="instagram" className={input} placeholder={`@${t('auth.instagramPlaceholder')}`} value={instagram}
              onChange={(e) => setInstagram(e.target.value)} />
          </div>
        </div>
        <button type="submit" disabled={busy || !typeReady(typeValue)}
          className="w-full flex justify-center py-2 px-4 text-sm font-medium rounded-md text-white bg-green-600 hover:bg-green-700 disabled:bg-gray-400">
          {t('auth.saveProfile')}
        </button>
        <p className="text-center text-sm">
          <Link to="/dashboard" className="text-gray-500 hover:text-gray-700">{t('auth.skipForNow')}</Link>
        </p>
      </form>
    </div>
  );
};

export default CompleteProfile;
