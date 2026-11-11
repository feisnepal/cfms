/**
 * Facebook Login through Facebook's own JS SDK.
 *
 * Off until VITE_FACEBOOK_APP_ID is set (a Meta developer app). The browser only ever
 * hands us an access token; the server asks Facebook whether that token is real and
 * ours before it believes anything about who the person is. Facebook also refuses to
 * open its dialog on plain http outside localhost, so this needs https in production.
 */

const APP_ID = (import.meta.env.VITE_FACEBOOK_APP_ID ?? '') as string;
const SDK_URL = 'https://connect.facebook.net/en_US/sdk.js';

interface FbSdk {
  init: (opts: Record<string, unknown>) => void;
  login: (cb: (res: { authResponse?: { accessToken: string } }) => void, opts: Record<string, unknown>) => void;
}

declare global {
  interface Window {
    FB?: FbSdk;
    fbAsyncInit?: () => void;
  }
}

export const facebookEnabled = (): boolean => APP_ID.length > 0;

let sdkReady: Promise<FbSdk> | null = null;

const loadSdk = (): Promise<FbSdk> => {
  if (sdkReady) return sdkReady;
  sdkReady = new Promise<FbSdk>((resolve, reject) => {
    window.fbAsyncInit = () => {
      window.FB!.init({ appId: APP_ID, cookie: false, xfbml: false, version: 'v21.0' });
      resolve(window.FB!);
    };
    const script = document.createElement('script');
    script.src = SDK_URL;
    script.async = true;
    script.onerror = () => {
      sdkReady = null; // let a later click try again
      reject(new Error('facebook sdk blocked'));
    };
    document.head.appendChild(script);
  });
  return sdkReady;
};

/** Opens the Facebook dialog and resolves with an access token, or rejects if the person backs out. */
export const facebookAccessToken = async (): Promise<string> => {
  const fb = await loadSdk();
  return new Promise<string>((resolve, reject) => {
    fb.login(
      (res) => (res.authResponse?.accessToken ? resolve(res.authResponse.accessToken) : reject(new Error('cancelled'))),
      { scope: 'public_profile,email' },
    );
  });
};
