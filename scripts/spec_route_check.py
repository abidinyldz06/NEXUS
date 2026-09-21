# -*- coding: utf-8 -*-
"""Spec test vakalari: classifier.dev shadow-mode dogrulama."""
from nexus.config import NexusConfig
from nexus.decision import route_text
import time

CASES = [
    ("Merhaba Hermes nasılsın?", "chat"),
    ("Mac mini'de terminali aç ve sistemi kontrol et.", "command"),
    ("Yarın saat 10'da Ahmet'i aramamı hatırlat.", "task"),
    ("Dün NEXUS için ne karar vermiştik?", "memory"),
    ("Bugünkü yapay zeka haberlerini araştır.", "research"),
    ("Bu Python hatasını bul ve düzelt.", "coding"),
    ("asdf123", "unknown"),
]

cfg = NexusConfig.from_mapping(
    {
        "decision_classifier_enabled": True,
        "decision_classifier_executable": "/Users/abidin/.local/lib/node_modules/classifier-dev/classify.js",
    }
)
latencies = []
passes = 0
for text, expected in CASES:
    t0 = time.perf_counter()
    r = route_text(text, cfg)
    ms = (time.perf_counter() - t0) * 1000
    latencies.append(ms)
    got = r.category.value
    # task/reminder esnekligi: reminder da task ailesi
    ok = got == expected or (expected == "task" and got == "reminder")
    ok_display = "OK " if ok else "X  "
    if ok:
        passes += 1
    print(
        f"{ok_display} exp={expected:<9} got={got:<22} conf={r.confidence:.2f} "
        f"backend={r.backend} review={str(r.needs_human_review):<5} {ms:.0f}ms"
    )
print(f"\nSONUC: {passes}/{len(CASES)} beklenen kategori")
print(f"LATENCY: min={min(latencies):.0f}ms ort={sum(latencies)/len(latencies):.0f}ms max={max(latencies):.0f}ms")