"""Golden Brother Angel One SmartAPI backend.

All broker credentials/tokens stay server-side. The one-time PIN/TOTP are used
only during the login request and are never stored. Access is protected by an
operator API token. This is a single-operator/family-account deployment, not a
multi-tenant SaaS authentication system.
"""
from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import requests
from cryptography.fernet import Fernet, InvalidToken
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy import Boolean, DateTime, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

APP_NAME = "Golden Brother SmartAPI"
BROKER_ROOT = "https://apiconnect.angelone.in"
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./golden_brother.db")
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

class BrokerAccount(Base):
    __tablename__ = "broker_accounts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    label: Mapped[str] = mapped_column(String(80))
    client_code_masked: Mapped[str] = mapped_column(String(32))
    client_code_enc: Mapped[str] = mapped_column(Text)
    api_key_enc: Mapped[str] = mapped_column(Text)
    jwt_enc: Mapped[str] = mapped_column(Text)
    refresh_enc: Mapped[str] = mapped_column(Text)
    feed_enc: Mapped[str] = mapped_column(Text)
    is_master: Mapped[bool] = mapped_column(Boolean, default=False)
    copy_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    copy_multiplier: Mapped[float] = mapped_column(default=1.0)
    max_order_value: Mapped[float] = mapped_column(default=10000.0)
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class CopyOrder(Base):
    __tablename__ = "copy_orders"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    master_account_id: Mapped[str] = mapped_column(String(36))
    follower_account_id: Mapped[str] = mapped_column(String(36))
    client_order_tag: Mapped[str] = mapped_column(String(19), unique=True)
    master_order_id: Mapped[str] = mapped_column(String(64))
    follower_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="submitted")
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

Base.metadata.create_all(engine)

app = FastAPI(title=APP_NAME, version="0.1.0")
origins = [x.strip() for x in os.getenv("CORS_ORIGINS", "http://localhost:8000").split(",") if x.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=False, allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["Authorization", "Content-Type"])

def get_fernet() -> Fernet:
    key = os.getenv("ENCRYPTION_KEY")
    if not key:
        raise HTTPException(503, "Server encryption is not configured. Set ENCRYPTION_KEY.")
    try:
        return Fernet(key.encode())
    except Exception:
        raise HTTPException(503, "ENCRYPTION_KEY is invalid. Generate a Fernet key.")

def seal(value: str) -> str:
    return get_fernet().encrypt(value.encode()).decode()

def unseal(value: str) -> str:
    try:
        return get_fernet().decrypt(value.encode()).decode()
    except (InvalidToken, ValueError):
        raise HTTPException(503, "Could not decrypt stored broker session. Check ENCRYPTION_KEY.")

def require_app_token(authorization: str | None = Header(default=None)) -> None:
    expected = os.getenv("APP_API_TOKEN")
    if not expected or len(expected) < 32:
        raise HTTPException(503, "Set APP_API_TOKEN to a random secret of at least 32 characters.")
    supplied = authorization or ""
    if not supplied.startswith("Bearer ") or not __import__("hmac").compare_digest(supplied[7:], expected):
        raise HTTPException(401, "Unauthorized")

def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class ConnectRequest(BaseModel):
    label: str = Field(min_length=2, max_length=80)
    client_code: str = Field(min_length=3, max_length=32)
    api_key: SecretStr
    pin: SecretStr
    totp: SecretStr = Field(min_length=6, max_length=8)
    account_owner_consent: bool
    make_master: bool = False

class CopySettings(BaseModel):
    enabled: bool
    multiplier: float = Field(default=1.0, gt=0, le=10)
    max_order_value: float = Field(default=10000, gt=0, le=10000000)

class OrderRequest(BaseModel):
    master_account_id: str
    tradingsymbol: str = Field(min_length=2, max_length=40)
    symboltoken: str = Field(min_length=1, max_length=24)
    exchange: str = Field(default="NSE", max_length=10)
    transactiontype: str
    ordertype: str
    producttype: str
    duration: str = "DAY"
    quantity: int = Field(gt=0, le=1000000)
    price: float = Field(default=0, ge=0)
    triggerprice: float = Field(default=0, ge=0)
    confirm_live: bool = False
    copy_to_followers: bool = False

def headers(account: BrokerAccount) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-PrivateKey": unseal(account.api_key_enc),
        "X-UserType": "USER",
        "X-SourceID": "WEB",
        "X-MACAddress": "00:00:00:00:00:00",
        "Authorization": "Bearer " + unseal(account.jwt_enc),
    }

def broker_request(account: BrokerAccount, method: str, path: str, payload: dict | None = None) -> dict[str, Any]:
    # Broker API calls are made server-side; never expose JWT/API keys to the browser.
    try:
        response = requests.request(method, BROKER_ROOT + path, headers=headers(account), json=payload, timeout=15)
        data = response.json()
    except requests.RequestException as exc:
        raise HTTPException(502, f"Angel One network error: {type(exc).__name__}")
    except ValueError:
        raise HTTPException(502, "Angel One returned a non-JSON response.")
    if response.status_code >= 400 or data.get("status") is False:
        raise HTTPException(502, {"broker_status": response.status_code, "message": data.get("message", "Angel One request failed"), "errorcode": data.get("errorcode")})
    return data

def account_or_404(db, account_id: str) -> BrokerAccount:
    account = db.get(BrokerAccount, account_id)
    if not account:
        raise HTTPException(404, "Account not found")
    return account

def place_for_account(db, account: BrokerAccount, master_payload: dict, quantity: int, tag: str) -> dict:
    payload = {
        "variety": "NORMAL",
        "tradingsymbol": master_payload["tradingsymbol"],
        "symboltoken": master_payload["symboltoken"],
        "transactiontype": master_payload["transactiontype"],
        "exchange": master_payload["exchange"],
        "ordertype": master_payload["ordertype"],
        "producttype": master_payload["producttype"],
        "duration": master_payload["duration"],
        "price": str(master_payload["price"]),
        "triggerprice": str(master_payload["triggerprice"]),
        "quantity": str(quantity),
        "ordertag": tag[:19],
    }
    return broker_request(account, "POST", "/rest/secure/angelbroking/order/v1/placeOrder", payload)

@app.get("/health")
def health():
    return {"ok": True, "service": APP_NAME, "live_trading_enabled": os.getenv("LIVE_TRADING_ENABLED", "false").lower() == "true"}

@app.post("/api/accounts/connect", dependencies=[Depends(require_app_token)])
def connect_account(body: ConnectRequest, db=Depends(db_session)):
    if not body.account_owner_consent:
        raise HTTPException(400, "The account holder must explicitly authorize this account connection.")
    # The PIN and TOTP are transient request values only; they are not persisted.
    api_key = body.api_key.get_secret_value()
    login_payload = {"clientcode": body.client_code, "password": body.pin.get_secret_value(), "totp": body.totp.get_secret_value()}
    try:
        response = requests.post(
            BROKER_ROOT + "/rest/auth/angelbroking/user/v1/loginByPassword",
            headers={"Content-Type": "application/json", "Accept": "application/json", "X-PrivateKey": api_key, "X-UserType": "USER", "X-SourceID": "WEB", "X-MACAddress": "00:00:00:00:00:00"},
            json=login_payload, timeout=15,
        )
        result = response.json()
    except requests.RequestException:
        raise HTTPException(502, "Could not reach Angel One login service.")
    except ValueError:
        raise HTTPException(502, "Angel One returned an invalid login response.")
    if response.status_code >= 400 or not result.get("status") or not result.get("data", {}).get("jwtToken"):
        raise HTTPException(401, {"message": result.get("message", "Angel One login failed"), "errorcode": result.get("errorcode")})
    data = result["data"]
    if body.make_master and db.scalar(select(BrokerAccount).where(BrokerAccount.is_master.is_(True))):
        raise HTTPException(409, "A master account already exists. Change roles explicitly before replacing it.")
    account = BrokerAccount(
        label=body.label, client_code_masked="••••" + body.client_code[-4:],
        client_code_enc=seal(body.client_code), api_key_enc=seal(api_key),
        jwt_enc=seal(data["jwtToken"]), refresh_enc=seal(data.get("refreshToken", "")),
        feed_enc=seal(data.get("feedToken", "")), is_master=body.make_master,
    )
    db.add(account); db.commit(); db.refresh(account)
    return {"id": account.id, "label": account.label, "client_code": account.client_code_masked, "is_master": account.is_master, "connected": True, "message": "Angel One session connected. PIN and TOTP were not stored."}

@app.get("/api/accounts", dependencies=[Depends(require_app_token)])
def list_accounts(db=Depends(db_session)):
    rows = db.scalars(select(BrokerAccount)).all()
    return [{"id": a.id, "label": a.label, "client_code": a.client_code_masked, "is_master": a.is_master, "copy_enabled": a.copy_enabled, "multiplier": a.copy_multiplier, "max_order_value": a.max_order_value, "connected": True} for a in rows]

@app.patch("/api/accounts/{account_id}/copy-settings", dependencies=[Depends(require_app_token)])
def update_copy_settings(account_id: str, body: CopySettings, db=Depends(db_session)):
    account = account_or_404(db, account_id)
    if account.is_master and body.enabled:
        raise HTTPException(400, "The master account cannot be a follower.")
    account.copy_enabled = body.enabled
    account.copy_multiplier = body.multiplier
    account.max_order_value = body.max_order_value
    db.commit()
    return {"id": account.id, "copy_enabled": account.copy_enabled, "multiplier": account.copy_multiplier, "max_order_value": account.max_order_value}

@app.post("/api/accounts/{account_id}/make-master", dependencies=[Depends(require_app_token)])
def make_master(account_id: str, db=Depends(db_session)):
    account = account_or_404(db, account_id)
    for row in db.scalars(select(BrokerAccount)).all():
        row.is_master = (row.id == account.id)
        if row.is_master:
            row.copy_enabled = False
    db.commit()
    return {"master_account_id": account.id}

@app.delete("/api/accounts/{account_id}", dependencies=[Depends(require_app_token)])
def disconnect_account(account_id: str, db=Depends(db_session)):
    account = account_or_404(db, account_id)
    db.delete(account); db.commit()
    return {"disconnected": True, "id": account_id}

@app.get("/api/accounts/{account_id}/profile", dependencies=[Depends(require_app_token)])
def profile(account_id: str, db=Depends(db_session)):
    return broker_request(account_or_404(db, account_id), "GET", "/rest/secure/angelbroking/user/v1/getProfile")

@app.get("/api/accounts/{account_id}/funds", dependencies=[Depends(require_app_token)])
def funds(account_id: str, db=Depends(db_session)):
    return broker_request(account_or_404(db, account_id), "GET", "/rest/secure/angelbroking/user/v1/getRMS")

@app.get("/api/accounts/{account_id}/orders", dependencies=[Depends(require_app_token)])
def orders(account_id: str, db=Depends(db_session)):
    return broker_request(account_or_404(db, account_id), "GET", "/rest/secure/angelbroking/order/v1/getOrderBook")

@app.get("/api/accounts/{account_id}/positions", dependencies=[Depends(require_app_token)])
def positions(account_id: str, db=Depends(db_session)):
    return broker_request(account_or_404(db, account_id), "GET", "/rest/secure/angelbroking/order/v1/getPosition")

@app.get("/api/accounts/{account_id}/holdings", dependencies=[Depends(require_app_token)])
def holdings(account_id: str, db=Depends(db_session)):
    return broker_request(account_or_404(db, account_id), "GET", "/rest/secure/angelbroking/portfolio/v1/getHolding")

@app.get("/api/accounts/{account_id}/quote", dependencies=[Depends(require_app_token)])
def quote(account_id: str, exchange: str, symboltoken: str, db=Depends(db_session)):
    return broker_request(account_or_404(db, account_id), "POST", "/rest/secure/angelbroking/order/v1/getLtpData", {"exchange": exchange, "tradingsymbol": "", "symboltoken": symboltoken})

@app.post("/api/orders/master", dependencies=[Depends(require_app_token)])
def place_master_order(body: OrderRequest, db=Depends(db_session)):
    if os.getenv("LIVE_TRADING_ENABLED", "false").lower() != "true":
        raise HTTPException(423, "Live trading is disabled. Set LIVE_TRADING_ENABLED=true only after completing broker and risk checks.")
    if not body.confirm_live:
        raise HTTPException(400, "Explicit confirm_live=true is required.")
    if body.transactiontype not in {"BUY", "SELL"}:
        raise HTTPException(400, "transactiontype must be BUY or SELL.")
    if body.ordertype not in {"MARKET", "LIMIT", "STOPLOSS_LIMIT", "STOPLOSS_MARKET"}:
        raise HTTPException(400, "Unsupported order type.")
    if body.producttype not in {"DELIVERY", "INTRADAY", "MARGIN", "CARRYFORWARD", "BO"}:
        raise HTTPException(400, "Unsupported product type.")
    master = account_or_404(db, body.master_account_id)
    if not master.is_master:
        raise HTTPException(400, "Selected account is not configured as master.")
    notional = body.quantity * max(body.price, body.triggerprice, 0)
    # Market orders have no client-known notional; require a configured cap via an explicit price estimate.
    if body.ordertype == "MARKET" and body.price <= 0:
        raise HTTPException(400, "For safety, provide an estimated price in price so the order-value cap can be checked.")
    if notional > 100000:
        raise HTTPException(400, "Master order exceeds the hard-coded ₹1,00,000 safety ceiling.")
    master_payload = body.model_dump()
    master_tag = uuid.uuid4().hex[:19]
    master_result = place_for_account(db, master, master_payload, body.quantity, master_tag)
    master_order_id = str((master_result.get("data") or {}).get("orderid", ""))
    output = {"master": {"account_id": master.id, "response": master_result}, "followers": []}
    if body.copy_to_followers:
        followers = db.scalars(select(BrokerAccount).where(BrokerAccount.copy_enabled.is_(True), BrokerAccount.is_master.is_(False))).all()
        for follower in followers:
            follower_qty = max(1, int(body.quantity * follower.copy_multiplier))
            if follower_qty * max(body.price, body.triggerprice) > follower.max_order_value:
                output["followers"].append({"account_id": follower.id, "status": "skipped", "reason": "Follower max order value exceeded"})
                continue
            tag = uuid.uuid4().hex[:19]
            try:
                # Respect cumulative order API limit; serialize follower calls.
                time.sleep(0.12)
                result = place_for_account(db, follower, master_payload, follower_qty, tag)
                follower_order_id = str((result.get("data") or {}).get("orderid", ""))
                db.add(CopyOrder(master_account_id=master.id, follower_account_id=follower.id, client_order_tag=tag, master_order_id=master_order_id, follower_order_id=follower_order_id, status="submitted"))
                output["followers"].append({"account_id": follower.id, "status": "submitted", "response": result})
            except HTTPException as exc:
                db.add(CopyOrder(master_account_id=master.id, follower_account_id=follower.id, client_order_tag=tag, master_order_id=master_order_id, status="failed", detail=str(exc.detail)))
                output["followers"].append({"account_id": follower.id, "status": "failed", "reason": exc.detail})
    db.commit()
    return output

@app.get("/api/copy-orders", dependencies=[Depends(require_app_token)])
def copy_orders(db=Depends(db_session)):
    rows = db.scalars(select(CopyOrder).order_by(CopyOrder.created_at.desc()).limit(200)).all()
    return [{"id": r.id, "master_order_id": r.master_order_id, "follower_account_id": r.follower_account_id, "follower_order_id": r.follower_order_id, "status": r.status, "detail": r.detail, "created_at": r.created_at.isoformat()} for r in rows]
