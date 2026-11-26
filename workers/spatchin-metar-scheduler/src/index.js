import {
  createGitHubWorkflowScheduler,
  REQUEST_TIMEOUT_MS,
} from '../../shared/github-workflow-scheduler.js';

const WORKFLOW = 'metar-update.yml';
const USER_AGENT = 'spatchin-metar-scheduler';
const scheduler = createGitHubWorkflowScheduler({ workflow: WORKFLOW, userAgent: USER_AGENT });

const DISPATCH_URL = scheduler.dispatchUrl;
const dispatchWorkflow = scheduler.dispatchWorkflow;

export default scheduler.worker;
export { DISPATCH_URL, REQUEST_TIMEOUT_MS, USER_AGENT, WORKFLOW, dispatchWorkflow };
