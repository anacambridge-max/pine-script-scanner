from __future__ import annotations

import os

import requests


def send_confirmed(signal: dict) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return

    risk = signal.get("risk") or {}
    direction = signal.get("direction")
    emoji = "🟢" if direction == "BUY" else "🔴"
    text = (
        f"{emoji} PRIME {direction} CONFIRMED\n"
        f"Symbol: {signal.get('symbol')}\n"
        f"TF: {signal.get('timeframe')}m\n"
        f"Time: {signal.get('timestamp')}\n"
        f"Trigger: {signal.get('trigger')}\n"
        f"Score: {signal.get('prime_score')} | Grade: {signal.get('grade')}\n"
        f"Entry: {risk.get('entry')}\n"
        f"SL: {risk.get('stop_loss')}\n"
        f"T1: {risk.get('target1')} | T2: {risk.get('target2')} | T3: {risk.get('target3')}\n"
        f"Qty: {risk.get('quantity')}"
    )
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    response = requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=10)
    response.raise_for_status()
