/** Login — email + password, phone + SMS code, or Facebook; then a role-based redirect. */
import React, { useState } from 'react';
import { useNavigate, useSearchParams, Link } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { useT } from '../i18n/hooks';
import LanguageSelector from '../components/LanguageSelector';
import PhoneCodeField from '../components/auth/PhoneCodeField';
import { authApi } from '../services/api';
import { apiErrorText } from '../lib/apiErrorText';
import { facebookAccessToken, facebookEnabled } from '../lib/facebookLogin';

type Mode = 'email' | 'phone';

const field =
  'appearance-none relative block w-full px-3 py-2 border border-gray-300 placeholder-gray-500 text-gray-900 focus:outline-none focus:ring-green-500 focus:border-green-500 focus:z-10 sm:text-sm';

const Login: React.FC = () => {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  // where to go after signing in: a path on this site only (never a full URL, so the link cannot send a person elsewhere)
  const requested = searchParams.get('next');
  const afterLogin = requested && requested.startsWith('/') && !requested.startsWith('//') && !requested.includes('\\') ? requested : '/dashboard';
  const t = useT();
  const { login, loginWithTokens } = useAuth();
  const [mode, setMode] = useState<Mode>('email');
  const [formData, setFormData] = useState({ email: '', password: '' });
  const [phone, setPhone] = useState('');
  const [phoneCode, setPhoneCode] = useState('');
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  /** Runs one sign-in attempt with the shared busy / error handling. */
  const attempt = async (run: () => Promise<void>, fallback: string) => {
    setError('');
    setIsLoading(true);
    try {
      await run();
      navigate(afterLogin);
    } catch (err: any) {
      setError(apiErrorText(err, fallback));
    } finally {
      setIsLoading(false);
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    return mode === 'email'
      ? attempt(() => login(formData), t('auth.loginFailed'))
      : attempt(async () => loginWithTokens(await authApi.loginPhone(phone, phoneCode)), t('auth.loginFailed'));
  };

  const withFacebook = () =>
    !facebookEnabled()
      ? setError(t('auth.facebookNotSetUp'))
      : attempt(async () => loginWithTokens(await authApi.loginFacebook(await facebookAccessToken())), t('auth.facebookFailed'));

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setFormData({ ...formData, [e.target.name]: e.target.value });
  };

  const tab = (m: Mode, text: string) => (
    <button
      type="button"
      role="tab"
      aria-selected={mode === m}
      onClick={() => { setMode(m); setError(''); }}
      className={`flex-1 py-2 text-sm font-medium border-b-2 ${
        mode === m ? 'border-green-600 text-green-700' : 'border-transparent text-gray-500 hover:text-gray-700'
      }`}
    >
      {text}
    </button>
  );

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 py-12 px-4 sm:px-6 lg:px-8">
      <div className="max-w-md w-full space-y-8">
        <LanguageSelector />
        <div>
          <img src="/cfms-logo.png" alt="" className="mx-auto h-20 w-20" />
          <h2 className="mt-4 text-center text-3xl font-extrabold text-gray-900">{t('common.appName')}</h2>
          <p className="mt-2 text-center text-sm text-gray-600">{t('auth.signInToAccount')}</p>
        </div>
        <form className="mt-8 space-y-6" onSubmit={handleSubmit}>
          {error && (
            <div className="rounded-md bg-red-50 p-4" role="alert">
              <p className="text-sm text-red-800">{error}</p>
            </div>
          )}

          <div role="tablist" className="flex border-b border-gray-200">
            {tab('email', t('auth.tabEmail'))}
            {tab('phone', t('auth.tabPhone'))}
          </div>

          {mode === 'email' ? (
            <div className="rounded-md shadow-sm -space-y-px">
              <div>
                <label htmlFor="email" className="sr-only">{t('auth.email')}</label>
                <input id="email" name="email" type="email" autoComplete="email" required
                  className={`${field} rounded-none rounded-t-md`} placeholder={t('auth.email')}
                  value={formData.email} onChange={handleChange} />
              </div>
              <div>
                <label htmlFor="password" className="sr-only">{t('auth.password')}</label>
                <input id="password" name="password" type="password" autoComplete="current-password" required
                  className={`${field} rounded-none rounded-b-md`} placeholder={t('auth.password')}
                  value={formData.password} onChange={handleChange} />
              </div>
            </div>
          ) : (
            <div className="space-y-2">
              <p className="text-sm text-gray-600">{t('auth.phoneSignInHelp')}</p>
              <PhoneCodeField idPrefix="login-phone" phone={phone} code={phoneCode} onPhone={setPhone}
                onCode={setPhoneCode} send={authApi.loginPhoneCode} />
            </div>
          )}

          <div className="space-y-3">
            <button type="submit" disabled={isLoading || (mode === 'phone' && phoneCode.length < 4)}
              className="group relative w-full flex justify-center py-2 px-4 border border-transparent text-sm font-medium rounded-md text-white bg-green-600 hover:bg-green-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-green-500 disabled:bg-gray-400">
              {isLoading ? t('auth.signingIn') : mode === 'phone' ? t('auth.signInWithCode') : t('auth.signIn')}
            </button>

            {(
              <>
                <p className="text-center text-xs text-gray-500">{t('auth.orContinueWith')}</p>
                <button type="button" onClick={withFacebook} disabled={isLoading}
                  className="w-full py-2 px-4 text-sm font-medium rounded-md text-white bg-blue-600 hover:bg-blue-700 disabled:bg-gray-400">
                  {t('auth.signInWithFacebook')}
                </button>
              </>
            )}
          </div>

          <div className="flex justify-between text-sm">
            <Link to="/forgot-password" className="font-medium text-green-600 hover:text-green-500">
              {t('auth.forgotPassword')}
            </Link>
            <Link to="/register" className="font-medium text-green-600 hover:text-green-500">
              {t('auth.noAccountRegister')}
            </Link>
          </div>
        </form>
      </div>
    </div>
  );
};

export default Login;
