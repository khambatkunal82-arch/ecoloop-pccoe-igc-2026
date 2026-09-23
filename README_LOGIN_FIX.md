# EcoLoop Login / Factory Sign-In Fix

The UI is intentionally unchanged. The fix is the Vite development proxy:
- `/api/*` -> `http://backend:8000`
- `/health` -> `http://backend:8000`

This allows the existing Admin Login and Factory Login tabs in the exact reference UI to reach FastAPI from the frontend container.

Demo accounts:
- Admin: `admin` / `admin123`
- Factory: `factory` / `factory123`

Factory Login selects the first ACTIVE factory from PostgreSQL and opens the Factory Portal.
