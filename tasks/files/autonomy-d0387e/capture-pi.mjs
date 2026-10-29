// Offline transport capture. Pass the pinned pi-ai api/anthropic-messages.js path.
import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';

globalThis.fetch = () => { throw new Error('Unexpected network transport'); };
const { stream } = await import(pathToFileURL(process.argv[2]).href);
const tool = { name: 'local_tool', description: 'Synthetic local tool', parameters: { type: 'object', properties: {} } };
const initial = { role: 'system', content: 'Synthetic system text', toolsAdded: [tool], timestamp: 0 };
const user = { role: 'user', content: 'Synthetic user text', timestamp: 1 };
const model = {
  id: 'claude-haiku-5-5', provider: 'anthropic', api: 'anthropic-messages',
  baseUrl: 'https://capture.invalid', reasoning: true, maxTokens: 2048,
  contextWindow: 100000, input: ['text'],
  cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
};
const cases = [
  ['plain', {}, [initial, user]],
  ['effort', { supportsMidConvoEffort: true, supportsMidConvoSystemMessages: true }, [initial, user]],
  ['inline', { supportsMidConvoSystemMessages: true, supportsMidConvoToolChanges: true },
    [initial, user, { role: 'system', content: 'Add tool', toolsAdded: [{ ...tool, name: 'later_tool' }], timestamp: 2 }]],
  ['fallback', { allowedFallbackModels: [{ model: 'outside-route' }] }, [initial, user]],
];
const captures = [];
for (const [id, compat, messages] of cases) {
  let calls = 0;
  const response = stream({ ...model, compat }, { messages }, {
    apiKey: 'synthetic-placeholder', env: {}, maxRetries: 0, thinkingEnabled: true,
    fetch: async (url, init) => {
      calls++;
      assert.equal(new URL(url).hostname, 'capture.invalid');
      assert.equal(typeof init.body, 'string');
      captures.push({ id, body: JSON.parse(init.body), beta: new Headers(init.headers).get('anthropic-beta') });
      return new Response(JSON.stringify({ type: 'error', error: { type: 'invalid_request_error', message: 'Offline capture complete' } }),
        { status: 400, headers: { 'content-type': 'application/json' } });
    },
  });
  const result = await response.result();
  assert.equal(calls, 1, `${id}: ${result.errorMessage}`);
  assert.equal(result.stopReason, 'error');
}
assert(captures[1].body.messages.some(m => m.role === 'system' && m.output_config?.effort === 'high'));
assert(captures[2].body.messages.some(m => Array.isArray(m.content) && m.content.some(b => b.type === 'tool_addition')));
assert.equal(captures[3].body.fallbacks[0].model, 'outside-route');
process.stdout.write(JSON.stringify(captures, null, 2) + '\n');
