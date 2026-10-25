#!/usr/bin/env python3
"""Проверка Anthropic/Claude, Groq и Jina. Запуск: cd ~/finish && python3 check_ai_limits.py"""
from __future__ import annotations

import os
import sys

import requests
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "") or os.getenv("CLAUDE_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")
ANTHROPIC_WORKSPACE_ID = (os.getenv("ANTHROPIC_WORKSPACE_ID") or "").strip()
GROQ_KEY = os.getenv("GROQ_API_KEY", "")
JINA_KEY = os.getenv("JINA_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
JINA_MODEL = "jina-embeddings-v3"


def fmt_headers(headers: dict, prefix: str) -> None:
    found = False
    for k, v in sorted(headers.items()):
        kl = k.lower()
        if kl.startswith(prefix) or "ratelimit" in kl or kl == "retry-after":
            print(f"   {k}: {v}")
            found = True
    if not found:
        print("   (заголовки лимитов не пришли в ответе)")


def check_claude() -> bool:
    print("\n▶ Claude / Anthropic (основные ответы бота)")
    print(f"   Модель: {ANTHROPIC_MODEL}")
    print("   Кабинет: https://console.anthropic.com/")
    if ANTHROPIC_WORKSPACE_ID:
        print(f"   Workspace: {ANTHROPIC_WORKSPACE_ID}")

    if not ANTHROPIC_KEY:
        print("   ❌ ANTHROPIC_API_KEY не задан")
        return False

    headers = {
        "x-api-key": ANTHROPIC_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    if ANTHROPIC_WORKSPACE_ID:
        headers["anthropic-workspace-id"] = ANTHROPIC_WORKSPACE_ID

    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json={
                "model": ANTHROPIC_MODEL,
                "max_tokens": 16,
                "messages": [{"role": "user", "content": "ping"}],
            },
            timeout=30,
        )
        print(f"   HTTP {r.status_code}")
        if r.status_code == 400 and "workspace" in r.text.lower():
            print("   ❌ Нужен workspace-scoped ключ ИЛИ ANTHROPIC_WORKSPACE_ID")
            print("   Settings → Workspaces → скопируйте ID (wrkspc_...)")
            print("   либо создайте API key с привязкой к одному workspace.")
            print(f"   Детали: {r.text[:220]}")
            return False
        if r.status_code == 429:
            print("   ⚠️  ЛИМИТ ИСЧЕРПАН (429)")
            return False
        if r.status_code >= 400:
            print(f"   ❌ Ошибка: {r.text[:220]}")
            return False
        print("   ✅ Claude отвечает")
        ws = r.headers.get("anthropic-workspace-id")
        if ws:
            print(f"   anthropic-workspace-id (из ответа): {ws}")
        return True
    except Exception as e:
        print(f"   ❌ {e}")
        return False


def check_groq() -> bool:
    print("\n▶ Groq (fallback)")
    print(f"   Модель: {GROQ_MODEL}")
    if not GROQ_KEY:
        print("   ❌ GROQ_API_KEY не задан")
        return False
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": GROQ_MODEL,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 5,
            },
            timeout=30,
        )
        print(f"   HTTP {r.status_code}")
        if r.status_code >= 400:
            print(f"   ❌ Ошибка: {r.text[:200]}")
            return False
        print("   ✅ Запрос прошёл")
        fmt_headers(dict(r.headers), "x-ratelimit")
        return True
    except Exception as e:
        print(f"   ❌ {e}")
        return False


def check_jina() -> bool:
    print("\n▶ Jina (поиск по базе)")
    print(f"   Модель: {JINA_MODEL}")
    if not JINA_KEY:
        print("   ❌ JINA_API_KEY не задан")
        return False
    try:
        r = requests.post(
            "https://api.jina.ai/v1/embeddings",
            headers={
                "Authorization": f"Bearer {JINA_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": JINA_MODEL,
                "task": "text-matching",
                "input": ["тест лимита"],
            },
            timeout=30,
        )
        print(f"   HTTP {r.status_code}")
        if r.status_code >= 400:
            print(f"   ❌ Ошибка: {r.text[:200]}")
            return False
        print("   ✅ Запрос прошёл")
        fmt_headers(dict(r.headers), "x-ratelimit")
        return True
    except Exception as e:
        print(f"   ❌ {e}")
        return False


def main() -> None:
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    print("=" * 60)
    print("Проверка лимитов ИИ для EMAR Bot")
    print("=" * 60)

    c = check_claude()
    g = check_groq()
    j = check_jina()

    print("\n" + "=" * 60)
    if c and j:
        print("✅ Claude + Jina отвечают — бот может работать.")
    elif g and j:
        print("⚠️  Claude нет, но Groq+Jina есть — ответы пойдут через fallback.")
    else:
        print("⚠️  Есть проблемы — смотрите выше.")
    print("=" * 60)


if __name__ == "__main__":
    main()
