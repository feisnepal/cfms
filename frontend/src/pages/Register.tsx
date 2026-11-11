/** Register — name, role, sub-division, a mobile number proved by SMS code, email, password, and a Facebook or Instagram identity. */
import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { useT } from '../i18n/hooks';
import LanguageSelector from '../components/LanguageSelector';
import PhoneCodeField from '../components/auth/PhoneCodeField';
import { authApi } from '../services/api';
import { apiErrorText } from '../lib/apiErrorText';
import { facebookAccessToken, facebookEnabled } from '../lib/facebookLogin';
import UserTypeFields, { EMPTY_TYPE, typePayload, typeReady, type TypeValue } from '../components/auth/UserTypeFields';

const input =
  'mt-1 block w-full rounded-xl border border-gray-200 bg-white/80 px-3.5 py-2.5 text-sm text-gray-900 placeholder-gray-400 shadow-sm transition focus:border-emerald-500 focus:outline-none focus:ring-4 focus:ring-emerald-100';
const label = 'block text-sm font-medium text-gray-700';

/** 0–4: one point for each rule the server enforces (8+ characters, capital, small letter, digit). */
const passwordScore = (p: string) =>
  [p.length >= 8, /[A-Z]/.test(p), /[a-z]/.test(p), /\d/.test(p)].filter(Boolean).length;
const METER = ['bg-gray-200', 'bg-red-400', 'bg-amber-400', 'bg-lime-500', 'bg-emerald-500'];

const Section: React.FC<{ n: number; title: string; children: React.ReactNode }> = ({ n, title, children }) => (
  <section className="space-y-4">
    <div className="flex items-center gap-3">
      <span className="flex h-7 w-7 items-center justify-center rounded-full bg-emerald-600 text-xs font-bold text-white shadow-sm shadow-emerald-600/30">
        {n}
      </span>
      <h3 className="text-sm font-semibold uppercase tracking-wide text-emerald-900">{title}</h3>
      <span className="h-px flex-1 bg-gradient-to-r from-emerald-200 to-transparent" />
    </div>
    {children}
  </section>
);

const Register: React.FC = () => {
  const t = useT();
  const { register, loginWithTokens } = useAuth();
  const navigate = useNavigate();
  const [formData, setFormData] = useState({
    full_name: '',
    email: '',
    password: '',
    instagram_handle: '',
  });
  const [typeValue, setTypeValue] = useState<TypeValue>(EMPTY_TYPE);
  const [phone, setPhone] = useState('');
  const [phoneCode, setPhoneCode] = useState('');
  const [facebookToken, setFacebookToken] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [created, setCreated] = useState(false);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    setFormData({ ...formData, [e.target.name]: e.target.value });
  };

  const connectFacebook = async () => {
    setError('');
    try {
      setFacebookToken(await facebookAccessToken());
    } catch {
      setError(t('auth.facebookFailed'));
    }
  };

  /** Sign up with Facebook alone: the account exists at once, the rest of the profile is asked for afterwards. */
  const signUpWithFacebook = async () => {
    setError('');
    if (!facebookEnabled()) {
      setError(t('auth.facebookNotSetUp'));
      return;
    }
    try {
      await loginWithTokens(await authApi.loginFacebook(await facebookAccessToken()));
      navigate('/complete-profile');
    } catch (err) {
      setError(apiErrorText(err, t('auth.facebookFailed')));
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    if (!typeReady(typeValue)) {
      setError(t('auth.typeIncomplete'));
      return;
    }
    setIsLoading(true);
    try {
      await register({
        full_name: formData.full_name,
        ...typePayload(typeValue),
        email: formData.email,
        password: formData.password,
        phone,
        phone_code: phoneCode,
        facebook_access_token: facebookToken || undefined,
        instagram_handle: formData.instagram_handle || undefined,
      });
      setCreated(true);
    } catch (err: any) {
      setError(apiErrorText(err, t('auth.registrationFailed')));
    } finally {
      setIsLoading(false);
    }
  };

  const score = passwordScore(formData.password);

  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
      {/* Brand panel: sits beside the form on wide screens, becomes a slim banner on phones. */}
      <aside className="relative overflow-hidden bg-gradient-to-br from-emerald-900 via-emerald-800 to-teal-700 px-6 py-8 text-white lg:px-12 lg:py-16">
        <div className="pointer-events-none absolute -right-24 -top-24 h-72 w-72 rounded-full bg-emerald-400/20 blur-3xl" />
        <div className="pointer-events-none absolute -bottom-32 -left-16 h-80 w-80 rounded-full bg-teal-300/20 blur-3xl" />
        <div className="relative flex h-full flex-col justify-between gap-10">
          <div className="flex items-center gap-3">
            <span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-white/15 text-2xl backdrop-blur">🌳</span>
            <span className="text-sm font-semibold tracking-wide text-emerald-50">{t('auth.joinSystem')}</span>
          </div>
          <div className="hidden space-y-8 lg:block">
            <h1 className="text-4xl font-extrabold leading-tight">{t('auth.createAccount')}</h1>
            <ul className="space-y-5 text-emerald-50/90">
              {[
                ['📱', t('auth.phoneRequired'), t('auth.phoneHelp')],
                ['🗺️', t('auth.typeTitle'), t('auth.typeOfficial')],
                ['🔐', t('auth.password'), t('auth.passwordHint')],
              ].map(([icon, title, body]) => (
                <li key={title} className="flex gap-4">
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-white/10 text-lg">{icon}</span>
                  <span>
                    <span className="block font-semibold text-white">{title}</span>
                    <span className="block text-sm text-emerald-100/80">{body}</span>
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </aside>

      <main className="flex items-start justify-center bg-gradient-to-b from-emerald-50/70 to-white px-4 py-8 sm:px-8 lg:items-center lg:py-12">
        <div className="w-full max-w-lg space-y-8">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="text-2xl font-extrabold text-gray-900 lg:hidden">{t('auth.createAccount')}</h2>
              <p className="text-sm text-gray-500">
                <Link to="/login" className="font-medium text-emerald-700 hover:text-emerald-600">
                  {t('auth.haveAccountSignIn')}
                </Link>
              </p>
            </div>
            <LanguageSelector />
          </div>

          {created ? (
            <div
              className="space-y-4 rounded-2xl border border-emerald-100 bg-white p-8 text-center shadow-xl shadow-emerald-900/5"
              data-testid="registration-pending"
            >
              <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-emerald-100 text-2xl">✓</div>
              <h3 className="text-lg font-semibold text-emerald-900">{t('auth.registrationPendingTitle')}</h3>
              <p className="text-sm text-gray-600">{t('auth.registrationPendingBody')}</p>
              <Link
                to="/login"
                className="inline-block rounded-xl bg-emerald-600 px-6 py-2.5 text-sm font-semibold text-white shadow-lg shadow-emerald-600/30 hover:bg-emerald-700"
              >
                {t('auth.backToSignIn')}
              </Link>
            </div>
          ) : (
            <form
              className="space-y-8 rounded-2xl border border-emerald-100 bg-white p-6 shadow-xl shadow-emerald-900/5 sm:p-8"
              onSubmit={handleSubmit}
            >
              {error && (
                <div className="rounded-xl border border-red-200 bg-red-50 p-4" role="alert">
                  <p className="text-sm text-red-800">{error}</p>
                </div>
              )}

              {(
                <div className="space-y-3">
                  <button type="button" onClick={signUpWithFacebook}
                    className="flex w-full items-center justify-center gap-2 rounded-xl bg-[#1877F2] px-4 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-[#166fe0]">
                    {t('auth.signUpWithFacebook')}
                  </button>
                  <p className="text-center text-xs text-gray-500">{t('auth.signUpWithFacebookHint')}</p>
                  <div className="flex items-center gap-3 text-xs uppercase text-gray-400">
                    <span className="h-px flex-1 bg-gray-200" />{t('auth.orFillIn')}<span className="h-px flex-1 bg-gray-200" />
                  </div>
                </div>
              )}

              <Section n={1} title={t('auth.typeTitle')}>
                <div>
                  <label htmlFor="full_name" className={label}>{t('auth.fullName')}</label>
                  <input id="full_name" name="full_name" type="text" required className={input}
                    placeholder={t('auth.fullNamePlaceholder')} value={formData.full_name} onChange={handleChange} />
                </div>

                <UserTypeFields value={typeValue} onChange={setTypeValue} />
              </Section>

              <Section n={2} title={t('auth.phoneRequired')}>
                <PhoneCodeField phone={phone} code={phoneCode} onPhone={setPhone} onCode={setPhoneCode}
                  send={authApi.signupPhoneCode} />
                <div>
                  <label htmlFor="email" className={label}>{t('auth.emailLabel')}</label>
                  <input id="email" name="email" type="email" autoComplete="email" required className={input}
                    placeholder={t('auth.emailPlaceholder')} value={formData.email} onChange={handleChange} />
                </div>
              </Section>

              <Section n={3} title={t('auth.socialTitle')}>
                <p className="-mt-2 text-xs text-gray-500">{t('auth.socialHelp')}</p>
                {facebookEnabled() && (
                  <button type="button" onClick={connectFacebook}
                    className={`flex w-full items-center justify-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold shadow-sm transition ${
                      facebookToken
                        ? 'bg-emerald-50 text-emerald-800 ring-1 ring-emerald-300'
                        : 'bg-[#1877F2] text-white hover:bg-[#166fe0]'
                    }`}>
                    {facebookToken ? `✓ ${t('auth.facebookConnected')}` : t('auth.connectFacebook')}
                  </button>
                )}
                <div>
                  <label htmlFor="instagram_handle" className="sr-only">{t('auth.instagramHandle')}</label>
                  <input id="instagram_handle" name="instagram_handle" type="text" className={input}
                    placeholder={`@${t('auth.instagramPlaceholder')}`} value={formData.instagram_handle}
                    onChange={handleChange} />
                </div>
              </Section>

              <Section n={4} title={t('auth.password')}>
                <div>
                  <label htmlFor="password" className="sr-only">{t('auth.password')}</label>
                  <div className="relative">
                    <input id="password" name="password" type={showPassword ? 'text' : 'password'}
                      autoComplete="new-password" required className={`${input} pr-16`} placeholder="••••••••"
                      aria-describedby="password-hint" value={formData.password} onChange={handleChange} />
                    <button type="button" onClick={() => setShowPassword((s) => !s)}
                      aria-label={showPassword ? t('auth.hidePassword') : t('auth.showPassword')}
                      className="absolute inset-y-0 right-0 mt-1 px-3.5 text-xs font-semibold text-emerald-700 hover:text-emerald-900">
                      {showPassword ? t('auth.hide') : t('auth.show')}
                    </button>
                  </div>
                  <div className="mt-2 flex gap-1.5" aria-hidden="true">
                    {[1, 2, 3, 4].map((i) => (
                      <span key={i} className={`h-1.5 flex-1 rounded-full transition-colors ${i <= score ? METER[score] : 'bg-gray-200'}`} />
                    ))}
                  </div>
                  <p id="password-hint" className="mt-1.5 text-xs text-gray-500">{t('auth.passwordHint')}</p>
                </div>
              </Section>

              <button type="submit" disabled={isLoading}
                className="w-full rounded-xl bg-gradient-to-r from-emerald-600 to-teal-600 px-4 py-3 text-sm font-semibold text-white shadow-lg shadow-emerald-600/30 transition hover:from-emerald-700 hover:to-teal-700 focus:outline-none focus:ring-4 focus:ring-emerald-200 disabled:cursor-not-allowed disabled:from-gray-400 disabled:to-gray-400 disabled:shadow-none">
                {isLoading ? t('auth.creatingAccount') : t('auth.register')}
              </button>
            </form>
          )}
        </div>
      </main>
    </div>
  );
};

export default Register;
