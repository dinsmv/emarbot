"""Регрессионные тесты: python3 test_golden.py [--llm]

По умолчанию LLM отключён (заглушка classify_by_llm).
Флаг --llm включает реальный classify_by_llm.
Не импортирует telegram и bot.py.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

GOLDEN_FILE = Path(__file__).parent / "golden_set.json"
USE_LLM = "--llm" in sys.argv


def main():
    import intent_router
    from priority_qa import match_priority_answer

    if not USE_LLM:
        intent_router.classify_by_llm = lambda text, history=None: (
            intent_router.RouteDecision("rag", "llm-off", 0.0, "llm disabled")
        )

    cases = json.loads(GOLDEN_FILE.read_text(encoding="utf-8"))
    passed = 0
    failed = []

    for case in cases:
        q = case["q"]
        ok = True
        details = []

        if "expect_intent" in case:
            route = intent_router.classify_intent(q, history=None)
            if route.intent != case["expect_intent"]:
                ok = False
                details.append(
                    f"intent: ожидали {case['expect_intent']}, "
                    f"получили {route.intent} (source={route.source})"
                )

        if "expect_contains" in case or "expect_not_contains" in case:
            history = case.get("history")
            answer = match_priority_answer(q, history=history)
            if "expect_contains" in case:
                if answer is None:
                    ok = False
                    details.append(
                        f"contains «{case['expect_contains']}»: ответ = None — priority не сработал!"
                    )
                else:
                    needle = case["expect_contains"].lower()
                    if needle not in answer.lower():
                        ok = False
                        got = answer[:80] + ("…" if len(answer) > 80 else "")
                        details.append(
                            f"contains «{case['expect_contains']}»: ответ = {got}"
                        )
            if "expect_not_contains" in case:
                if answer and case["expect_not_contains"].lower() in answer.lower():
                    ok = False
                    details.append(
                        f"not_contains «{case['expect_not_contains']}»: ответ всё равно содержит это"
                    )

        if ok:
            passed += 1
            print(f"✅ {q}")
        else:
            failed.append((q, details))
            print(f"❌ {q}")
            for d in details:
                print(f"   └─ {d}")

    print("\n" + "=" * 50)
    print(f"ИТОГО: ✅ {passed} / ❌ {len(failed)} из {len(cases)}")
    if failed:
        print("\nУпавшие кейсы:")
        for q, _ in failed:
            print(f"  • {q}")
        sys.exit(1)
    print("Все тесты прошли.")


if __name__ == "__main__":
    main()
