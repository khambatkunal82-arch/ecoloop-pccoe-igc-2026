# EcoLoop — PCCOE IGC 2026 Final UI

Full-stack industrial circular economy demo with two role-based portals.

## Demo login
- Admin: `admin` / `admin123`
- Factory: `factory` / `factory123`

## Admin portal
Dashboard, Factories, Resources, Matches, Forecasts, Optimization, OpenStreetMap, Impact & Analytics, System Controls, Profile.

## Factory portal
Dashboard, My Factory, Waste & Supply, Demand, Exchange Opportunities, My Matches, Forecasts, Map, My Impact, Profile.

## Run
```bash
docker compose build --no-cache
docker compose up -d
docker compose ps
```
Open `http://EC2_PUBLIC_IP:5173`.

Do not use `docker compose down -v` if you want to keep PostgreSQL data.

## Functional flow
Factory registration → admin approval → factory login → publish supply/demand → forecast → compatibility → OR-Tools optimization → matches → map → impact.

Data is synthetic/illustrative for demonstration. CO₂ figures are estimated avoided emissions, not measured emissions.
