Veriscope runs a **four-provider LLM fleet, complexity-routed**. Different pipeline steps
have genuinely different difficulty, and paying reasoning-grade latency for a formatting
step is waste. Unconfigured providers are skipped automatically, so the system works with
one key and works better with four.

## The fleet

| Provider | Default model | Routed to | RPM |
| --- | --- | --- | --- |
| Groq | `llama-3.3-70b-versatile` | Fast, low-stakes steps | 25 |
| Gemini | `gemini-2.0-flash` | Structured mid-tier JSON | 10 |
| DeepSeek | `deepseek-chat` | Synthesis and judging — strongest free reasoning | 20 |
| OpenRouter | `meta-llama/llama-3.3-70b-instruct:free` | Spillover | 15 |
| NVIDIA | `meta/llama-3.3-70b-instruct` | Optional additional capacity | 40 |

Chains live in `app/llm/router.py` under `ROUTING`.

## Minimum viable configuration

One key is enough to run the product:

```bash
GROQ_API_KEY=...
```

Adding a second materially improves reliability, because a rate-limited provider falls
through to the next chain entry instead of failing the node.

```bash
GROQ_API_KEY=...
GEMINI_API_KEY=...
DEEPSEEK_API_KEY=...
OPENROUTER_API_KEY=...
```

## Rate limits and caching

Each provider carries its own requests-per-minute budget, enforced with a Redis throttle
bucket. Identical calls are cached:

```bash
LLM_CACHE_TTL_SECONDS=86400
```

:::tip Determinism where it matters
Two nodes run at temperature 0 on purpose — `evidence_schema` and `report_architect`. The
same question must yield the same evidence schema and the same report structure, or two
runs of one question stop being comparable. Do not raise their temperature to get
"more creative" structure.
:::

## The local ML models are not LLMs

Embeddings, reranking and entailment run locally and are not part of the fleet. This is a
correctness decision, not a cost decision: the verification gate must not depend on a
third-party API that can rate-limit, change model versions, or go down mid-run.

```bash
ML_EMBEDDINGS_ENABLED=true
ML_RERANK_ENABLED=true
ML_NLI_ENABLED=true
EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
RERANK_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2
NLI_MODEL=MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli
```

:::danger The reranker is not an entailment model
A cross-encoder scores *relevance*. Using it as a proxy for entailment was the specific
mistake v2 was built to correct. Relevance says a passage is on-topic; entailment says the
sentence follows from it. Only the second is a verification signal.
:::

## Offloading inference

For deployments where the API container should stay light, point the ML stack at a
separate inference service:

```bash
INFERENCE_SERVICE_URL=http://models:8100
INFERENCE_SERVICE_TIMEOUT=120
```

The `models` compose profile runs exactly that service.

## External source keys

| Key | Needed for |
| --- | --- |
| `SEMANTIC_SCHOLAR_API_KEY` | Higher Semantic Scholar rate limits (works without). |
| `GITHUB_TOKEN` | Repository evidence, when practitioner sources are enabled. |
| `TAVILY_API_KEY` | Whitelisted blog search. |

Practitioner sources are **off by default** (`PRACTITIONER_SOURCES_ENABLED=false`). When
enabled, they are kept in a separate evidence class and never share a drafting context
with scholarly sources.

## Related

- [Configuration](#/docs/reference/configuration) — every setting in one table.
- [The verification gate](#/docs/explanation/verification-gate)
