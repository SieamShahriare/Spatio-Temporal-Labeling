# Spatiotemporal Annotation Tool

A web application for annotating text passages with Event and Time spans, visualizing them on a timeline, and computing Allen's Interval Algebra relations.

---

## Quick Start

### 1. Backend (FastAPI)

```bash
cd backend
pip install -r requirements.txt

# Create .env with your NeonDB URL:
echo "DATABASE_URL=postgresql://user:pass@host/db?sslmode=require" > .env

# Apply schema to NeonDB:
psql $DATABASE_URL -f migrations/schema.sql

# Start server:
uvicorn main:app --reload --port 8000
```

### 2. Frontend (Next.js)

```bash
cd spatiotemporal-labeling

# Create .env.local:
echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > .env.local

# Install and run:
pnpm install
pnpm dev
```

Open **http://localhost:3000**.

---

## Deployment (free tier)

| Part     | Host                  | Config                                   |
|----------|-----------------------|------------------------------------------|
| Database | Neon (free)           | Already hosted                           |
| Backend  | Render (free web svc) | `render.yaml` (Blueprint)                |
| Frontend | Vercel (Hobby)        | Root directory `spatiotemporal-labeling` |

The frontend proxies `/backend/*` to the API (see `next.config.ts`), so auth cookies stay first-party.

**Backend (Render):** New → Blueprint → pick this repo. Render reads `render.yaml` and prompts for
`DATABASE_URL`, `LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY`. Free services sleep after 15 min idle
(first request takes ~1 min to wake).

**Frontend (Vercel):** Import the repo, set Root Directory to `spatiotemporal-labeling`, and add env vars:

```
NEXT_PUBLIC_API_URL=/backend
BACKEND_URL=https://<your-render-service>.onrender.com
```

Secrets live only in the Render/Vercel dashboards. Never commit `.env` files (they are gitignored).

---

## User Flow

1. **Landing Page** — Enter username, paste stem text → click **Start Labeling**
2. **Step 1: Label Text** — Select text spans, assign as Event (E1, E2…) or Time (T1, T2…)
3. **Step 2: Timeline** — Drag/resize blocks on the 0–100 narrative scale; use manual inputs for precision
4. **Step 3: Matrix** — View auto-computed Allen's Algebra relation matrix; unlock to override cells manually
5. **Mark Done & Exit** — Saves everything to NeonDB, returns to landing page

---

## Allen's Algebra Encoding

| Code | Relation    | Symbol | Inverse |
|------|-------------|--------|---------|
| +1   | precedes    | <      | -1      |
| +2   | meets       | m      | -2      |
| +3   | overlaps    | o      | -3      |
| +4   | starts      | s      | -4      |
| +5   | during      | d      | -5      |
| +6   | finishes    | f      | -6      |
| +7   | equals      | =      | +7      |

---

## File Structure

```
labeling/
├── backend/
│   ├── main.py             # FastAPI endpoints
│   ├── database.py         # asyncpg connection pool
│   ├── models.py           # Pydantic schemas
│   ├── allen/
│   │   ├── relations.py    # compute_relation(), build_matrix()
│   │   └── validate.py     # transitivity_check()
│   ├── migrations/
│   │   └── schema.sql      # Postgres schema
│   └── requirements.txt
│
└── spatiotemporal-labeling/   # Next.js frontend
    ├── app/
    │   ├── page.tsx           # Landing page
    │   └── annotate/[session_id]/page.tsx
    ├── components/
    │   ├── TextLabeler.tsx    # Span selection & highlighting
    │   ├── Timeline.tsx       # Drag timeline with manual inputs
    │   └── AllenMatrix.tsx    # Matrix table with review/override
    └── lib/
        ├── api.ts             # API fetch helpers
        └── types.ts           # TypeScript types
```
