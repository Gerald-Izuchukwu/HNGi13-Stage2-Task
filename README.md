# Blue/Green with Nginx Upstreams (Stage 2)


## What this repo provides
- Docker Compose setup with 3 services: nginx (public), app_blue (8081), app_green (8082).
- Nginx upstreams configured for primary/backup behavior, tight timeouts, and retries within a single client request.


## Quick start
1. Copy `.env.example` to `.env` and fill values for `BLUE_IMAGE` and `GREEN_IMAGE` and release ids.


2. (Optional) For local dev on Docker Desktop / Linux, prepare nginx upstream injection:
```sh
export ACTIVE_POOL=blue
./scripts/generate-upstream.sh
cp ./nginx/generated_default.conf ./nginx/conf.d/default.conf
```

3. Start services:

```bash
docker compose up -d
```

4. Verify baseline (blue active):

```bash
curl -i http://localhost:8080/version
```
# Expect 200 and headers: X-App-Pool: blue, X-Release-Id: <RELEASE_ID_BLUE>

5. Induce chaos on the active app (grader will do this, but you can test):
```bash
curl -X POST "http://localhost:8081/chaos/start?mode=error"
```

Then run repeated GETs against the public endpoint and observe nginx failing over to green with 0 client errors:
```bash
for i in $(seq 1 50); do curl -s -o /dev/null -w "%{http_code} %{redirect_url}\n" http://localhost:8080/version; done
```
6. Stop chaos:
```bash
curl -X POST "http://localhost:8081/chaos/stop"
```

##### Notes & behavior

Nginx is configured to forward X-App-Pool and X-Release-Id unchanged to clients using proxy_pass_header directives.

Primary upstreams use max_fails and fail_timeout tuned low (2 failures within 2s), so failover is quick.

proxy_next_upstream includes timeout and http_5xx so nginx will retry the backup within the same client request.

No app image builds are performed in this repo; images are provided via env vars.