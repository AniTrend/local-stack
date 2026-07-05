# Unleash Feature Flag Service

Feature flagging platform for local-stack services. Coexists with GrowthBook; intended as the primary flagging backend for on-the-edge and future services.

## Setup

1. Copy `.env.example` to `.env` and fill in secrets.
2. Ensure PostgreSQL is running with the `unleash` database created (see `postgres/init/01-unleash.sql`).
3. Deploy via `./stackctl.sh`:
   ```bash
   ./stackctl.sh generate
   ./stackctl.sh up -s platform
   ```

## Access

- Admin UI: `https://unleash.docker.localhost`
- Client API: `https://unleash.docker.localhost/client`
- Health: `GET /health`

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| DATABASE_URL | PostgreSQL connection string | Required |
| UNLEASH_URL | Public URL of the Unleash instance | Required |
| INIT_ADMIN_API_TOKENS | Initial admin API tokens | Required |
| INIT_CLIENT_API_TOKENS | Initial client API tokens | Required |
| INIT_FRONTEND_API_TOKENS | Initial frontend API tokens | Required |

## Notes

- Unleash creates its database tables on first startup.
- API tokens are only created on first run if they don't exist.
- For production, use `ENVIRONMENT=production` and a real admin password via `INIT_ADMIN_PASSWORD`.
