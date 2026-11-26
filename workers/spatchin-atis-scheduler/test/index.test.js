import worker, {
  DISPATCH_URL,
  USER_AGENT,
  WORKFLOW,
  dispatchWorkflow,
} from '../src/index.js';
import { schedulerContract } from '../../shared/scheduler-contract.js';

schedulerContract({
  worker,
  dispatchWorkflow,
  dispatchUrl: DISPATCH_URL,
  workflow: WORKFLOW,
  userAgent: USER_AGENT,
});
