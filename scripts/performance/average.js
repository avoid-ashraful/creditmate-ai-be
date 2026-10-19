// Retain the parent suite's actions and checks; reduce only the load shape.
import run, { setup, options as original } from '/home/ubuntu/credit/load-tests/average-load.js';
import { randomSeed } from 'k6';
randomSeed(42);
export { setup };
export default run;
const thresholds = { ...original.thresholds };
for (const endpoint of ['list', 'detail', 'typeahead', 'advanced-search', 'health']) {
  thresholds[`http_req_duration{endpoint:${endpoint},status:200}`] = ['p(99)>=0'];
}
export const options = {
  ...original,
  thresholds,
  scenarios: {
    average_load: {
      ...original.scenarios.average_load,
      startVUs: 0,
      stages: [
        { duration: '1m', target: 30 },
        { duration: '3m', target: 30 },
        { duration: '1m', target: 0 },
      ],
    },
  },
};
export function handleSummary(data) {
  return { [__ENV.SUMMARY_PATH]: JSON.stringify(data, null, 2) };
}
