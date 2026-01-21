# Cost Optimization

## Strategies
- Use spot/preemptible nodes for `heavy-analysis` pool if tolerated.
- Keep analysis concurrency limited (`MAX_CONCURRENT_JOBS`).
- Right-size requests and limits based on observed metrics.

## Reasoning
Analysis jobs are bursty and expensive; isolating them keeps baseline costs predictable.
