import assert from 'node:assert/strict';
import { findSelectableDefault, isSelectableDefault } from '../src/model-defaults.js';

const providers = { openai: { enabled: true }, claude: { enabled: true }, local: { enabled: false } };
const settings = {
  runtime: { default_model: 'router-default' },
  providers,
  models: [
    { id: 'router-default', provider: 'openai', display_name: 'Router Default', visible: true },
    { id: 'claude-child', provider: 'claude', display_name: 'Claude Child', visible: true },
    { id: 'disabled-local', provider: 'local', display_name: 'Disabled Local', visible: true },
  ],
};

assert.equal(isSelectableDefault(settings), true);
assert.equal(findSelectableDefault(settings)?.id, 'router-default');

settings.models[0].visible = false;
assert.equal(isSelectableDefault(settings), false);
assert.equal(findSelectableDefault(settings)?.id, 'claude-child');

settings.models[0].visible = true;
providers.openai.enabled = false;
assert.equal(isSelectableDefault(settings), false);
assert.equal(findSelectableDefault(settings)?.id, 'claude-child');

settings.models[1].visible = false;
assert.equal(findSelectableDefault(settings), null);
console.log('PASS default-model repair covers visibility, provider disable, and no-replacement cases');
