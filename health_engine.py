import os

import anthropic

_SYSTEM = (
    "Eres un nutricionista clínico experto. Analiza la ingesta alimentaria diaria del usuario "
    "y proporciona un plan concreto para mañana: qué comer, en qué cantidades aproximadas y por qué. "
    "Sé específico con los alimentos. Responde siempre en español con formato Markdown claro."
)


def analyze_health(today_entries: list[dict]) -> str:
    lines = [
        f"- **{e['food_name']}**: {e['estimated_calories']} kcal "
        f"(Proteína {e['protein_g']}g · Carbos {e['carbs_g']}g · "
        f"Grasa {e['fat_g']}g · Fibra {e['fiber_g']}g)"
        for e in today_entries
    ]
    total = sum(e["estimated_calories"] for e in today_entries)

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    msg = client.messages.create(
        model="claude-3-5-sonnet-20241022",
        max_tokens=1200,
        system=_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Hoy consumí **{total} kcal** en total:\n\n"
                    + "\n".join(lines)
                    + "\n\n¿Qué debería comer mañana para equilibrar mi nutrición?"
                ),
            }
        ],
    )
    return msg.content[0].text
