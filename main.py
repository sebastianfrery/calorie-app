import os
from typing import Literal

import stripe
import uvicorn
from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from database import (
    get_cached_analysis,
    get_today_entries,
    get_user,
    hash_image,
    save_analysis,
    set_user_vip,
)
from health_engine import analyze_health
from models import FoodAnalysis
from vision_engine import analyze_food

load_dotenv()

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
STRIPE_SUCCESS_URL = os.environ.get("STRIPE_SUCCESS_URL", "https://calorie-app.com/payment-success")
STRIPE_CANCEL_URL = os.environ.get("STRIPE_CANCEL_URL", "https://calorie-app.com/payment-cancel")

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}

app = FastAPI(title="CalorieApp Vision API", version="2.0.0")

# ── CORS Configuration for Mobile App ─────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Food analysis ─────────────────────────────────────────────────────────────

@app.post("/analyze", response_model=FoodAnalysis)
async def analyze(
    image: UploadFile = File(..., description="Food image (JPEG, PNG, WebP)"),
    tier: Literal["Basic", "Pro"] = Query(default="Basic"),
    email: str | None = Query(default=None),
):
    if image.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=415, detail=f"Unsupported media type '{image.content_type}'.")

    image_bytes = await image.read()
    if len(image_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Image exceeds 10 MB limit.")

    # Protect Anthropic credits: only confirmed VIP users may use the Pro tier
    if tier == "Pro":
        user = get_user(email) if email else None
        if not user or not user.get("is_vip"):
            tier = "Basic"

    image_hash = hash_image(image_bytes)

    cached = get_cached_analysis(image_hash)
    if cached:
        print(f"[CACHE HIT] hash={image_hash[:12]} model={cached.model_used} email={email}")
        save_analysis(cached, image_hash, tier, email=email)
        return cached

    try:
        result = analyze_food(image_bytes, image.content_type, user_tier=tier)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    print(f"[API CALL] tier={tier} model={result.model_used} email={email} hash={image_hash[:12]}")
    save_analysis(result, image_hash, tier, email=email)
    return result


# ── VIP Health Analysis ───────────────────────────────────────────────────────

@app.post("/health-analysis")
def health_analysis(email: str = Query(..., description="User email")):
    user = get_user(email)
    if not user or not user.get("is_vip"):
        raise HTTPException(status_code=403, detail="Acceso exclusivo para usuarios VIP.")

    entries = get_today_entries(email)
    if not entries:
        raise HTTPException(status_code=400, detail="No hay alimentos registrados hoy.")

    try:
        advice = analyze_health(entries)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {"advice": advice}


# ── Stripe ────────────────────────────────────────────────────────────────────

@app.post("/create-checkout-session")
def create_checkout_session(email: str = Query(..., description="User email")):
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[
                {
                    "price_data": {
                        "currency": "usd",
                        "product_data": {"name": "CalorieApp VIP"},
                        "unit_amount": 999,  # $9.99
                    },
                    "quantity": 1,
                }
            ],
            mode="payment",
            customer_email=email,
            metadata={"email": email},
            success_url=STRIPE_SUCCESS_URL,
            cancel_url=STRIPE_CANCEL_URL,
        )
    except stripe.StripeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {"checkout_url": session.url}


@app.post("/stripe-webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    if event["type"] == "checkout.session.completed":
        session_obj = event["data"]["object"]
        email = session_obj.get("metadata", {}).get("email")
        if email:
            set_user_vip(email)

    return {"received": True}


# ── Misc ──────────────────────────────────────────────────────────────────────

@app.get("/user-status")
def user_status(email: str = Query(..., description="User email")):
    if not email or not email.strip():
        raise HTTPException(status_code=400, detail="Email is required")

    try:
        user = get_user(email)
        return {
            "email": email,
            "is_vip": bool(user and user.get("is_vip")),
            "exists": user is not None
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error fetching user status: {str(exc)}") from exc


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
