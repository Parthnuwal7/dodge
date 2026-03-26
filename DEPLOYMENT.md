# Deployment Guide (Hugging Face + Vercel)

## Architecture
- Backend: Hugging Face Space (Docker)
- Frontend: Vercel (Vite/React)
- Repository: single repo with `backend/` and `frontend/`

## 1. Deploy Backend to Hugging Face Spaces

### Space settings
- SDK: `Docker`
- Repository: this repo
- Branch: your deployment branch

### Required files
- Root `Dockerfile` is used to start FastAPI from `backend/`.

### Secrets / Variables in Space
Set these as Space secrets:
- `NEO4J_URI`
- `NEO4J_USER`
- `NEO4J_PASSWORD`
- `OPENROUTER_API_KEY`
- `OPENROUTER_BASE_URL`
- `LLM_MODEL`
- `GROQ_API_KEY`
- `GROQ_MODEL`
- `DATA_DIR` (if needed in hosted environment)
- `CYPHER_TEMPLATE_DIR` (optional if default works)
- `LOG_LEVEL`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `SUPABASE_CHAT_TABLE`

### Health check
After deploy, verify:
- `https://<space-name>.hf.space/api/v1/health`
- `https://<space-name>.hf.space/api/v1/query/chat/status`

## 2. Deploy Frontend to Vercel

### Project setup
- Import this repo in Vercel
- Set **Root Directory** to `frontend`
- Build command: `npm run build`
- Output directory: `dist`

### Environment variables (Vercel)
Set:
- `VITE_API_BASE_URL=https://<space-name>.hf.space/api/v1`

The frontend reads this from `frontend/src/api/client.ts`. If missing, it defaults to `/api/v1` for local proxy.

### SPA routing
`frontend/vercel.json` rewrites all routes to `index.html` so `/ingest` works on refresh.

## 3. Local Development

### Backend
From `backend/`:
- `./venv/Scripts/python.exe -m uvicorn app.main:app --reload --env-file .env --port 8000`

### Frontend
From `frontend/`:
- `npm run dev`

Vite proxy forwards `/api` to `http://localhost:8000` via `frontend/vite.config.ts`.

## 4. Common Issues
- Frontend cannot call backend in production:
  - Check `VITE_API_BASE_URL` in Vercel
  - Confirm backend URL ends with `/api/v1`
- Chat storage disabled:
  - Verify `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY`
  - Verify `chat_logs` table exists
- `No module named supabase`:
  - Ensure `supabase` is in `backend/requirements.txt` and backend rebuilds
