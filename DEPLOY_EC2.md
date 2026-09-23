# EC2 deployment

1. Copy this ZIP to Ubuntu EC2.
2. SSH into EC2.
3. Install Docker if needed:
```bash
sudo apt update
sudo apt install -y docker.io docker-compose-v2 unzip
sudo systemctl enable --now docker
sudo usermod -aG docker $USER
```
Reconnect after `usermod`.

4. Extract:
```bash
cd ~
unzip ecoloop-pccoe-final.zip
cd ecoloop-pccoe-final
```

5. Start:
```bash
docker compose up --build -d
```

6. Verify:
```bash
docker compose ps
docker compose logs --tail=50 backend
docker compose logs --tail=50 frontend
```

7. Security Group inbound:
- TCP 22: My IP
- TCP 5173: your demo audience / 0.0.0.0/0 if necessary
- TCP 8000: optional, only for Swagger/API testing
- Do not expose 5432.

8. Open:
`http://EC2_PUBLIC_IP:5173`

The frontend uses a Vite reverse proxy for `/api`, so the browser does not try to call `localhost:8000` on the user's own computer.

## Demo login
Admin: `admin` / `admin123`
Factory operator: `factory` / `factory123`
