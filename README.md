# Golden Brother — Angel One Copy Trading

A web-based multi-account trading workspace for a master Angel One account and separately authorized family follower accounts.

## Current status

The first UI prototype is available in `index.html`. It is a static demo dashboard with sample market, order and account data. It does **not** connect to Angel One, authenticate accounts, stream live prices, or place real orders.

## Planned implementation

- Master-account overview: charts, positions, holdings, funds/margins, order book and P&L.
- Separate Angel One SmartAPI authorization/session per account holder.
- Follower account management and opt-in copy settings.
- Order replication with configurable quantity rules, per-account limits and execution status.
- Idempotency/duplicate protection, rate limiting, audit logs, partial-fill/error handling and global kill switch.
- Persistent user data with encrypted broker tokens and access controls.

## Important safety and compliance notes

- Each family account holder must independently authorize their own account; do not collect or share their broker password, PIN, TOTP or OTP.
- Never put SmartAPI keys, JWTs, refresh tokens or feed tokens in browser code, Git, logs or public configuration.
- Live trading must remain disabled until SmartAPI app registration, redirect URL/static-IP requirements (if applicable), account authorization, API permissions and applicable Angel One/NSE/SEBI requirements have been checked.
- Copy execution is not guaranteed to match the master order: follower orders may be rejected, partially filled, delayed or filled at different prices.
- Start with paper trading and explicit follower confirmation before considering automatic execution.

## Technology direction

Recommended deployment architecture: browser UI + authenticated backend API + PostgreSQL + encrypted secret storage. Render can host the web service and database, subject to the broker's current network/IP requirements.

## Run the prototype

Open `index.html` in a browser. All data is illustrative and local to the page; no backend or broker integration is configured.

## Official API reference

- [Angel One SmartAPI documentation](https://smartapi.angelone.in/docs)
