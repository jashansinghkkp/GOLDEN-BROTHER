# Golden Brother — Angel One Multi-Account Copy Trading

A web-based Angel One SmartAPI workspace for one master trading account and separately authorized family follower accounts.

## What's included

- `index.html`: dashboard prototype.
- `connect.html`: secure account-connection and account-data interface.
- `server.py`: FastAPI backend for Angel One login, encrypted sessions, account data, and guarded master/follower order submission.
- `render.yaml`: Render web-service blueprint with persistent disk.
- `.env.example`: required environment variables.

## Implemented SmartAPI calls

- Login: `/rest/auth/angelbroking/user/v1/loginByPassword`.
- JWT refresh: `/rest/auth/angelbroking/jwt/v1/generateTokens`.
- Profile, funds/RMS, order book, positions and holdings.
- LTP quote polling.
- Per-account trade book and live account summary endpoints, plus an all-account dashboard snapshot with independent section error reporting.
- Master order submission and optional follower replication to opted-in accounts.

Official references: [SmartAPI authentication and WebSocket documentation](https://smartapi.angelone.in/docs/ResponseStructure), [API endpoints, order and market-data reference](https://smartapi.angelone.in/docs/Exceptions), [rate limits and postbacks](https://smartapi.angelone.in/docs/Edis/).

## Security and limitations

- This version is designed for a **single operator/family deployment**. It uses one long random `APP_API_TOKEN` as an operator gate; it is not a multi-user SaaS with individual website logins, roles, MFA or per-family permissions.
- Each account holder must explicitly authorize their own account. Never connect an account without its owner's permission.
- Angel One PIN and TOTP are submitted once to the backend for broker login and are not stored. API keys and JWT/refresh/feed tokens are encrypted at rest using Fernet.
- Never commit `.env`, API keys, PINs, TOTP secrets, JWTs, refresh tokens or feed tokens.
- Use HTTPS only. Restrict the backend to your own frontend origin and protect the app token. Do not expose it in a public website bundle.
- Set `ENCRYPTION_KEY` manually to a valid Fernet key; Render's generic generated value is not guaranteed to be Fernet-compatible.
- SmartAPI may require account/API-key configuration and static source-IP allowlisting for order APIs. Verify current requirements and Render outbound IP arrangements before enabling live orders.
- Copy trading cannot guarantee identical fills: follower orders may be rejected, delayed, partially filled or executed at different prices.
- Not yet included: SmartAPI WebSocket streaming, broker postback signature verification, automated partial-fill reconciliation, multi-tenant authentication, and production-grade distributed rate limiting. Do not treat this as a finished unattended trading system.
- Live orders are **disabled by default**. Keep them disabled until you have tested safely and confirmed applicable Angel One/exchange/regulatory requirements.

See [BACKEND_SETUP.md](BACKEND_SETUP.md) for the deployment and live-account verification checklist.

## Deploy on Render

1. Create a Render Blueprint from this repository/branch, or create a Python Web Service.
2. Build: `pip install -r requirements.txt`
3. Start: `uvicorn server:app --host 0.0.0.0 --port $PORT`
4. Attach a persistent disk mounted at `/var/data`; set `DATABASE_URL=sqlite:////var/data/golden_brother.db`.
5. Set `APP_API_TOKEN` to a random secret of at least 32 characters.
6. Generate a Fernet key locally:
   ```bash
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```
   Add the output as Render secret `ENCRYPTION_KEY`. Back it up securely; losing it makes stored sessions undecryptable.
7. Set `CORS_ORIGINS` to the exact HTTPS origin hosting `connect.html` (no trailing slash).
8. Keep `LIVE_TRADING_ENABLED=false`.
9. Open `https://YOUR-SERVICE.onrender.com/health` to verify the API, then open `https://YOUR-SERVICE.onrender.com/connect` for the connection dashboard. Enter the backend URL and app token, then connect each account separately. The main dashboard is served at `/`.
10. Check profile/funds/orders/positions/holdings before considering any real order execution.

## Environment

See `.env.example`. Never put broker secrets in frontend JavaScript, GitHub or chat.

## API endpoints

All `/api/*` endpoints require `Authorization: Bearer APP_API_TOKEN`.

- `POST /api/accounts/connect` — connect using client code, SmartAPI key, PIN and current TOTP.
- `GET /api/accounts` — list masked connected accounts.
- `PATCH /api/accounts/{id}/copy-settings` — opt in/out and set quantity multiplier/order-value cap.
- `POST /api/accounts/{id}/make-master` — select the master account.
- `DELETE /api/accounts/{id}` — disconnect/remove a stored session.
- `GET /api/accounts/{id}/profile|funds|orders|positions|holdings` — account data.
- `GET /api/accounts/{id}/quote?exchange=NSE&tradingsymbol=SBIN-EQ&symboltoken=3045` — LTP quote.
- `GET /api/accounts/{id}/trades` — trade book.
- `GET /api/accounts/{id}/summary` — profile, funds, positions, holdings, orders and trades.
- `GET /api/dashboard` — live summaries for all connected accounts.
- `POST /api/orders/master` — guarded live order endpoint; requires server live flag and explicit confirmation.
- `GET /api/copy-orders` — follower execution log.

FastAPI schema: `/docs`.

## Live trading gate

Only after all checks and testing, set `LIVE_TRADING_ENABLED=true`. The order endpoint also requires `confirm_live=true`. It applies a hard-coded ₹1,00,000 master-order notional ceiling and per-follower configured notional caps. Market orders require an estimated price for the cap check. These are basic safeguards, not a guarantee against loss.

## Run locally

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

Copy `.env.example` to `.env`, generate a valid Fernet key, set a long random app token, then run `uvicorn server:app --reload`.
