# VPS Deployment Guide — IHP Design and Construction Platform

Complete, copy-paste guide to run the platform on any Ubuntu VPS (tested path:
Contabo / Hetzner / DigitalOcean, Ubuntu 22.04 or 24.04, 2+ vCPU, 4+ GB RAM,
20+ GB disk). The whole stack runs in Docker: **Postgres 16 (+pgvector)**,
**FastAPI backend**, **Next.js frontend**, **nightly database backups**, and
an optional **Cloudflare tunnel** for HTTPS.

---

## 1. Prepare the server (one time)

```bash
ssh root@YOUR_VPS_IP

# Updates + Docker
apt update && apt upgrade -y
curl -fsSL https://get.docker.com | sh

# Deploy user (skip if you deploy as root)
adduser --disabled-password deploy
usermod -aG docker deploy
su - deploy
```

## 2. Get the code and configure secrets

```bash
sudo mkdir -p /opt/ihp && sudo chown $USER /opt/ihp
git clone <your-repo-url> /opt/ihp      # or: scp -r the project folder
cd /opt/ihp
cp .env.example .env
nano .env
```

**Minimum required in `.env`:**

| Key | Value |
|---|---|
| `DB_PASSWORD` | strong random password (`openssl rand -hex 24`) |
| `SECRET_KEY` | `openssl rand -hex 32` — signs auth tokens |
| `ADMIN_USERNAME` | your admin login name |
| `ADMIN_PASSWORD` | strong password (seeded on first boot) |

The backend logs a loud warning at startup if `SECRET_KEY` or
`ADMIN_PASSWORD` are left at defaults — check `docker compose logs backend`.

## 3. Start the stack

```bash
cd /opt/ihp
docker compose up -d --build
docker compose ps          # db, backend, frontend, db-backup should be Up
docker compose logs backend | tail -20   # watch migrations + admin seed
```

The frontend listens on container port **3000**. Nothing is published to the
host by default — expose it through a tunnel or reverse proxy (next section).

## 4. Put it on the internet (pick ONE)

### Option A — Cloudflare Tunnel (recommended, free HTTPS, no open ports)

1. Cloudflare Zero Trust dashboard → Networks → Tunnels → *Create tunnel*.
2. Copy the tunnel token into `.env` as `CLOUDFLARE_TUNNEL_TOKEN=...`.
3. `docker compose --profile tunnel up -d`
4. In the tunnel's public hostname settings point your domain
   (e.g. `ihp.example.com`) → `http://frontend:3000`.

### Option B — Host cloudflared already running on the VPS

Add the hostname to the existing tunnel's ingress pointing at
`http://localhost:3000`, and publish the port in `docker-compose.yml`:

```yaml
  frontend:
    ports: ["127.0.0.1:3000:3000"]
```

### Option C — Nginx + Let's Encrypt on the VPS

```bash
apt install -y nginx certbot python3-certbot-nginx
```

```nginx
# /etc/nginx/sites-available/ihp
server {
    server_name ihp.example.com;
    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        # Project files can be sizeable — allow big uploads
        client_max_body_size 100m;
    }
}
```

Publish the frontend port as in Option B, then:
```bash
ln -s /etc/nginx/sites-available/ihp /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
certbot --nginx -d ihp.example.com
```

## 5. First login

Open `https://your-domain` → login with `ADMIN_USERNAME` /
`ADMIN_PASSWORD` from `.env` → **Admin → Users** to create real users,
then **Admin → Roles** to grant capabilities. Change the admin password from
the Profile page.

## 6. Backups & restore

The `db-backup` service dumps the database **nightly at 00:00 UTC** into
`/opt/ihp/backups/` and prunes old files (14 daily / 4 weekly / 3 monthly).

```bash
ls -lh /opt/ihp/backups/                 # verify dumps appear
# Restore:
gunzip < /opt/ihp/backups/ihp_<date>.sql.gz \
  | docker compose exec -T db psql -U ihp -d ihp
```

Uploaded/generated project files live in the `ihp_data` volume — back it up
with any volume snapshot tool, or add an rsync/cron copying
`/var/lib/docker/volumes/ihp_ihp_data/_data` off-host.

## 7. Updates / CI-CD

Manual: `cd /opt/ihp && git pull && docker compose up -d --build`

Automatic: the GitHub Actions workflow `.github/workflows/deploy.yml` SSHes
to the VPS on every push to `main` and does exactly that. Set these repo
secrets (Settings → Secrets and variables → Actions):

- `VPS_HOST` — VPS IP or hostname
- `VPS_USER` — SSH user (must be in the `docker` group)
- `VPS_SSH_KEY` — private key whose public key is in the VPS
  `~/.ssh/authorized_keys`

## 8. Operations cheat-sheet

```bash
docker compose ps                     # status
docker compose logs -f backend       # tail API logs
docker compose restart backend       # restart one service
docker compose exec db psql -U ihp   # SQL shell
docker compose down                  # stop (data volumes kept)
docker compose down -v               # STOP — also deletes DB + files!
```

## 9. Troubleshooting

| Symptom | Fix |
|---|---|
| `backend` restarts in a loop | `docker compose logs backend` — usually a bad `DATABASE_URL`/password |
| Login 401 right after deploy | `ADMIN_PASSWORD` in `.env` differs from the one the admin was seeded with; `docker compose exec db psql -U ihp -c "delete from users;"` and restart to reseed (dev only) |
| 502 from tunnel/nginx | frontend container not up — check `docker compose ps` |
| Migrations failed mid-deploy | `docker compose logs backend`, fix env, then `docker compose up -d` again (alembic reruns) |
