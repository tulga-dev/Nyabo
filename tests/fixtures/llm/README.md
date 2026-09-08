# LLM fixtures for MockLlmClient

`<purpose>/<key>.json` where `purpose` is `extract`, `classify`, `question`, `eval` and
`key` is `nyabo_mn.agent.llm_client.hash_parts(user_parts)` (sha256 over the text parts,
images by their bytes). `default.json` answers any call without a keyed fixture.

Shapes:

```json
{"data": {...}}                                                        // structured()
{"text": "...", "tool_calls": [{"name": "...", "arguments": {...}}]}   // with_tools()
```

Keys starting with `_` are comments. Real client data never goes here.
