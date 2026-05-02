import os
from datetime import date

import pandas as pd
import stripe
import streamlit as st
from dotenv import load_dotenv

from database import get_cached_analysis, get_today_entries, get_user, hash_image, save_analysis
from health_engine import analyze_health
from vision_engine import analyze_food

load_dotenv()

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_SUCCESS_URL = os.environ.get("STRIPE_SUCCESS_URL", "http://localhost:8501?vip_activated=1")
STRIPE_CANCEL_URL = os.environ.get("STRIPE_CANCEL_URL", "http://localhost:8501")

st.set_page_config(page_title="CalorieApp", page_icon="🍽️", layout="centered")


def check_vip(email: str) -> bool:
    if not email:
        return False
    try:
        user = get_user(email)
        return bool(user and user.get("is_vip"))
    except Exception:
        return False


# ── VIP activation banner ─────────────────────────────────────────────────────
if st.query_params.get("vip_activated") == "1":
    st.toast("🌟 ¡Pago confirmado! Tu cuenta VIP ya está activa.", icon="✅")
    st.query_params.clear()

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Configuración")
    email = st.text_input("Tu correo electrónico", placeholder="tu@email.com")
    daily_goal = st.number_input("Objetivo calórico diario (kcal)", 500, 6000, 2000, 50)

    is_vip = check_vip(email) if email else False

    if is_vip:
        tier = st.selectbox("Plan de análisis", ["Pro", "Basic"])
        st.success("🌟 Usuario VIP activo")
    else:
        tier = "Basic"
        st.selectbox(
            "Plan de análisis",
            ["Basic"],
            disabled=True,
            help="Hazte VIP para desbloquear el Plan Pro (Claude Sonnet)",
        )
        if email:
            st.caption("Plan gratuito · Upgrade disponible abajo")

    st.divider()
    if st.button("🔄 Actualizar galería"):
        st.rerun()

# ── Upload & Analyze ──────────────────────────────────────────────────────────
st.title("🍽️ CalorieApp")
st.subheader("Analizar alimento")

uploaded = st.file_uploader(
    "Sube una foto de tu comida",
    type=["jpg", "jpeg", "png", "webp"],
    label_visibility="collapsed",
)

if uploaded:
    st.image(uploaded, width=320)
    if st.button("Analizar", type="primary"):
        if not email:
            st.warning("Por favor ingresa tu correo electrónico en el sidebar antes de analizar.")
        else:
            with st.spinner("Analizando imagen…"):
                try:
                    image_bytes = uploaded.getvalue()
                    media_type = uploaded.type

                    # Server-side VIP guard
                    effective_tier = tier
                    if effective_tier == "Pro":
                        user = get_user(email)
                        if not user or not user.get("is_vip"):
                            effective_tier = "Basic"

                    image_hash = hash_image(image_bytes)
                    cached = get_cached_analysis(image_hash)

                    if cached:
                        result = cached
                        print(f"[CACHE HIT] hash={image_hash[:12]} model={result.model_used} email={email}")
                    else:
                        result = analyze_food(image_bytes, media_type, user_tier=effective_tier)
                        print(f"[API CALL] tier={effective_tier} model={result.model_used} email={email} hash={image_hash[:12]}")

                    save_analysis(result, image_hash, effective_tier, email=email)
                    st.session_state["last_analysis"] = result
                    st.session_state["just_analyzed"] = True

                except Exception as exc:
                    st.error(f"Error al analizar: {exc}")

# ── Analysis Result ───────────────────────────────────────────────────────────
if "last_analysis" in st.session_state:
    result = st.session_state["last_analysis"]

    if st.session_state.pop("just_analyzed", False):
        st.toast("🍽️ ¡Añadido a tu diario!")

    st.success(f"**{result.food_name}**")

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Calorías", f"{result.estimated_calories} kcal")
    m = result.macronutrients
    c2.metric("Proteína", f"{m.protein_g} g")
    c3.metric("Carbos", f"{m.carbs_g} g")
    c4.metric("Grasa", f"{m.fat_g} g")
    c5.metric("Fibra", f"{m.fiber_g} g")

    chart_df = pd.DataFrame(
        {"Gramos": [m.protein_g, m.carbs_g, m.fat_g]},
        index=["Proteína", "Carbos", "Grasa"],
    )
    st.bar_chart(chart_df)

    if result.portion_size_g:
        st.caption(f"🍽️ Porción estimada: {result.portion_size_g} g/ml")
    if result.allergens:
        st.warning(f"⚠️ Alérgenos detectados: {', '.join(result.allergens)}")
    if result.health_score is not None:
        icon = "🟢" if result.health_score >= 7 else "🟡" if result.health_score >= 4 else "🔴"
        st.info(f"{icon} Score de Salud: **{result.health_score}/10** — {result.health_score_reason or ''}")

    st.caption(
        f"Modelo: {result.model_used} · Confianza: {result.confidence}"
        + (" · ✓ desde caché" if result.cache_hit else "")
    )

st.divider()

# ── Today's Gallery & Calorie Tracker ────────────────────────────────────────
st.subheader("Lo que comí hoy")

entries = get_today_entries(email or None)

if not entries:
    msg = "Todavía no has registrado ningún alimento hoy." if email else "Ingresa tu correo en el sidebar para ver tu historial."
    st.info(msg)
else:
    total = sum(e["estimated_calories"] for e in entries)
    remaining = daily_goal - total
    pct = min(total / daily_goal, 1.0)

    c1, c2, c3 = st.columns(3)
    c1.metric("Consumidas", f"{total} kcal")
    c2.metric("Objetivo", f"{daily_goal} kcal")
    if remaining < 0:
        c3.markdown(
            f'<div style="padding:4px 0">'
            f'<p style="font-size:.75rem;color:#888;margin:0">⚠️ Exceso de kcal</p>'
            f'<p style="font-size:2rem;font-weight:700;color:#e74c3c;margin:4px 0 0">{abs(remaining)} kcal</p>'
            f'<p style="font-size:.875rem;color:#e74c3c;margin:0">{remaining:+d}</p>'
            f'</div>',
            unsafe_allow_html=True,
        )
    else:
        c3.metric("Restantes", f"{abs(remaining)} kcal", delta=f"{remaining:+d}")

    bar_color = "#e74c3c" if remaining < 0 else "#2ecc71"
    st.markdown(
        f"""
        <div style="background:#e0e0e0;border-radius:8px;height:18px;overflow:hidden">
          <div style="width:{pct*100:.1f}%;background:{bar_color};height:100%;
                      border-radius:8px;transition:width .4s ease"></div>
        </div>
        <p style="text-align:right;font-size:0.8rem;color:#888;margin:2px 0 0">
          {pct*100:.0f}% del objetivo</p>
        """,
        unsafe_allow_html=True,
    )

    st.divider()
    for entry in entries:
        with st.container(border=True):
            left, right = st.columns([3, 1])
            left.markdown(f"**{entry['food_name']}**")
            right.markdown(
                f"<p style='text-align:right;font-size:1.1rem;font-weight:600'>"
                f"{entry['estimated_calories']} kcal</p>",
                unsafe_allow_html=True,
            )
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Proteína", f"{entry['protein_g']} g")
            c2.metric("Carbos", f"{entry['carbs_g']} g")
            c3.metric("Grasa", f"{entry['fat_g']} g")
            c4.metric("Fibra", f"{entry['fiber_g']} g")

    # ── Health Coach ──────────────────────────────────────────────────────────
    st.divider()
    st.markdown("#### 🌟 Plan Nutricional para Mañana")

    if not email:
        st.caption("Ingresa tu correo en el sidebar para acceder.")
    elif not is_vip:
        st.markdown("Claude Sonnet analiza tu dieta de hoy y genera un plan personalizado para mañana.")
        col_desc, col_btn = st.columns([2, 1])
        col_desc.markdown("**$9.99** — pago único, activación inmediata")
        if col_btn.button("Upgrade a VIP →", type="primary"):
            try:
                session = stripe.checkout.Session.create(
                    payment_method_types=["card"],
                    line_items=[
                        {
                            "price_data": {
                                "currency": "usd",
                                "product_data": {"name": "CalorieApp VIP"},
                                "unit_amount": 999,
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
                st.session_state["checkout_url"] = session.url
            except stripe.StripeError as exc:
                st.error(f"Error al crear sesión de pago: {exc}")
        if "checkout_url" in st.session_state:
            st.link_button(
                "Ir al pago seguro (Stripe) →",
                st.session_state["checkout_url"],
                type="primary",
            )
    else:
        if st.button("Generar Plan Nutricional con Claude Sonnet", type="primary", use_container_width=True):
            with st.spinner("Claude Sonnet analizando tu dieta del día…"):
                try:
                    advice = analyze_health(entries)
                    st.session_state["health_advice"] = advice
                except Exception as exc:
                    st.error(f"Error al generar plan: {exc}")
        if "health_advice" in st.session_state:
            with st.expander("Tu plan para mañana", expanded=True):
                st.markdown(st.session_state["health_advice"])
