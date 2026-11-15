// k6 load/stress test for SignWave backend.
// Usage:
//   k6 run tests/load/k6.signwave.js
//   BASE=https://host PROFILE=smoke k6 run tests/load/k6.signwave.js
// Profiles: smoke | stress (default) — or override with env VU_*/DURATION.

import http from 'k6/http';
import ws from 'k6/ws';
import { check, sleep, fail } from 'k6';
import { Rate, Trend, Counter } from 'k6/metrics';
import { uuidv4 } from 'https://jslib.k6.io/k6-utils/1.4.0/index.js';

const BASE = __ENV.BASE || 'https://signwave-24148.swedencentral.cloudapp.azure.com';
const WS_BASE = BASE.replace(/^http/, 'ws');

const PROFILE = __ENV.PROFILE || 'stress';

const errorRate = new Rate('errors');
const httpPredict = new Trend('ml_predict_duration', true);
const wsRtt = new Trend('ws_predict_rtt', true);
const registered = new Counter('users_registered');

// ---------- scenarios ----------
const profiles = {
  smoke: {
    auth:      { executor: 'constant-vus', vus: 2,  duration: '30s', exec: 'authFlow' },
    api:       { executor: 'constant-vus', vus: 5,  duration: '30s', exec: 'apiFlow', startTime: '5s' },
    ml_http:   { executor: 'constant-vus', vus: 3,  duration: '30s', exec: 'mlPredictHttp', startTime: '5s' },
    ml_ws:     { executor: 'constant-vus', vus: 3,  duration: '30s', exec: 'mlPredictWs', startTime: '5s' },
  },
  stress: {
    auth:      { executor: 'ramping-vus', startVUs: 0, exec: 'authFlow',
                 stages: [{ duration: '1m', target: 30 }, { duration: '4m', target: 30 }, { duration: '1m', target: 0 }] },
    api:       { executor: 'ramping-vus', startVUs: 0, exec: 'apiFlow', startTime: '10s',
                 stages: [{ duration: '2m', target: 150 }, { duration: '2m', target: 400 },
                          { duration: '3m', target: 400 }, { duration: '1m', target: 0 }] },
    ml_http:   { executor: 'ramping-vus', startVUs: 0, exec: 'mlPredictHttp', startTime: '20s',
                 stages: [{ duration: '2m', target: 10 }, { duration: '2m', target: 40 },
                          { duration: '3m', target: 40 }, { duration: '1m', target: 0 }] },
    ml_ws:     { executor: 'ramping-vus', startVUs: 0, exec: 'mlPredictWs', startTime: '30s',
                 stages: [{ duration: '2m', target: 10 }, { duration: '2m', target: 40 },
                          { duration: '3m', target: 40 }, { duration: '1m', target: 0 }] },
  },
};

export const options = {
  scenarios: profiles[PROFILE],
  thresholds: {
    http_req_failed: ['rate<0.05'],
    http_req_duration: ['p(95)<5000'],
    errors: ['rate<0.10'],
  },
};

const JSON_HEADERS = { 'Content-Type': 'application/json' };

// ---------- helpers ----------

// One 20x450 feature window, reused per request (inference cost is server-side anyway).
const FEATURES = (() => {
  const frame = [];
  for (let i = 0; i < 450; i++) frame.push(Math.random() * 2 - 1);
  const win = [];
  for (let t = 0; t < 20; t++) win.push(frame);
  return win;
})();
const FEATURES_BODY = JSON.stringify({ features: FEATURES });

// Per-VU credentials (module scope persists across iterations within a VU).
let vuUser = null;
let vuToken = null;

function username() {
  return `load_${__VU}_${Date.now().toString(36)}`.slice(0, 30);
}

function ensureUser() {
  if (vuToken) return vuToken;
  if (!vuUser) {
    vuUser = {
      username: username(),
      email: `load_${__VU}_${uuidv4().slice(0, 8)}@k6load.dev`,
      password: 'LoadTest!234',
    };
  }
  const r = http.post(`${BASE}/api/auth/register`, JSON.stringify(vuUser), { headers: JSON_HEADERS, tags: { name: 'register' } });
  if (r.status === 200) registered.add(1);
  if (r.status !== 200 && r.status !== 400) {
    errorRate.add(1);
    return null;
  }
  const l = http.post(`${BASE}/api/auth/login`,
    JSON.stringify({ username: vuUser.username, password: vuUser.password }),
    { headers: JSON_HEADERS, tags: { name: 'login' } });
  const ok = check(l, { 'login 200': (x) => x.status === 200 });
  errorRate.add(!ok);
  if (!ok) return null;
  vuToken = l.json('access_token');
  return vuToken;
}

function authHeaders() {
  const t = ensureUser();
  return t ? { ...JSON_HEADERS, Authorization: `Bearer ${t}` } : JSON_HEADERS;
}

function hit(name, url, headers) {
  const r = http.get(url, { headers, tags: { name }, timeout: '30s' });
  const ok = check(r, { [`${name} 2xx/401`]: (x) => x.status >= 200 && x.status < 500 });
  errorRate.add(!ok || r.status >= 500);
  return r;
}

// ---------- scenario bodies ----------

export function authFlow() {
  const u = {
    username: username(),
    email: `auth_${__VU}_${uuidv4().slice(0, 8)}@k6load.dev`,
    password: 'LoadTest!234',
  };
  const reg = http.post(`${BASE}/api/auth/register`, JSON.stringify(u), { headers: JSON_HEADERS, tags: { name: 'register' } });
  const regOk = check(reg, { 'register 200/400': (x) => x.status === 200 || x.status === 400 });
  errorRate.add(!regOk);
  if (reg.status === 200) registered.add(1);

  const l = http.post(`${BASE}/api/auth/login`,
    JSON.stringify({ username: u.username, password: u.password }),
    { headers: JSON_HEADERS, tags: { name: 'login' } });
  const loginExpected = reg.status === 200 ? 200 : 401;
  const ok = check(l, { 'login status': (x) => x.status === loginExpected });
  errorRate.add(!ok);
  sleep(1);
}

export function apiFlow() {
  const h = authHeaders();
  hit('categories', `${BASE}/api/gestures/categories`, h);
  sleep(0.3);
  hit('gestures', `${BASE}/api/gestures`, h);
  sleep(0.3);
  hit('gestures_daily', `${BASE}/api/gestures/daily`, h);
  sleep(0.3);
  hit('levels', `${BASE}/api/lessons/levels`, h);
  sleep(0.3);
  hit('profile', `${BASE}/api/user/profile`, h);
  sleep(0.3);
  hit('daily_tasks', `${BASE}/api/daily-tasks/`, h);
  sleep(1);
}

export function mlPredictHttp() {
  const r = http.post(`${BASE}/ml/predict`, FEATURES_BODY, {
    headers: JSON_HEADERS, tags: { name: 'ml_predict' }, timeout: '60s',
  });
  httpPredict.add(r.timings.duration);
  const ok = check(r, {
    'predict 200': (x) => x.status === 200,
    'has label': (x) => x.status === 200 && !!x.json('label'),
  });
  errorRate.add(!ok);
  sleep(0.5);
}

export function mlPredictWs() {
  const url = `${WS_BASE}/ml/ws/predict`;
  const res = ws.connect(url, { tags: { name: 'ws_predict' } }, function (socket) {
    socket.on('open', () => {
      socket.send(FEATURES_BODY);
      socket.setInterval(() => socket.send(FEATURES_BODY), 2000);
    });
    socket.on('message', (msg) => {
      let m;
      try { m = JSON.parse(msg); } catch (e) { return; }
      if (m.inference_ms !== undefined) {
        wsRtt.add(m.inference_ms);
      }
      if (m.error) errorRate.add(1);
    });
    socket.setTimeout(() => socket.close(), 28000);
  });
  check(res, { 'ws 101': (x) => x && x.status === 101 });
  sleep(1);
}
