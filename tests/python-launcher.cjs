'use strict';

function pythonCommand(env = process.env, platform = process.platform) {
  return env.PYTHON || (platform === 'win32' ? 'python' : 'python3');
}

module.exports = { pythonCommand };
