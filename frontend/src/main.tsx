/**
 * main — application entry point.
 *
 * Mounts the React app into the DOM, applies global styles, and
 * initializes Sentry monitoring (side-effect import) plus Web Vitals
 * listeners (Phase 8) before the first render so LCP/FCP/CLS windows are
 * not missed.
 */
import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import RootErrorBoundary from './components/RootErrorBoundary';
import './index.css';
import { initPerformanceMonitoring } from './lib/performance';
import './utils/sentry'; // side-effect: initializes Sentry only if VITE_SENTRY_DSN is set
import './i18n'; // side-effect: initializes i18n with Nepali/English locales
import { registerOfflineSupport } from './pwa/offline';

initPerformanceMonitoring();
registerOfflineSupport(); // production builds only: the page and the forest's data open without a signal

// H3.8: outside StrictMode on purpose. StrictMode double-invokes render in
// development, so a boundary inside it can catch the same error twice and
// report it twice; outside, it still catches everything below and reports once.
ReactDOM.createRoot(document.getElementById('root')!).render(
  <RootErrorBoundary>
    <React.StrictMode>
      <App />
    </React.StrictMode>
  </RootErrorBoundary>
);
