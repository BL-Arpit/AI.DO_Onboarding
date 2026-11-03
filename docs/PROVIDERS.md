# Pluggable chat providers

Edit `active_provider` in the selected TOML file and restart. Provider entries contain a kind, HTTPS base URL and the names of environment variables for credentials/model IDs. They do not contain secret values. You may set a non-secret `model = "account-model-id"` directly in the provider TOML entry; otherwise the named model environment variable is used. Additional entries with `kind="openai"` can target compatible HTTPS tool-calling APIs, subject to their protocol compatibility tests. There is no front-end model picker or redundant model badge.

| Kind | Protocol used | Credential header |
| --- | --- | --- |
| demo | Local deterministic parser | None |
| openai | POST /chat/completions with a function tool | Authorization: Bearer |
| gemini | POST /models/{model}:generateContent with function declarations | x-goog-api-key |
| claude | POST /messages with client tools | x-api-key, anthropic-version |

The Claude version header is configurable; the adapter defaults to the documented legacy-compatible `2023-06-01` contract. Use your provider's current compatible version/account policy. New model capabilities may need an adapter update; changing a model ID alone does not guarantee tool support.

The adapter has a 10-second connection and 45-second total request timeout, does not follow redirects, bypasses proxy environment variables, and sends credentials only to the server-configured HTTPS URL. Model-generated URLs cannot change that URL. The server validates and limits returned plans before proposing a mutation. OpenAI requests explicitly set `store=false`; retention behavior of any provider account must be reviewed separately by the operator.

Production rejects the demo provider. Demo supports documented command-style CRUD and guided missing-field collection; it is not presented as a pretrained or generative model. Real conversational understanding comes from the configured cloud model. No silent fallback executes actions under a different provider when a request fails.

Provider adapters are contract-tested with simulated upstream HTTP responses. Live credentials, rate limits, selected-model behavior, pricing and end-to-end cloud quality are not verified in this release.

Primary protocol references:

- https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create
- https://ai.google.dev/api/generate-content
- https://platform.claude.com/docs/en/api/messages
