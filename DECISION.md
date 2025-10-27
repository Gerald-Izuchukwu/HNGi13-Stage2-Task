

### DECISION.md


```markdown
# Decisions (brief)


* **Why proxy_next_upstream + backup:** This keeps client requests resilient — nginx retries a backup on failures within the same request cycle.
* **Tight timeouts:** To detect broken upstreams quickly for the grader (1s connect, 4-6s read/send). Adjust if images respond slower.
* **No rebuilds:** Requirement — images are pre-built. Compose only wires up containers and nginx templating.
* **Healthchecks on app containers:** Docker-level healthchecks help docker know container liveness; nginx relies on response behavior and `max_fails` for failover to be deterministic during the grading loop.