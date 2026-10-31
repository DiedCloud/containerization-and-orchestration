import http from 'k6/http';
import { check } from 'k6';

export const options = {
  scenarios: {
    orders: {
      executor: 'constant-arrival-rate',
      rate: Number(__ENV.RATE || 10), timeUnit: '1s',
      duration: __ENV.DURATION || '10m',
      preAllocatedVUs: 10, maxVUs: 50,
    },
  },
  thresholds: {
    http_req_duration: ['p(95)<300'],
    http_req_failed: ['rate<0.01'],
    checks: ['rate>0.99'],
    dropped_iterations: ['count==0'],
  },
};
export default function () {
  const r = http.post(`${__ENV.BASE_URL || 'http://172.20.0.2:30080'}/order`,
    JSON.stringify({item: 'lab4-load', quantity: 1}),
    {headers: {'Content-Type': 'application/json'}, timeout: '5s'});
  check(r, {'order persisted (201 + id)': r => r.status === 201 && r.json('id') > 0});
}
