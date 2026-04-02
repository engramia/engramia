# Admin Dashboard — Architecture & Design (Phase 5.3)

> Goal: transform Engramia from "just a library" into a commercially credible
> product with visible ROI.  The dashboard is the **P0 blocker** for commercial
> positioning (roadmap.md:114).

---

## 1. Design Principles

| Principle | Rationale |
|-----------|-----------|
| **Static build, zero runtime** | `next export` produces pure HTML/JS/CSS — bundled into the Docker image or served via CDN.  No Node.js server in production. |
| **API-first** | Every screen is powered by existing `/v1/*` endpoints.  Dashboard never touches DB directly. |
| **RBAC-aware** | UI adapts to the authenticated user's role (reader → owner).  Buttons/actions hidden when permission is missing. |
| **Lightweight** | Minimal dependencies.  No heavy component library.  Tailwind CSS + a small chart library. |
| **Progressive disclosure** | Overview first, then drill-down.  Don't overwhelm the operator with every metric at once. |

---

## 2. Technology Stack

```
┌─────────────────────────────────────────────────────┐
│  Next.js 15 (App Router, static export)             │
│  ├── React 19                                       │
│  ├── TypeScript 5.x                                 │
│  ├── Tailwind CSS 4                                 │
│  ├── Recharts 2  (charts — lightweight, composable) │
│  ├── TanStack Query v5  (data fetching + caching)   │
│  ├── Lucide React  (icons, tree-shakeable)          │
│  └── clsx + tailwind-merge  (conditional classes)   │
└─────────────────────────────────────────────────────┘
```

**Why Next.js static export (not SPA)?**
- File-based routing out of the box
- `output: "export"` produces a `dashboard/out/` folder — zero Node.js runtime
- Image optimization, code splitting, lazy routes for free
- Can be served by Caddy / FastAPI `StaticFiles` / S3+CloudFront

**Why not a full SSR app?**
- Adds Node.js runtime dependency to prod
- Engramia is Python-first — keep the operational surface small
- Auth is Bearer token (client-side), not cookie/session

---

## 3. Project Structure

```
dashboard/
├── package.json
├── tsconfig.json
├── tailwind.config.ts
├── next.config.ts            # output: "export", basePath: "/dashboard"
├── public/
│   └── favicon.svg
├── src/
│   ├── app/
│   │   ├── layout.tsx        # Shell: sidebar + topbar + auth gate
│   │   ├── page.tsx          # → redirect to /dashboard/overview
│   │   ├── login/
│   │   │   └── page.tsx      # API key entry
│   │   ├── overview/
│   │   │   └── page.tsx      # KPI cards + ROI chart + health
│   │   ├── patterns/
│   │   │   ├── page.tsx      # Pattern explorer (search + table)
│   │   │   └── [key]/
│   │   │       └── page.tsx  # Pattern detail + classify + delete
│   │   ├── analytics/
│   │   │   └── page.tsx      # ROI rollups + recall breakdown + trends
│   │   ├── evaluations/
│   │   │   └── page.tsx      # Eval history timeline + variance alerts
│   │   ├── keys/
│   │   │   └── page.tsx      # API key management (CRUD)
│   │   ├── governance/
│   │   │   └── page.tsx      # Retention + export + scoped delete
│   │   ├── jobs/
│   │   │   └── page.tsx      # Async job monitor
│   │   └── audit/
│   │       └── page.tsx      # Audit log viewer (admin+)
│   ├── components/
│   │   ├── ui/               # Primitives: Button, Card, Badge, Table, Modal, Input
│   │   ├── layout/
│   │   │   ├── Sidebar.tsx   # Nav with role-gated items
│   │   │   ├── Topbar.tsx    # Project switcher + health dot + logout
│   │   │   └── Shell.tsx     # Sidebar + Topbar + content slot
│   │   ├── charts/
│   │   │   ├── ROIScoreChart.tsx      # Line chart: roi_score over time
│   │   │   ├── RecallBreakdown.tsx    # Stacked bar: duplicate/adapt/fresh
│   │   │   ├── EvalScoreTrend.tsx     # Line chart: p50/p90 eval scores
│   │   │   └── ReuseTierPie.tsx       # Donut: reuse tier distribution
│   │   ├── patterns/
│   │   │   ├── PatternTable.tsx       # Sortable table with filters
│   │   │   ├── PatternDetail.tsx      # Full pattern view + metadata
│   │   │   └── PatternSearch.tsx      # Semantic search input
│   │   ├── keys/
│   │   │   ├── KeyTable.tsx           # List with status badges
│   │   │   ├── KeyCreateModal.tsx     # Create form + one-time secret display
│   │   │   └── KeyRotateModal.tsx     # Rotate confirmation + new secret
│   │   └── jobs/
│   │       ├── JobTable.tsx           # Status-filterable job list
│   │       └── JobDetail.tsx          # Result/error display
│   ├── lib/
│   │   ├── api.ts            # Typed API client (fetch wrapper + Bearer auth)
│   │   ├── auth.ts           # Token storage (localStorage) + role extraction
│   │   ├── permissions.ts    # Role → permission set (mirrors backend)
│   │   ├── hooks/
│   │   │   ├── useAuth.ts           # Auth context + role
│   │   │   ├── useHealth.ts         # Polling deep health
│   │   │   ├── useMetrics.ts        # GET /metrics
│   │   │   ├── usePatterns.ts       # Recall + pattern ops
│   │   │   ├── useAnalytics.ts      # ROI rollups + events
│   │   │   ├── useKeys.ts           # Key CRUD
│   │   │   ├── useJobs.ts           # Job polling
│   │   │   └── useGovernance.ts     # Retention + export + delete
│   │   └── types.ts          # TypeScript types matching API schemas
│   └── styles/
│       └── globals.css       # Tailwind base + custom tokens
├── Dockerfile                # Multi-stage: npm build → copy out/ to nginx/caddy
└── README.md
```

---

## 4. Page Architecture

### 4.1 Login (`/login`)

```
┌──────────────────────────────────┐
│         Engramia Logo            │
│                                  │
│  ┌────────────────────────────┐  │
│  │  API Key                   │  │
│  │  engramia_sk_____________  │  │
│  └────────────────────────────┘  │
│  ┌────────────────────────────┐  │
│  │  API URL (optional)        │  │
│  │  https://api.engramia.dev  │  │
│  └────────────────────────────┘  │
│                                  │
│        [ Connect ]               │
│                                  │
│  Validates via GET /v1/health    │
│  Stores token in localStorage    │
│  Extracts role from GET /v1/keys │
└──────────────────────────────────┘
```

**Auth flow:**
1. User enters API key + optional base URL
2. Dashboard calls `GET /v1/health` with `Authorization: Bearer <key>`
3. On 200 → store key + URL in `localStorage`, redirect to `/overview`
4. On 401 → show error
5. Role detection: `GET /v1/keys` → find key matching `key_prefix` → extract `role`

No cookies, no sessions, no OAuth.  API key is the only credential.

---

### 4.2 Overview (`/overview`)

The landing page after login.  Shows the operational pulse at a glance.

```
┌─────────────────────────────────────────────────────────────────┐
│  Sidebar    │  Overview                                         │
│             │                                                   │
│  Overview ● │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌────────┐ │
│  Patterns   │  │ ROI     │ │ Patterns│ │ Reuse   │ │ Avg    │ │
│  Analytics  │  │ Score   │ │ Count   │ │ Rate    │ │ Eval   │ │
│  Evals      │  │  7.2    │ │  1,247  │ │  68%    │ │  8.1   │ │
│  Keys  🔑   │  │ ▲ +0.4 │ │ ▲ +23  │ │ ▲ +5%  │ │ ▲ +0.3│ │
│  Governance │  └─────────┘ └─────────┘ └─────────┘ └────────┘ │
│  Jobs       │                                                   │
│  Audit  🔒  │  ┌──────────────────────┐ ┌──────────────────┐   │
│             │  │  ROI Score (Weekly)   │ │  System Health   │   │
│  ─────────  │  │                      │ │                  │   │
│  Health: ●  │  │   ╱─╲    ╱──         │ │  Storage   ● ok  │   │
│  v0.5.4     │  │  ╱   ╲──╱            │ │  LLM       ● ok  │   │
│             │  │ ╱                     │ │  Embedding ● ok  │   │
│             │  │ ─────────────────     │ │  Uptime  4d 12h  │   │
│             │  └──────────────────────┘ └──────────────────┘   │
│             │                                                   │
│             │  ┌──────────────────────┐ ┌──────────────────┐   │
│             │  │  Recall Breakdown    │ │  Recent Activity │   │
│             │  │  ██████░░ 68% reuse  │ │  • learn  2m ago │   │
│             │  │  ████░░░░ dup: 41%   │ │  • recall 5m ago │   │
│             │  │  ██░░░░░░ adapt: 27% │ │  • eval   8m ago │   │
│             │  │  ░░░░░░░░ fresh: 32% │ │  • key    1h ago │   │
│             │  └──────────────────────┘ └──────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

**Data sources:**
- KPI cards → `GET /v1/metrics` + `GET /v1/analytics/rollup/daily`
- ROI chart → `GET /v1/analytics/events?limit=500` (aggregate client-side by day)
- Health → `GET /v1/health/deep` (poll every 30s)
- Recall breakdown → `GET /v1/analytics/rollup/daily` → `.recall`
- Activity → `GET /v1/analytics/events?limit=10`

---

### 4.3 Pattern Explorer (`/patterns`)

```
┌──────────────────────────────────────────────────────────────────┐
│  Patterns                                                        │
│                                                                  │
│  ┌─────────────────────────────┐  Classification  Source         │
│  │ 🔍 Search by task...        │  [All ▾]        [All ▾]        │
│  └─────────────────────────────┘                                 │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────────┐│
│  │ Task                    │ Score │ Reuse │ Class.  │ Source │ ││
│  ├──────────────────────────────────────────────────────────────┤│
│  │ Create REST API for ... │  8.4  │  12×  │ internal│  api   │ ││
│  │ Parse CSV with valid... │  7.1  │   5×  │ public  │  sdk   │ ││
│  │ Generate test suite ... │  9.0  │  23×  │ confid. │  api   │ ││
│  │ ...                     │       │       │         │        │ ││
│  └──────────────────────────────────────────────────────────────┘│
│                                                                  │
│  Showing 1–25 of 1,247          [← Prev]  [Next →]              │
└──────────────────────────────────────────────────────────────────┘
```

**Search:** `POST /v1/recall` with user query → display matches ranked by similarity.

**Pattern detail** (`/patterns/[key]`):
- Full task text, code (syntax-highlighted), eval score, reuse count
- Metadata: classification, source, run_id, author, created_at
- Actions: Classify (PUT /governance/patterns/{key}/classify), Delete (DELETE /patterns/{key})
- Permission: delete requires `patterns:delete` (admin+), classify requires `governance:write` (admin+)

**Note on pagination:** The current API lacks cursor-based pagination.
For Phase 5.3, use `POST /v1/recall` with `limit=50` for search results and
`GET /v1/analytics/events` with `limit` + `since` for event-based listings.
Full pagination is a Phase 5.8+ improvement (see Section 10).

---

### 4.4 Analytics (`/analytics`)

The commercial value proposition page.  This is what sells Engramia.

```
┌──────────────────────────────────────────────────────────────────┐
│  ROI Analytics                    Window: [Hourly|Daily|Weekly]  │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │  ROI Score Trend                                         │    │
│  │  10 ┤                                                    │    │
│  │   8 ┤         ●───●                                      │    │
│  │   6 ┤    ●───●     ╲●───●───●───●                       │    │
│  │   4 ┤●──●                                                │    │
│  │   2 ┤                                                    │    │
│  │   0 ┼───┼───┼───┼───┼───┼───┼───┼───                    │    │
│  │     Mon Tue Wed Thu Fri Sat Sun Mon                      │    │
│  └──────────────────────────────────────────────────────────┘    │
│                                                                  │
│  ┌────────────────────────┐ ┌────────────────────────────┐      │
│  │  Recall Outcomes       │ │  Eval Score Distribution   │      │
│  │                        │ │                            │      │
│  │  ┌──┐ ┌──┐ ┌──┐      │ │  p50: ████████░░ 7.8       │      │
│  │  │██│ │▓▓│ │░░│      │ │  p90: ██████████ 9.2       │      │
│  │  │██│ │▓▓│ │░░│      │ │  avg: ████████░░ 8.1       │      │
│  │  └──┘ └──┘ └──┘      │ │                            │      │
│  │  dup  adapt fresh     │ │                            │      │
│  │  41%   27%   32%      │ │                            │      │
│  └────────────────────────┘ └────────────────────────────┘      │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │  Top Patterns by Reuse                                   │    │
│  │  # │ Task (truncated)                │ Reuse │ Score     │    │
│  │  1 │ Create REST API for user...     │  23×  │  9.0      │    │
│  │  2 │ Parse and validate CSV...       │  18×  │  8.4      │    │
│  │  3 │ Generate pytest suite for...    │  15×  │  8.7      │    │
│  └──────────────────────────────────────────────────────────┘    │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │  Event Stream                              [Load More]   │    │
│  │  12:04  recall  similarity=0.94  tier=duplicate  key=... │    │
│  │  12:02  learn   eval_score=8.5   key=patterns/a3f2...    │    │
│  │  11:58  recall  similarity=0.71  tier=adapt      key=... │    │
│  └──────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────┘
```

**Data sources:**
- ROI trend → multiple `GET /v1/analytics/rollup/{window}` calls (or events aggregate)
- Recall outcomes → `rollup.recall` (duplicate_hits, adapt_hits, fresh_misses)
- Eval distribution → `rollup.learn` (p50, p90, avg)
- Top patterns → `GET /v1/analytics/events?limit=1000` → client-side group by pattern_key, sort by count
- Event stream → `GET /v1/analytics/events?limit=50&since=<ts>`

**Window switcher:** hourly / daily / weekly — triggers `POST /v1/analytics/rollup` if no cached rollup exists, then `GET /v1/analytics/rollup/{window}`.

---

### 4.5 Evaluations (`/evaluations`)

```
┌──────────────────────────────────────────────────────────────────┐
│  Evaluation History                                              │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │  Eval Scores Over Time (from learn events)               │    │
│  │  10 ┤       ●  ●                                        │    │
│  │   8 ┤  ●  ●  ●  ●  ●  ●                                │    │
│  │   6 ┤●                                                   │    │
│  │   4 ┤                                                    │    │
│  │   0 ┼──────────────────────                              │    │
│  └──────────────────────────────────────────────────────────┘    │
│                                                                  │
│  ⚠ Variance Alert: 2 evaluations in last 24h had variance > 1.5 │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │  Top Recurring Issues (Feedback)                         │    │
│  │  1. Missing error handling for edge cases        (12×)   │    │
│  │  2. Insufficient input validation                 (8×)   │    │
│  │  3. No docstrings on public methods               (5×)   │    │
│  └──────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────┘
```

**Data sources:**
- Score timeline → `GET /v1/analytics/events?limit=500` → filter kind=learn, plot eval_score
- Variance alerts → client-side: flag events where variance would be high (or from eval response cache)
- Feedback → `GET /v1/feedback?limit=10`

---

### 4.6 API Keys (`/keys`)

```
┌──────────────────────────────────────────────────────────────────┐
│  API Keys                                     [ + Create Key ]   │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ Name        │ Prefix       │ Role   │ Last Used │ Actions │  │
│  ├────────────────────────────────────────────────────────────┤  │
│  │ Production  │ engramia_sk… │ editor │ 2min ago  │ 🔄  🗑  │  │
│  │ CI/CD       │ engramia_sk… │ editor │ 1h ago    │ 🔄  🗑  │  │
│  │ Admin       │ engramia_sk… │ admin  │ 5min ago  │ 🔄  🗑  │  │
│  │ Read-only   │ engramia_sk… │ reader │ never     │ 🔄  🗑  │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│  Requires role: admin+    (reader/editor see this page disabled) │
└──────────────────────────────────────────────────────────────────┘
```

**Create modal:** name, role (dropdown), max_patterns (optional), expires_at (optional).
On create → display full key **once** with copy button + warning.

**Rotate modal:** confirmation dialog → `POST /v1/keys/{id}/rotate` → display new key once.

**Revoke:** confirmation dialog → `DELETE /v1/keys/{id}`.

**Endpoints:** `GET /v1/keys`, `POST /v1/keys`, `DELETE /v1/keys/{id}`, `POST /v1/keys/{id}/rotate`

---

### 4.7 Governance (`/governance`)

```
┌──────────────────────────────────────────────────────────────────┐
│  Data Governance                                                 │
│                                                                  │
│  Retention Policy                                                │
│  ┌────────────────────────────────────────────┐                  │
│  │  Current: 365 days (source: project)       │                  │
│  │  [ Change to: [___] days ]  [ Save ]       │                  │
│  │                                            │                  │
│  │  [ Apply Now (dry run) ]  [ Apply Now ]    │                  │
│  │  Last applied: 2026-03-28, purged 12       │                  │
│  └────────────────────────────────────────────┘                  │
│                                                                  │
│  Data Export                                                     │
│  ┌────────────────────────────────────────────┐                  │
│  │  Classification: [All ▾]                   │                  │
│  │  [ Export NDJSON ]                         │                  │
│  │  Streams via GET /governance/export        │                  │
│  └────────────────────────────────────────────┘                  │
│                                                                  │
│  Danger Zone                                                     │
│  ┌────────────────────────────────────────────┐                  │
│  │  Delete Project Data                       │                  │
│  │  [ Delete All Data for Project ]  ⚠        │                  │
│  │  Requires: governance:delete (admin+)      │                  │
│  └────────────────────────────────────────────┘                  │
└──────────────────────────────────────────────────────────────────┘
```

---

### 4.8 Jobs (`/jobs`)

```
┌──────────────────────────────────────────────────────────────────┐
│  Async Jobs                     Filter: [All ▾]  [ Refresh 🔄 ] │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ ID (short) │ Operation │ Status    │ Created   │ Actions  │  │
│  ├────────────────────────────────────────────────────────────┤  │
│  │ a3f2…      │ evaluate  │ ● running │ 2min ago  │          │  │
│  │ b1c4…      │ roi_rollup│ ✅ done   │ 15min ago │ [View]   │  │
│  │ d5e6…      │ import    │ ❌ failed │ 1h ago    │ [View]   │  │
│  │ f7a8…      │ compose   │ ⏳ pending│ 2min ago  │ [Cancel] │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│  Auto-refresh: every 5s for running jobs                         │
└──────────────────────────────────────────────────────────────────┘
```

**Job detail:** expandable row or separate modal showing `result` (JSON) or `error` (string).

---

### 4.9 Audit Log (`/audit`)

Visible only to admin+ roles.

```
┌──────────────────────────────────────────────────────────────────┐
│  Audit Log                                                       │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ Time       │ Event          │ Actor    │ Resource │ IP     │  │
│  ├────────────────────────────────────────────────────────────┤  │
│  │ 12:04:23   │ PATTERN_DELETE │ key:a3f2 │ pat/b1c4 │ 1.2.… │  │
│  │ 12:01:15   │ KEY_CREATED    │ key:d5e6 │ key:f7a8 │ 1.2.… │  │
│  │ 11:58:02   │ RATE_LIMITED   │ —        │ —        │ 5.6.… │  │
│  │ 11:45:30   │ AUTH_FAILURE   │ —        │ —        │ 9.8.… │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│  Note: Requires new GET /v1/audit endpoint (see Section 10)      │
└──────────────────────────────────────────────────────────────────┘
```

---

## 5. Component Architecture

### 5.1 Data Flow

```
                     ┌──────────────┐
                     │  localStorage│
                     │  - api_key   │
                     │  - base_url  │
                     │  - role      │
                     └──────┬───────┘
                            │
                     ┌──────▼───────┐
                     │  AuthProvider │  (React Context)
                     │  - token     │
                     │  - role      │
                     │  - baseUrl   │
                     │  - logout()  │
                     └──────┬───────┘
                            │
                     ┌──────▼───────┐
                     │ QueryClient  │  (TanStack Query)
                     │ - staleTime  │
                     │ - refetch    │
                     └──────┬───────┘
                            │
              ┌─────────────┼─────────────┐
              │             │             │
        ┌─────▼────┐ ┌─────▼────┐ ┌─────▼────┐
        │useMetrics│ │useAnalyti│ │useKeys   │   ... hooks
        │          │ │cs       │ │          │
        └─────┬────┘ └─────┬────┘ └─────┬────┘
              │             │             │
              └─────────────┼─────────────┘
                            │
                     ┌──────▼───────┐
                     │  api.ts      │  (fetch wrapper)
                     │  - get()     │
                     │  - post()    │
                     │  - delete()  │
                     │  + Bearer hdr│
                     └──────┬───────┘
                            │
                     ┌──────▼───────┐
                     │  Engramia    │
                     │  REST API    │
                     │  /v1/*       │
                     └──────────────┘
```

### 5.2 API Client (`lib/api.ts`)

```typescript
// Typed, minimal fetch wrapper — no axios dependency
class EngramiaClient {
  constructor(private baseUrl: string, private token: string) {}

  private async request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const res = await fetch(`${this.baseUrl}${path}`, {
      method,
      headers: {
        "Authorization": `Bearer ${this.token}`,
        "Content-Type": "application/json",
      },
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new ApiError(res.status, err.detail ?? "Unknown error");
    }
    return res.json();
  }

  // Typed methods matching API surface
  health()      { return this.request<HealthResponse>("GET", "/v1/health"); }
  healthDeep()  { return this.request<DeepHealthResponse>("GET", "/v1/health/deep"); }
  metrics()     { return this.request<MetricsResponse>("GET", "/v1/metrics"); }
  recall(req)   { return this.request<RecallResponse>("POST", "/v1/recall", req); }
  learn(req)    { return this.request<LearnResponse>("POST", "/v1/learn", req); }
  // ... all endpoints
}
```

### 5.3 Permission Gating (`lib/permissions.ts`)

```typescript
// Mirrors backend engramia/api/permissions.py exactly
const ROLE_PERMISSIONS: Record<string, Set<string>> = {
  reader: new Set(["health", "metrics", "recall", "feedback:read", "skills:search",
                   "jobs:list", "jobs:read", "analytics:read"]),
  editor: new Set([/* reader + */ "learn", "evaluate", "compose", "evolve",
                   "analyze_failures", "skills:register", "aging", "feedback:decay",
                   "jobs:cancel", "analytics:rollup"]),
  admin:  new Set([/* editor + */ "patterns:delete", "import", "export",
                   "keys:create", "keys:list", "keys:revoke", "keys:rotate",
                   "governance:read", "governance:write", "governance:admin",
                   "governance:delete"]),
  owner:  new Set(["*"]),
};

export function hasPermission(role: string, perm: string): boolean {
  const perms = ROLE_PERMISSIONS[role];
  if (!perms) return false;
  return perms.has("*") || perms.has(perm);
}
```

```tsx
// Usage in components
function DeleteButton({ patternKey }: { patternKey: string }) {
  const { role } = useAuth();
  if (!hasPermission(role, "patterns:delete")) return null;
  return <Button variant="danger" onClick={() => deletePattern(patternKey)}>Delete</Button>;
}
```

### 5.4 Sidebar Navigation (role-aware)

```typescript
const NAV_ITEMS = [
  { label: "Overview",    href: "/overview",    icon: LayoutDashboard, perm: "health" },
  { label: "Patterns",    href: "/patterns",    icon: Brain,           perm: "recall" },
  { label: "Analytics",   href: "/analytics",   icon: BarChart3,       perm: "analytics:read" },
  { label: "Evaluations", href: "/evaluations", icon: FlaskConical,    perm: "feedback:read" },
  { label: "Keys",        href: "/keys",        icon: Key,             perm: "keys:list" },
  { label: "Governance",  href: "/governance",  icon: Shield,          perm: "governance:read" },
  { label: "Jobs",        href: "/jobs",        icon: Cog,             perm: "jobs:list" },
  { label: "Audit",       href: "/audit",       icon: ScrollText,      perm: "governance:admin" },
];
// Items without permission are hidden from nav
```

---

## 6. Deployment Architecture

### Option A: Bundled with API (recommended for v1)

```
┌─────────────────────────────────────────────────┐
│  Docker Image (engramia:0.6.0)                  │
│                                                 │
│  ┌───────────────┐  ┌────────────────────────┐  │
│  │  FastAPI       │  │  /dashboard/ (static)  │  │
│  │  /v1/*         │  │  HTML/JS/CSS from      │  │
│  │  /dashboard/*  │──│  Next.js export        │  │
│  │  (StaticFiles) │  │                        │  │
│  └───────────────┘  └────────────────────────┘  │
└─────────────────────────────────────────────────┘
```

**FastAPI mount:**
```python
# engramia/api/app.py
from fastapi.staticfiles import StaticFiles
from pathlib import Path

dashboard_dir = Path(__file__).parent.parent.parent / "dashboard" / "out"
if dashboard_dir.exists():
    app.mount("/dashboard", StaticFiles(directory=str(dashboard_dir), html=True), name="dashboard")
```

**Dockerfile addition:**
```dockerfile
# --- Stage: dashboard build ---
FROM node:22-alpine AS dashboard
WORKDIR /app
COPY dashboard/package.json dashboard/package-lock.json ./
RUN npm ci
COPY dashboard/ .
RUN npm run build   # next build && next export → out/

# --- Stage: runtime (existing) ---
FROM python:3.12-slim AS runtime
# ... existing setup ...
COPY --from=dashboard /app/out /app/dashboard/out
```

**Caddyfile (no change needed)** — Caddy proxies everything to FastAPI, which serves both API and dashboard.

### Option B: Separate CDN (for scale)

```
                    ┌──────────────────┐
                    │  CloudFront / R2 │
   /dashboard/*  ──►│  Static HTML/JS  │
                    └──────────────────┘

                    ┌──────────────────┐
   /v1/*         ──►│  FastAPI (API)   │
                    └──────────────────┘
```

Use this when dashboard traffic is high or you want independent deploy cycles.
For Phase 5.3 v1, Option A is simpler and sufficient.

---

## 7. Data Refresh Strategy

| Page | Endpoint | Refresh | Technique |
|------|----------|---------|-----------|
| Overview KPIs | `/v1/metrics` | 30s | `refetchInterval` |
| Overview Health | `/v1/health/deep` | 30s | `refetchInterval` |
| Overview ROI | `/v1/analytics/rollup/daily` | 5min | `staleTime` |
| Analytics Trend | `/v1/analytics/events` | 60s | `staleTime` |
| Patterns | `/v1/recall` (search) | on demand | manual trigger |
| Keys | `/v1/keys` | on mutation | `invalidateQueries` |
| Jobs | `/v1/jobs` | 5s (if running) | conditional `refetchInterval` |
| Governance | `/v1/governance/retention` | on demand | manual |
| Audit | (new endpoint) | on demand | manual |

---

## 8. RBAC Visibility Matrix

| Page / Action | reader | editor | admin | owner |
|---------------|--------|--------|-------|-------|
| Overview (view) | ✅ | ✅ | ✅ | ✅ |
| Patterns (search) | ✅ | ✅ | ✅ | ✅ |
| Patterns (delete) | — | — | ✅ | ✅ |
| Patterns (classify) | — | — | ✅ | ✅ |
| Analytics (view) | ✅ | ✅ | ✅ | ✅ |
| Analytics (trigger rollup) | — | ✅ | ✅ | ✅ |
| Evaluations (view) | ✅ | ✅ | ✅ | ✅ |
| Keys (view list) | — | — | ✅ | ✅ |
| Keys (create/rotate/revoke) | — | — | ✅ | ✅ |
| Governance (view retention) | — | — | ✅ | ✅ |
| Governance (set/apply) | — | — | ✅ | ✅ |
| Governance (delete scope) | — | — | ✅ | ✅ |
| Governance (delete tenant) | — | — | — | ✅ |
| Jobs (view) | ✅ | ✅ | ✅ | ✅ |
| Jobs (cancel) | — | ✅ | ✅ | ✅ |
| Audit log | — | — | ✅ | ✅ |

---

## 9. Visual Design Tokens

```
Colors (dark-first, with light mode support):
  --bg-primary:    #0f1117   (slate-950)
  --bg-surface:    #1a1d27   (slate-900)
  --bg-elevated:   #252832   (slate-800)
  --border:        #2e3241   (slate-700)
  --text-primary:  #e2e8f0   (slate-200)
  --text-secondary:#94a3b8   (slate-400)
  --accent:        #6366f1   (indigo-500 — Engramia brand)
  --success:       #22c55e   (green-500)
  --warning:       #f59e0b   (amber-500)
  --danger:        #ef4444   (red-500)

Typography:
  --font-sans:  "Inter", system-ui, sans-serif
  --font-mono:  "JetBrains Mono", "Fira Code", monospace

Spacing: 4px base unit (Tailwind default)
Border radius: 8px (rounded-lg)
Shadows: minimal — borders preferred in dark mode
```

---

## 10. Backend Changes Required

The dashboard is API-first and the backend is nearly complete, but a few additions
would significantly improve the experience:

### 10.1 New: Audit Log Query Endpoint (P1)

```
GET /v1/audit?limit=50&since=<iso>&action=<filter>
Permission: governance:admin
Response: { events: AuditEvent[], total: int }
```

Currently audit events are written to DB (`audit.log_db_event()`) but there's
no read endpoint.  The dashboard Audit page needs this.

### 10.2 New: Pattern List Endpoint (P2)

```
GET /v1/patterns?limit=50&offset=0&classification=internal&source=api&sort_by=reuse_count
Permission: recall
Response: { patterns: PatternSummary[], total: int }
```

Currently the only way to browse patterns is via semantic search (`POST /v1/recall`).
A list/filter endpoint would power the Pattern Explorer table without requiring
a search query.

### 10.3 Enhancement: Top Patterns by Reuse (P2)

Either add to the rollup response or as a dedicated endpoint:
```
GET /v1/analytics/top-patterns?limit=10&window=daily
```

Currently achievable client-side by aggregating events, but expensive for large datasets.

### 10.4 Enhancement: CORS for Dashboard Origin (P1)

If dashboard is served from a different origin (CDN deployment), configure:
```
ENGRAMIA_CORS_ORIGINS=https://dashboard.engramia.dev
```

Not needed for bundled deployment (Option A) since same origin.

---

## 11. Implementation Phases

### Phase 5.3a — Skeleton + Auth + Overview (Week 1-2)

- [ ] Initialize Next.js project with Tailwind, TypeScript
- [ ] Build `api.ts` client + `AuthProvider` + login page
- [ ] Build Shell layout (Sidebar + Topbar)
- [ ] Build Overview page (KPI cards + health + ROI chart)
- [ ] Wire up `useMetrics`, `useHealth`, `useAnalytics` hooks
- [ ] Add permission gating in Sidebar

### Phase 5.3b — Core Pages (Week 2-3)

- [ ] Pattern Explorer (search via recall + table + detail view)
- [ ] Analytics page (ROI trend + recall breakdown + top patterns)
- [ ] Evaluations page (score timeline + feedback list)
- [ ] API Keys page (CRUD with one-time secret display)

### Phase 5.3c — Governance + Jobs + Polish (Week 3-4)

- [ ] Governance page (retention + export + scoped delete)
- [ ] Jobs page (status table + auto-refresh + cancel)
- [ ] Audit page (requires backend endpoint 10.1)
- [ ] Dark/light mode toggle
- [ ] Mobile responsive breakpoints
- [ ] Loading states, error boundaries, empty states

### Phase 5.3d — Deployment + Integration (Week 4)

- [ ] Add dashboard build stage to Dockerfile
- [ ] Mount static files in FastAPI (`app.py`)
- [ ] Update Caddyfile if needed
- [ ] Update docker-compose.prod.yml
- [ ] Add `npm run build` to CI
- [ ] Update README with dashboard screenshots
- [ ] Update roadmap.md Phase 5.3 as complete

---

## 12. File Inventory (Estimated)

```
~35 files total:
  9 pages (login, overview, patterns, patterns/[key], analytics,
           evaluations, keys, governance, jobs, audit)
  ~12 components (UI primitives, charts, domain-specific)
  ~8 hooks (auth, health, metrics, analytics, keys, jobs, governance, patterns)
  3 lib files (api.ts, auth.ts, permissions.ts)
  1 types file (types.ts)
  3 config files (next.config.ts, tailwind.config.ts, tsconfig.json)
```

Estimated bundle size: **~150-200 KB** gzipped (React + Recharts + Tailwind).

---

## 13. Non-Goals for Phase 5.3

- **No real-time WebSocket** — polling is sufficient for v1
- **No multi-tenant switcher** — dashboard operates in the scope of the authenticated key
- **No user management UI** — tenants/projects managed via API or CLI
- **No custom theming** — single brand theme (dark + light)
- **No i18n** — English only for v1
- **No offline support** — requires API connectivity
