# Host Scan Policy — On-call Runbook

> **Audience:** anyone responding to "the scanner stopped finding matches on
> dealer X" or "BD spend looks weird this week".
> **System under management:** `host_scan_policy` table + `host_policy_service.py`
> + `render_strategies.py` ladder.
> **Last verified:** 2026-05-05 against `main`.

This is the "what do I run, what do I look at, and how do I fix it" doc for
the per-hostname adaptive render-strategy system. Read the top section once
to orient; jump to the symptom you're seeing for an action sequence.

---

## What the system does (one paragraph)

Every dealer hostname gets a row in `host_scan_policy` keyed by lowercased
hostname. The row records which render strategy the runner should use for
that host — `playwright_desktop` (cheap default) up through `unlocker_only`
(every page goes via Bright Data) and finally `unreachable` (don't bother).
After every scan, `host_policy_service.record_host_outcomes` aggregates per-host
outcomes from `pipeline_stats.blocked_details`, increments a confidence counter
on consecutive failures, and **auto-promotes** the strategy one rung up after
`PROMOTE_THRESHOLD = 2` failed scans in a row. A successful scan resets the
counter. There is no auto-demotion — once a host has proven it needs a stealthier
renderer, it stays there until an operator manually demotes it.

---

## The strategy ladder

In escalation order. Each rung is "what we try when the previous one keeps
failing":

| Tier | Strategy                      | What it does                                                                                  | Cost per page                                  |
|-----:|-------------------------------|-----------------------------------------------------------------------------------------------|------------------------------------------------|
|    0 | `playwright_desktop`          | Local Playwright Chromium, desktop UA. Default for unseen hosts.                              | ~free (worker CPU only)                        |
|    1 | `playwright_mobile_first`     | Playwright with iPhone UA + viewport. Sometimes bypasses bot rules that key on desktop UA.    | ~free                                          |
|    2 | `playwright_then_unlocker`    | One Playwright shot; if blocked, fall through to BD on the same page.                         | ~free unless BD fires (~$0.0015 / unlock)      |
|    3 | `unlocker_only`               | Skip Playwright entirely. Every page goes via BD — best for hosts with hard WAFs (rent.cat.com). | ~$0.0015 per page                              |
|    4 | `unreachable`                 | Don't even try. Used when even BD repeatedly returns no usable HTML.                          | $0 (rung short-circuits before any API call)   |

The promotion order is defined by `render_strategies.PROMOTION_ORDER` in
`backend/app/services/render_strategies.py`. The valid CHECK constraint values
are enforced by migration 031.

---

## Quick health checks

### 1. What's the current policy for a specific host?

```sql
SELECT
  hostname, strategy, waf_vendor, confidence, last_outcome,
  last_block_reason, last_http_status,
  last_seen_at, last_promoted_at, manual_override
FROM host_scan_policy
WHERE hostname = 'rent.cat.com';
```

What to look at:

- `strategy`: where the host currently sits on the ladder.
- `confidence`: consecutive-failure streak. `0` means the last scan succeeded;
  `1` means one failed scan since last success; `2` is the auto-promote
  trigger and you should see a recent `last_promoted_at`.
- `last_outcome`: `images` (success), `blocked` (WAF rejection), `timeout`,
  `crashed`, `empty` (rendered but no extractable images).
- `last_block_reason`: short string from the runner. Common values:
  `brightdata_http_400`, `brightdata_response_too_large`,
  `brightdata_url_template_placeholder`, `playwright_navigation_timeout`,
  `akamai_challenge_page`.
- `manual_override`: when `true`, auto-promotion is disabled for this host.

### 2. Hosts that auto-promoted recently

```sql
SELECT
  hostname, strategy, waf_vendor, last_outcome, last_promoted_at
FROM host_scan_policy
WHERE last_promoted_at > now() - interval '7 days'
ORDER BY last_promoted_at DESC;
```

### 3. Hosts on `unlocker_only` or `unreachable` (every scan costs money)

```sql
SELECT
  hostname, strategy, waf_vendor,
  success_count_30d, blocked_count_30d, timeout_count_30d,
  last_outcome, last_seen_at, manual_override
FROM host_scan_policy
WHERE strategy IN ('unlocker_only', 'unreachable')
ORDER BY blocked_count_30d DESC;
```

### 4. Hosts that haven't been scanned in a while (stale)

```sql
SELECT hostname, strategy, last_seen_at
FROM host_scan_policy
WHERE last_seen_at < now() - interval '30 days'
ORDER BY last_seen_at NULLS FIRST;
```

These are candidates for cleanup. They aren't actively costing anything (no
scan = no spend) but the strategy may be wildly out of date if/when scanning
resumes.

### 5. Bright Data spend correlated with a host

`host_scan_policy` doesn't store cost; cross-reference with the per-scan
`cost.line_items` JSON on `scan_jobs`:

```sql
SELECT
  sj.id, sj.created_at,
  jsonb_path_query_array(
    sj.cost_breakdown,
    '$.line_items[*] ? (@.vendor == "brightdata_unlocker")'
  ) AS bd_items
FROM scan_jobs sj
WHERE sj.created_at > now() - interval '24 hours'
  AND sj.cost_breakdown @> '{"by_vendor":{"brightdata_unlocker":0}}' = false
ORDER BY sj.created_at DESC
LIMIT 20;
```

Look in the `meta` of each `bd_items` element for the `target` URL — that's
the dealer page that triggered the BD call.

---

## Symptom → action

### "Scanner finds zero matches on dealer X all of a sudden"

1. Get the hostname from the dealer's `website_url`.
2. Run **Health check #1**.
3. Branch on `strategy`:
   - `playwright_desktop` / `mobile_first`: the host got upgraded mid-scan
     or this is just the local renderer struggling. Look at the latest
     `pipeline_stats.blocked_details` row for the dealer to see the actual
     `outcome` and `reason` per page. If most pages are `blocked`, the next
     scan will auto-promote (confidence will rise to 2). If you want to
     accelerate, see **"Manually promote a host"** below.
   - `playwright_then_unlocker`: BD is firing as a fallback. Check
     `pipeline_stats.cost.by_vendor.brightdata_unlocker` for the most recent
     scan to confirm BD is being called and succeeding. If BD requests
     succeed but `matched_new` is 0, this is a matcher problem, not a
     rendering problem — escalate to the AI funnel (`pipeline_stats.below_threshold`,
     `claude_errors`).
   - `unlocker_only`: BD is the only path. If you also see BD failures
     (`blocked_count_30d` rising, `last_block_reason: brightdata_*`), the
     WAF has broken our BD config — see **"BD itself is failing"**.
   - `unreachable`: we've given up on this host. If the client says it
     should work, see **"Demote a host that recovered"**.

### "Bright Data spend looks too high"

1. Run **Health check #3** to find every host on `unlocker_only` /
   `unreachable`. Each one costs ~$0.0015 per page per scan.
2. Cross-reference scan frequency: a host on `unlocker_only` scanned daily
   with 15 pages = ~$0.022/day per host. Multiply by however many hosts and
   the scan frequency to get monthly spend.
3. If a host's WAF was relaxed (you can confirm by hitting it from your
   browser and getting a clean response), demote it back to
   `playwright_desktop` per **"Demote a host that recovered"**.

### "BD itself is failing — every unlock returns an error"

Triage by the `last_block_reason` value:

| `last_block_reason`                                  | What it means                                                                  | Action                                                                                                                                                              |
|------------------------------------------------------|--------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `brightdata_unconfigured`                            | `BRIGHTDATA_API_TOKEN` or `BRIGHTDATA_UNLOCKER_ZONE` missing in env.           | Set the secrets in Render / your secret manager. Restart the worker. Smoke test on next scan re-enables the rung.                                                   |
| `brightdata_auth_401` / `brightdata_auth_403`        | BD rejected our credentials. Rung self-disables for 5 min, then retries.       | Verify the token in the BD dashboard hasn't been rotated/revoked. If it has, update the secret and `kill -HUP` (or just wait — the smoke test re-enables it).        |
| `brightdata_http_400`                                | BD got a request shape it didn't like.                                         | Look at the URL — is it well-formed? Check `_normalize_target_url` rejected reasons (`brightdata_url_template_placeholder` / `brightdata_url_too_long` / etc.).     |
| `brightdata_http_429`                                | BD rate-limited us.                                                            | Lower scan concurrency (`MAX_CONCURRENT_DEALERS` env). Should self-recover within a scan or two.                                                                    |
| `brightdata_timeout`                                 | BD didn't respond within 60 s.                                                 | Usually transient. If it persists across multiple hosts, BD is having an outage — check status.brightdata.com.                                                       |
| `brightdata_response_too_large`                      | Upstream host returned >8 MB HTML (or >25 MB image). Cap at `_MAX_UNLOCKER_*`. | Investigate that single host — almost always a misconfigured page returning a directory listing or a CDN attack. Pin the host to `unreachable` if needed.            |
| `brightdata_empty_response`                          | BD returned 200 but a near-empty body.                                         | The unlocker didn't wait for JS to render. Sometimes self-clears on retry; if persistent, the page may need a different BD zone (residential vs datacenter).       |
| `brightdata_disabled_by_smoke_test`                  | The boot-time smoke test failed; rung is short-circuited.                      | Check API logs for the smoke-test error. Most common cause: `BRIGHTDATA_API_TOKEN` env var has trailing whitespace or is missing entirely.                          |

### "A scan promoted a host I didn't expect"

1. Run **Health check #1** for the host.
2. Look at `last_promoted_at`. The scan that promoted it is the one that
   completed just before that timestamp.
3. Run:
   ```sql
   SELECT id, status, started_at, completed_at,
          pipeline_stats->'blocked_details' AS blocked
   FROM scan_jobs
   WHERE completed_at BETWEEN <last_promoted_at> - interval '5 minutes'
                          AND <last_promoted_at> + interval '1 minute'
   ORDER BY completed_at DESC;
   ```
4. The `blocked` JSON shows every page on every dealer that produced a
   non-success outcome. If you can see real WAF rejections there, the
   promotion was correct. If the pages are timing out for a non-WAF
   reason (e.g. our worker is OOMing), demote and fix the actual
   problem — see **"Demote a host that recovered"**.

---

## Manual interventions

### Manually promote a host (skip the 2-scan confidence wait)

When the client tells you "site X is now Akamai-protected, just go straight
to BD":

```sql
UPDATE host_scan_policy
SET strategy        = 'unlocker_only',
    confidence      = 0,
    manual_override = true,
    last_promoted_at = now(),
    notes           = COALESCE(notes, '') || E'\nManual promote ' || now()::text || ' — reason: ...',
    updated_at      = now()
WHERE hostname = 'rent.cat.com';
```

Setting `manual_override = true` pins the row — auto-promotion will not
move it from here. The next successful scan won't auto-demote either
(there's no auto-demote at all).

### Demote a host that recovered

When you've verified the WAF is gone (browse the page from a clean IP,
get a normal response):

```sql
UPDATE host_scan_policy
SET strategy        = 'playwright_desktop',
    confidence      = 0,
    manual_override = false,
    last_outcome    = NULL,
    last_block_reason = NULL,
    notes           = COALESCE(notes, '') || E'\nManual demote ' || now()::text,
    updated_at      = now()
WHERE hostname = 'rent.cat.com';
```

Set `manual_override = false` so if the WAF comes back the system
re-promotes automatically. Leave it `true` only if you've decided to
permanently pin this host — e.g., a site we know we will *always* go
direct on.

### Pin a host to `unreachable` (stop spending on it entirely)

When BD itself can't render the host and it's not worth investigating:

```sql
UPDATE host_scan_policy
SET strategy        = 'unreachable',
    confidence      = 0,
    manual_override = true,
    notes           = COALESCE(notes, '') || E'\nPinned unreachable ' || now()::text || ' — reason: ...',
    updated_at      = now()
WHERE hostname = '<host>';
```

The `unreachable` rung short-circuits before any API call, so this
host produces zero spend going forward. The dealer will appear in
`pipeline_stats.dealers_blocked` on every scan; that's intentional —
it's the operator's reminder that the host is shelved.

### Reset 30-day counters (after a long-running incident)

The `success_count_30d` / `blocked_count_30d` / `timeout_count_30d`
columns are running totals. If a one-time incident skews them and you
want a clean baseline:

```sql
UPDATE host_scan_policy
SET success_count_30d = 0,
    blocked_count_30d = 0,
    timeout_count_30d = 0,
    updated_at = now()
WHERE hostname = '<host>';
```

There's no automatic 30-day rollover — these counters grow forever
unless reset. Operator hygiene; not on the critical path.

### Wipe a host row entirely (force re-probe from scratch)

```sql
DELETE FROM host_scan_policy WHERE hostname = '<host>';
```

The next scan that touches this host will trigger
`host_policy_service.preflight_probe` — a single HEAD request that
sniffs the WAF vendor and seeds a fresh row with the suggested
strategy. Use this when you suspect the row is corrupted or wildly
out of sync with reality.

---

## How to verify the system is working

Sanity check after any of the above interventions:

1. **Trigger a scan** that hits the host you changed (start a campaign
   scan or wait for the next scheduled run).
2. **Watch the API logs** for `Preflight <host>` (only on first scan
   of unseen hosts) and `Host <host> auto-promoted: X -> Y` lines —
   either confirms the promotion path is alive.
3. **Check the resulting `pipeline_stats.blocked_details`**:
   - For each dealer on this host, the `pages` array should have
     `outcome: images` for the pages that worked, and a structured
     `reason` for any that didn't.
4. **Re-run Health check #1** post-scan. `confidence` should be `0`
   on success, `last_outcome: images`, and `last_seen_at` should be
   within the last few minutes.

---

## Things this runbook deliberately does NOT do

- **Mass operations.** There's no "demote all unlocker_only hosts at
  once" command and there shouldn't be — every host has its own story.
  If you find yourself wanting to bulk-update, write a one-off SQL
  script, peer-review it, and document the reason in a `log.md` entry.
- **Schema changes.** Adding a column or constraint is a migration
  (see `supabase/migrations/`), not a runbook step.
- **Render strategy invention.** Adding a new strategy means touching
  `render_strategies.py`, the migration's CHECK constraint, and the
  promotion order, plus reading the existing tests. Out of scope for
  on-call.

## Glossary

- **WAF** — Web Application Firewall. Akamai, Cloudflare, Imperva,
  Sucuri, Fastly, CloudFront. Detected by header fingerprints in
  `host_policy_service._WAF_FINGERPRINTS`.
- **Promotion** — moving a host one rung up the ladder
  (`playwright_desktop` → `playwright_mobile_first`, etc.). Automatic
  when `confidence >= PROMOTE_THRESHOLD`; manual via the SQL above.
- **Smoke test** — boot-time check in `unlocker_service.smoke_test`.
  POSTs `https://example.com/` to BD; on failure, disables the BD rung
  for 5 minutes and logs at ERROR.
- **`pipeline_stats.blocked_details`** — per-scan rollup of every page
  that didn't return `images`. Source of truth for `record_host_outcomes`.
