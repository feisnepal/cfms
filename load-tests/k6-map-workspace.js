// load-tests/k6-map-workspace.js
// Phase 11 — k6 load testing for the tabbed Calculation Detail / Workspace.
// Adapted from Tab_setup to this app's real stack: Leaflet (not Mapbox),
// frontend routes `/my-uploads` + `/calculations/:id/tabbed`, API base
// `/api` (proxied by the frontend; backend on :8001).
//
// Run:
//   k6 run load-tests/k6-map-workspace.js                       # against local preview + backend
//   k6 run --env BASE_URL=https://demo.forest.example --env TEST_AUTH_TOKEN=xxx load-tests/k6-map-workspace.js
//
// Env:
//   BASE_URL            default http://localhost:4173
//   API_URL             default <BASE_URL>/api
//   TEST_AUTH_TOKEN     optional bearer token (skips login)
//
// ⚠ H5.6 / H2.8: THE TARGET MUST RUN WITH RATE_LIMIT_ENABLED=false.
//   Rate limiting (added after this script was written) applies 600 req/min to
//   every route and keys it on IDENTITY, not address. TEST_AUTH_TOKEN — and the
//   fallback single login below — share ONE token across every VU, so all 250
//   are one identity on one 600/min budget. Left enabled, this measures the
//   limiter: the run is mostly 429s and p95 reports how fast it refuses.
//   config.py: "Off only for deliberate load tests."
//   Full analysis: runbooks/OPS-ASSETS-VERIFICATION.md §3
//   LOAD_TEST_USER/PASS default demo@forest.com / Demo1234
//   CALC_IDS            comma-separated calc ids (default the shared e2e demo calc)
//
// Scenarios (per plan): Normal 50→100 VUs (16m), Spike 50→200 (5m),
// Stress 100→1000 (19m), Soak 50 constant (30m) — staggered in one run.
//
// Custom metrics per plan: map_init_time (p75/p95), tab_switch_time (p95),
// chunk_download_time, api_errors (<5%), active_users.
// NOTE: map_init_time is approximated by the MapWorkspace chunk fetch
// duration (k6 measures HTTP, not client-side JS) — the exact client metric
// is `measurements.map-init` in Sentry (Phase 10).

import http from 'k6/http';
import { check, sleep, group } from 'k6';
import { Trend, Rate, Counter, Gauge } from 'k6/metrics';
import { randomIntBetween } from 'https://jslib.k6.io/k6-utils/1.2.0/index.js';

// ─── Custom Metrics ────────────────────────────────────────────────
const mapInitTime = new Trend('map_init_time', true);
const tabSwitchTime = new Trend('tab_switch_time', true);
const apiErrorRate = new Rate('api_errors');
const chunkDownloadTime = new Trend('chunk_download_time', true);
const activeUsers = new Gauge('active_users');
const calculationLoads = new Counter('calculation_loads');

// ─── Scenarios & Thresholds ────────────────────────────────────────
export const options = {
  scenarios: {
    normal_load: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '2m', target: 50 },
        { duration: '4m', target: 50 },
        { duration: '2m', target: 100 },
        { duration: '6m', target: 100 },
        { duration: '2m', target: 0 },
      ],
      gracefulRampDown: '30s',
      tags: { scenario: 'normal' },
    },
    spike_test: {
      executor: 'ramping-vus',
      startVUs: 50,
      stages: [
        { duration: '1m', target: 200 },
        { duration: '2m', target: 200 },
        { duration: '1m', target: 50 },
        { duration: '1m', target: 0 },
      ],
      startTime: '16m',
      tags: { scenario: 'spike' },
    },
    stress_test: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '1m', target: 100 },
        { duration: '2m', target: 250 },
        { duration: '2m', target: 500 },
        { duration: '2m', target: 750 },
        { duration: '2m', target: 1000 },
        { duration: '8m', target: 1000 },
        { duration: '2m', target: 0 },
      ],
      startTime: '22m',
      tags: { scenario: 'stress' },
    },
    soak_test: {
      executor: 'constant-vus',
      vus: 50,
      duration: '30m',
      startTime: '41m',
      tags: { scenario: 'soak' },
    },
  },
  thresholds: {
    http_req_duration: ['p(95)<2000'],
    http_req_failed: ['rate<0.01'],
    map_init_time: ['p(75)<3000', 'p(95)<5000'],
    tab_switch_time: ['p(95)<100'],
    api_errors: ['rate<0.05'],
  },
  tags: {
    service: 'calculation-detail',
    environment: __ENV.ENV || 'staging',
  },
};

const BASE_URL = (__ENV.BASE_URL || 'http://localhost:4173').replace(/\/$/, '');
const API_URL = (__ENV.API_URL || BASE_URL + '/api').replace(/\/$/, '');

const CALC_IDS = (__ENV.CALC_IDS || '15f64467-c857-4948-bb42-34eefadb88bc')
  .split(',')
  .map((s) => s.trim())
  .filter(Boolean);

function randomCalculationId() {
  return CALC_IDS[randomIntBetween(0, CALC_IDS.length - 1)];
}

export function setup() {
  console.log(`Load test against: ${BASE_URL} (API ${API_URL})`);

  let token = __ENV.TEST_AUTH_TOKEN || '';
  if (!token) {
    const login = http.post(
      API_URL + '/auth/login',
      JSON.stringify({
        username: __ENV.LOAD_TEST_USER || 'demo@forest.com',
        password: __ENV.LOAD_TEST_PASSWORD || 'Demo1234',
      }),
      { headers: { 'Content-Type': 'application/json' } },
    );
    token = login.status === 200 ? (login.json('access_token') || '') : '';
    console.log(`Login via ${API_URL}/auth/login -> ${login.status}`);
  }

  // Discover the hashed MapWorkspace chunk from the served HTML so the test
  // doesn't pin a stale filename.
  let mapChunkPath = '';
  const index = http.get(BASE_URL + '/my-uploads');
  const m = /MapWorkspace-[A-Za-z0-9_-]+\.js/.exec(String(index.body || ''));
  if (m) mapChunkPath = '/assets/' + m[0];

  return { token, mapChunkPath, baseUrl: BASE_URL, apiUrl: API_URL };
}

export default function (data) {
  const { token, mapChunkPath, baseUrl, apiUrl } = data;
  const headers = {
    Authorization: 'Bearer ' + token,
    'Content-Type': 'application/json',
  };
  const calcId = randomCalculationId();
  activeUsers.add(__VU);

  group('01 - Load Calculations List', () => {
    const res = http.get(baseUrl + '/my-uploads', { headers });
    check(res, {
      'list page served (200)': (r) => r.status === 200,
    });
    sleep(randomIntBetween(1, 3));
  });

  group('02 - Load Calculation Detail + Map Chunk', () => {
    const detailRes = http.get(`${apiUrl}/forests/calculations/${calcId}`, { headers });
    check(detailRes, {
      'detail API 200': (r) => r.status === 200,
      'detail < 3s': (r) => r.timings.duration < 3000,
    });
    apiErrorRate.add(detailRes.status >= 400);
    calculationLoads.add(1);

    if (mapChunkPath) {
      const chunkStart = Date.now();
      const chunkRes = http.get(baseUrl + mapChunkPath);
      chunkDownloadTime.add(chunkRes.timings.duration);
      check(chunkRes, {
        'map chunk 200': (r) => r.status === 200,
      });
      // Proxy for map init: chunk fetch + transfer (client JS init is Sentry's
      // measurements.map-init).
      mapInitTime.add(Date.now() - chunkStart);
    }

    sleep(randomIntBetween(3, 8));
  });

  group('03 - Sampling tab data', () => {
    const start = Date.now();
    const res = http.get(`${apiUrl}/forests/calculations/${calcId}/blocks`, { headers });
    tabSwitchTime.add(Date.now() - start);
    check(res, {
      'blocks API 200': (r) => r.status === 200,
      'tab switch < 100ms': () => Date.now() - start < 100,
    });
    apiErrorRate.add(res.status >= 400);
    sleep(randomIntBetween(2, 5));
  });

  group('04 - Reports tab data', () => {
    const start = Date.now();
    const res = http.get(`${apiUrl}/forests/calculations/${calcId}/sub-areas`, { headers });
    tabSwitchTime.add(Date.now() - start);
    check(res, {
      'sub-areas API 200': (r) => r.status === 200,
      'tab switch < 100ms': () => Date.now() - start < 100,
    });
    apiErrorRate.add(res.status >= 400);
    sleep(randomIntBetween(1, 3));
  });

  // NOTE: no mutating POST (digitize/geometry) here on purpose — load tests
  // must not write data into the database. Geometry/OP writes are covered by
  // functional + E2E tests instead.
}

export function teardown(data) {
  console.log('Load test complete.');
}
