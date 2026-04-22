# MySpotify v4 — Brainstorm: Hide cold-miss latency behind user intent

This document captures the next round of improvements after v3 shipped. The v3
work (resolver + ffmpeg stream-copy + next-in-queue prefetch + upgraded
`ffmpeg` + Deno for the JS solver) cut YouTube playback startup from 10–20 s
to **~400 ms for any track that's been played before** and to **~10 s for the
first play of a fresh track**.

Every uncached track still pays the full 10 s YouTube tax because that's the
real cost of scraping YouTube: fetch the watch page, download the player JS,
run Deno to solve the signature/n challenge, and only then get a playable URL.
This can't be made free, but it can be **paid up-front while the user is still
deciding what to click**.

Related prior docs:
- [features-v3.md](features-v3.md) — resolver + passthrough + prefetch work.
- [system_specification.md](system_specification.md) — authoritative API/ops.
- [docker.md](docker.md) — image build/rebuild + runtime checks.

---

## Implementation status

| Item | Status | Notes |
| :--- | :----- | :---- |
| **§3 — Improved resolver logging (phased timing)** | **In testing (unshipped)** | Implemented: `_PhaseRecorder` + `_DispatchLogger` + `_recorder_ctx` in `yt_resolver.py`. Log line now includes `cache=miss clients=tv,web timing=webpage@180,client_cfg:tv@260,player_api:tv@3500,...`. Cache-hit DEBUG log added. Unit tests: 6 new tests in `test_yt_resolver.py` (14 total). Web UI bumped to `v2.9.19`. **Pending rebuild + manual validation on Pi 5.** |
| §4 — `prefetch_youtube(mode="resolve")` + `POST /prefetch?mode=` | Backlog | Do after §3 numbers come in. |
| §5 — Hover/focus prefetch, search-top-N prefetch | Backlog | Depends on §4. |
| §7 — Deferred items (parallel race, persistent cache, predictive prefetch, drop `mweb`) | Backlog | Re-evaluate after phased log data. |

---

## 1. Where the cold-miss 10 seconds actually goes

Roughly, per uncached resolve (warm backend, Deno already alive):

| Phase | Typical cost | Notes |
| :---- | :----------- | :---- |
| yt-dlp extractor init | 100–300 ms | One-time per process (already paid after first resolve). |
| Fetch watch page (HTTPS RT to Google) | 300–800 ms | Network round-trip, variable. |
| Fetch player JS | 500–1500 ms | Large file (multi-MB). yt-dlp caches it on disk. |
| **Run Deno signature/n solver** | **1500–4000 ms** | Spawn + parse + execute. Biggest single cost. |
| Fetch player API JSON | 300–800 ms | Per-client (tv / web / mweb). |
| Format selection + return | < 50 ms | Cheap. |

The numbers above are estimates from the Pi 5 logs; we should *measure* them
instead (see §3 — phased timing log).

---

## 2. The core idea: prefetch-on-intent

We already have `POST /api/v1/tracks/{track_id}/prefetch`. Today it:

1. Resolves via `yt_resolver`.
2. Downloads the full audio to `TEMP_DIR` as a local file.
3. Promotes it to cache after the usual "play-count" threshold (same as normal
   streaming).

This is exactly what we want for **next-in-queue**, where the user is all but
certain to play the track. It is **too expensive** (3–5 MB per track, often
wasted) for "the user is *looking at* this track".

Split prefetch into two modes:

| Mode | What it does | When to use | Cost |
| :--- | :----------- | :---------- | :--- |
| `resolve` | Call `yt_resolver.resolve()` only. Warms the 5-hour URL cache; no disk I/O, no full download. | Hover/focus, search results render | ~10 s CPU/network per *new* track, zero disk |
| `download` (current behavior) | Resolve + download to `TEMP_DIR`. | Next-in-queue (already implemented in v3) | ~10 s + 3–5 MB |

A click on a track that had `resolve`-prefetch triggered any time in the last
5 hours hits the in-memory resolver cache (ms), so first-byte is bounded by
ffmpeg/httpx start-up — roughly the same ~400 ms we already see for
second-play.

---

## 3. Improved resolver logging (phased timing)

**Highest-signal, lowest-risk change.** Before tuning anything further we
should *know* which phase of the 10 s is biting on the Pi specifically.
Right now `yt_resolver` logs one line per resolve:

```
yt_resolver: resolved video_id=GBUWZeItAOM ext=mp4 acodec=mp4a.40.2 elapsed_ms=11991
```

Proposed richer log line (same INFO level, structured k=v):

```
yt_resolver: resolved video_id=GBUWZeItAOM ext=mp4 acodec=mp4a.40.2 \
  elapsed_ms=11991 phase_ms=[init:250,watch:680,js:420,solver:4200,api:900,pick:35] \
  client=tv cache=miss
```

Instrument the `_resolve_sync` call in `yt_resolver.py` with:

- `ydl.add_postprocessor` and/or custom `YoutubeDL` hooks so we can timestamp
  each phase without forking yt-dlp.
- Fall-back path: wrap the `extract_info` call with a `ProgressHook` and
  aggregate the `downloading_*` events into buckets.

Also emit:

- Resolver cache events: `hit` / `miss` / `stale-refresh`.
- Final client actually used (not the configured list).

Why this is worth doing first:

1. It's a read-only change — zero behavioral risk.
2. It converts "resolve takes 10 s" (useless) into "solver: 4200 ms, api: 900
   ms, watch: 680 ms" (actionable).
3. It lets us validate whether hover-prefetch really hides the cost before we
   invest in the UI work.

---

## 4. Server work

### 4.1 `streamer.prefetch_youtube(track_id, *, mode="download")`

```python
async def prefetch_youtube(
    track_id: str,
    *,
    mode: Literal["resolve", "download"] = "download",
    library_user_id: Optional[str] = None,
) -> str:
    ...
```

- `mode="resolve"` — fire-and-forget call to `yt_resolver.resolve(track_id)`
  under a lightweight semaphore (separate from the download semaphore).
  Returns `"resolved" | "cached" | "failed"`. **No disk writes.**
- `mode="download"` — identical to today's implementation (next-in-queue
  prefetch).

### 4.2 `POST /api/v1/tracks/{track_id}/prefetch?mode=resolve|download`

Default `mode=download` to preserve current client behavior. Rate-limit
`resolve` more generously than `download` (e.g., 600/min vs 120/min) since it
has no disk cost.

### 4.3 Config

```python
# Dedicated knob so hover-prefetch can't blow past it even if the UI goes wild
PREFETCH_RESOLVE_MAX_CONCURRENT: int = 4
# Per-client rate-limit (guardrail only; semaphore is the real back-pressure)
PREFETCH_RESOLVE_RATE_LIMIT_PER_MIN: int = 600
# Auto-prefetch top-N YouTube search results (0 disables)
PREFETCH_ON_SEARCH_TOP_N: int = 2
```

### 4.4 Persistent resolver cache (deferred — §7.2 below)

---

## 5. Client work

### 5.1 Hover / focus prefetch (desktop + keyboard)

In `player.js` (or wherever track rows are wired up):

- On `mouseenter` of a YouTube track row, start a 250 ms timer. If it fires
  (user didn't leave), call `API.prefetch(id, { mode: 'resolve' })`.
- On `mouseleave`, clear the timer. Do **not** cancel an in-flight request —
  it's cheap and likely useful within 5 h anyway.
- On `focus` (keyboard nav), same as hover, no debounce.

Guard:

- Skip if `track.is_cached` or `source_type !== 'youtube'`.
- Keep a tiny `Set<string>` of "already hover-prefetched this session" so we
  don't spam the backend for tracks the user flicks the mouse over repeatedly.

### 5.2 Search-results top-N prefetch (mobile + tap-happy users)

When `/search` returns results, find the first N YouTube tracks that aren't
cached and fire `API.prefetch(id, { mode: 'resolve' })` for each. N from
`/api/v1/config` (new field), default `2`.

Runs once per search result render.

### 5.3 Next-in-queue (unchanged)

`API.prefetch(id, { mode: 'download' })` ~3 s after play starts. This is the
v3 behavior; we keep it.

---

## 6. Expected impact

Assuming `resolve` cost = 10 s cold, < 50 ms warm (resolver cache hit):

| Scenario | Before v4 | After v4 |
| :------- | :-------- | :------- |
| First play after restart, unhovered | ~10 s | ~10 s (no change — can't beat YouTube) |
| Click on track hovered for ≥ 1 s | ~10 s | ~0.5–1.5 s |
| Tap top result right after search | ~10 s | ~0.5–1.5 s (if hit within ~10 s) |
| Click on track seen but not hovered | ~10 s | ~10 s (same as before) |
| Next-in-queue auto-advance | ~0.5 s (v3 download) | ~0.5 s (unchanged) |
| Replay of something resolved < 5 h ago | ~0.5 s | ~0.5 s (unchanged) |

Realistic share of user actions covered: hover/focus + search-top-N should
eliminate cold-miss latency for **80–95 %** of plays. The residual cases
("click without any prior UI interaction") are rare on desktop; on mobile
they'll normally match the search-top-N path.

---

## 7. Deferred / backlog

### 7.1 Parallel client race (`tv` vs `web`)

Fire both clients in parallel, take the winner, cancel the loser. Saves
1–3 s per cold miss. Complex (yt-dlp doesn't expose this cleanly) and risks
YouTube rate-limiting. Revisit if the phased log shows client order is the
dominant cost.

### 7.2 Persistent resolver cache (SQLite `resolved_urls` table)

Columns: `video_id PRIMARY KEY`, `url`, `ext`, `acodec`, `http_headers (json)`,
`expires_at`. Loaded into the in-memory TTL cache on startup, written on each
successful resolve. Survives container restarts. Probably ~50 lines of code.

Trigger for building this: users complain after `docker compose restart`.

### 7.3 Predictive prefetch from listening history

"User plays track X → top-3 next-likely tracks are Y, Z, W → prefetch them."
Needs a playcount/co-occurrence model. Probably not worth it until the
listening corpus grows.

### 7.4 Drop `mweb` from the default client list

`mweb` requires a PO token we don't provide, so when yt-dlp falls through to
it the log fills with WARNINGs even though `tv` already succeeded.
Low-priority cosmetic fix. Change default to `tv,web`.

---

## 8. Suggested sequencing

1. **§3 Phased timing log** — do this first. It's two tiny commits and it
   informs everything else. Validate on the Pi against a few unique videos.
2. **§4.1 + §4.2 `mode=resolve` server endpoint** — smallest backend change
   that unlocks client work.
3. **§5.1 Hover/focus prefetch** — single biggest UX win.
4. **§5.2 Search-top-N** — covers the mobile/tap-fast case.
5. Measure again with the §3 log. If solver cost is still the dominant phase,
   consider §7.1; otherwise stop here.

---

## 9. Risks & mitigations

- **Backend load from over-eager hover prefetch.** Mitigated by
  `PREFETCH_RESOLVE_MAX_CONCURRENT`, dedup via resolver cache, and
  "already-prefetched this session" Set on the client.
- **YouTube rate-limiting / bot detection from too many resolves.** Per-user
  rate-limit on the endpoint, and the resolve-only mode reuses the same
  `yt_resolver` path (so both `download` and `resolve` calls share the same
  resolver cache — no duplicate work).
- **Data/CPU cost on mobile.** Resolve-only mode has no download cost; the
  only cost is the backend's YouTube round-trip, invisible to the client.
- **Regression in next-in-queue prefetch.** Kept literally unchanged —
  `mode="download"` is the default and its code path is the v3 one.
