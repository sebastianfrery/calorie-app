import os
from datetime import date

import requests
import streamlit as st
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

BACKEND_URL = "http://localhost:8000"

st.set_page_config(page_title="CalorieApp", page_icon="🍽️", layout="centered")


@st.cache_resource
def _supabase():
    return create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_ROLE_KEY"],
    )


def get_today_entries(email: str | None = None) -> list[dict]:
    if not email:
        return []
    today = date.today().isoformat()
    return (
        _supabase()
        .table("food_analyses")
        .select("food_name, estimated_calories, protein_g, carbs_g, fat_g, fiber_g, created_at")
        .eq("analyzed_date", today)
        .eq("email", email)
        .order("created_at")
        .execute()
        .data or []
    )


def check_vip(email: str) -> bool:
    if not email:
        return False
    res = requests.get(f"{BACKEND_URL}/user-status", params={"email": email}, timeout=5)
    return res.ok and res.json().get("is_vip", False)


# ── VIP activation banner ─────────────────────────────────────────────────────
params = st.query_params
if params.get("vip_activated") == "1":
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
        st.cache_data.clear()

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
                    resp = requests.post(
                        f"{BACKEND_URL}/analyze",
                        files={"image": (uploaded.name, uploaded.getvalue(), uploaded.type)},
                        params={"tier": tier, "email": email},
                        timeout=60,
                    )
                except requests.ConnectionError:
                    st.error("No se puede conectar al servidor. ¿Está corriendo `python main.py`?")
                    st.stop()

            if resp.ok:
                data = resp.json()
                st.success(f"**{data['food_name']}**")
                st.toast("🍽️ ¡Añadido a tu diario!")
                c1, c2, c3, c4, c5 = st.columns(5)
                c1.metric("Calorías", f"{data['estimated_calories']} kcal")
                m = data["macronutrients"]
                c2.metric("Proteína", f"{m['protein_g']} g")
                c3.metric("Carbos", f"{m['carbs_g']} g")
                c4.metric("Grasa", f"{m['fat_g']} g")
                c5.metric("Fibra", f"{m['fiber_g']} g")
                st.caption(
                    f"Modelo: {data['model_used']} · Confianza: {data['confidence']}"
                    + (" · ✓ desde caché" if data.get("cache_hit") else "")
                )
                st.cache_data.clear()
            else:
                st.error(f"Error {resp.status_code}: {resp.json().get('detail', 'Error desconocido')}")

st.divider()

# ── Today's Gallery & Calorie Tracker ────────────────────────────────────────
st.subheader("Lo que comí hoy")

entries = get_today_entries(email or None)

if not entries:
    st.info("Todavía no has registrado ningún alimento hoy.")
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

    # ── Health Coach (al final de la galería) ─────────────────────────────
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
                r = requests.post(
                    f"{BACKEND_URL}/create-checkout-session",
                    params={"email": email},
                    timeout=10,
                )
                if r.ok:
                    st.session_state["checkout_url"] = r.json()["checkout_url"]
                else:
                    st.error(r.json().get("detail", "Error al crear sesión de pago"))
            except requests.ConnectionError:
                st.error("No se puede conectar al servidor.")
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
                    r = requests.post(
                        f"{BACKEND_URL}/health-analysis",
                        params={"email": email},
                        timeout=90,
                    )
                except requests.ConnectionError:
                    st.error("No se puede conectar al servidor.")
                    st.stop()
            if r.ok:
                with st.expander("Tu plan para mañana", expanded=True):
                    st.markdown(r.json()["advice"])
            elif r.status_code == 403:
                st.error("Estado VIP no reconocido. Intenta actualizar la página.")
            else:
                st.error(r.json().get("detail", "Error desconocido"))
