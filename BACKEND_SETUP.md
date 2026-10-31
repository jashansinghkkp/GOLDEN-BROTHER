# Real backend deployment checklist

This repository contains a FastAPI service that calls Angel One SmartAPI from the server. The browser must never call SmartAPI directly or receive broker JWT/feed/refresh tokens.

## Deploy the backend on Render

1. Push/deploy the `feature/real-backend-setup` branch as a Render Python web service (or merge its PR first).
2. Build command: `pip install -r requirements.txt`.
3. Start command: `uvicorn server:app --host 0.0.0.0 --port $PORT`.
4. Attach a persistent disk at `/var/data` (1 GB is enough for initial testing).
5. Configure these environment variables in Render:
   - `DATABASE_URL=sqlite:////var/data/golden_brother.db`
   - `APP_API_TOKEN`: a random secret of at least 32 characters. Generate locally with `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
   - `ENCRYPTION_KEY`: a Fernet key. Generate locally with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
   - `LIVE_TRADING_ENABLED=false`
   - `CORS_ORIGINS`: exact HTTPS origin of the frontend; no trailing slash.
6. Back up the Fernet key securely. If it is lost or changed, encrypted broker sessions cannot be decrypted.
7. Open `https://YOUR-SERVICE.onrender.com/health`. It should return `ok: true`.
8. Open `https://YOUR-SERVICE.onrender.com/connect`, enter the backend URL and application token, and connect each Angel One account separately. The account owner must authorize their own account.

## First connection and verification

- Create/enable the SmartAPI app in Angel One's SmartAPI portal and use its API key.
- Use each account's own client code, PIN and current TOTP during its connection flow. PIN and TOTP are used for login only and are not stored.
- Verify each account's profile, funds, positions, holdings, orders and trade book using the account-data controls.
- New endpoints: `GET /api/accounts/{id}/trades`, `GET /api/accounts/{id}/summary`, and `GET /api/dashboard`. Dashboard sections return independently so a failed broker endpoint does not hide the other account data.
- API reference: `https://YOUR-SERVICE.onrender.com/docs`.

## Live trading safety

Live trading stays disabled. Do not change `LIVE_TRADING_ENABLED` to true until each account has been authorized, read-only checks pass, the API key's trading permissions and Angel One's current source-IP/static-IP requirements are confirmed, and the order flow has been tested with a safe process. A successful order submission response is not proof of a fill. Follower orders can be rejected, partially filled, delayed or filled at different prices.

This backend is currently a single-operator/family deployment protected by one application bearer token. It is not a public multi-user SaaS login system. Do not publish the application token in client-side JavaScript or give it to untrusted users. Use HTTPS only. Do not commit broker credentials or secrets to GitHub.

## Not yet production-complete

The current implementation does not provide continuous SmartAPI WebSocket chart streaming, broker postback signature validation, automated partial-fill reconciliation, per-user login/roles, a distributed rate limiter, or a fully automated daily-loss kill switch. Treat it as a real broker-connected integration foundation for controlled testing, not an unattended trading system.
