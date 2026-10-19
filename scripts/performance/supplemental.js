// The upstream suite does not exercise banks or comparison by ids.
import { check, sleep } from 'k6';
import { get, fetchCardIds } from '/home/ubuntu/credit/load-tests/lib.js';
export const options = {
  vus: 1,
  duration: '30s',
  thresholds: {
    http_req_failed: ['rate<0.01'],
    'http_req_duration{endpoint:banks,status:200}': ['p(99)<500'],
    'http_req_duration{endpoint:compare,status:200}': ['p(99)<500'],
  },
  summaryTrendStats: ['med', 'p(95)', 'p(99)'],
};
export function setup() { return { ids: fetchCardIds(3) }; }
export default function(data) {
  for (const [endpoint, path] of [
    ['banks', '/api/v1/banks/'],
    ['compare', '/api/v1/credit-cards/?ids=' + data.ids.join(',')],
  ]) {
    const response = get(__ENV.BASE_URL + path, endpoint);
    check(response, { '200': r => r.status === 200 });
  }
  sleep(1);
}
export function handleSummary(data) {
  return { [__ENV.SUMMARY_PATH]: JSON.stringify(data, null, 2) };
}
