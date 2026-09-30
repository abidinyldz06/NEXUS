"""Read-only links to existing Hermes profiles, not a second bot manager."""

ROLES = (
    ("default", "Hermes", "Genel sohbet"),
    ("writer-agent", "Writer Agent", "Yazım"),
    ("research-agent", "Research Agent", "Araştırma"),
    ("coder-agent", "Coder Agent", "Geliştirme"),
    ("scheduler-agent", "Scheduler Agent", "Planlama"),
    ("control-room", "Control Room", "Koordinasyon"),
)


def snapshot() -> dict:
    try:
        # Do not use list_profiles: it can migrate configs / seed model settings.
        from hermes_cli.profiles import list_profile_names
        names = list_profile_names()
        if not isinstance(names, list) or any(not isinstance(n, str) for n in names):
            raise ValueError("invalid names")
    except Exception:
        return {"available": False, "items": [], "read_only": True,
                "dispatch_enabled": False, "reason": "Hermes profilleri okunamadı"}
    existing = set(names)
    return {"available": True, "read_only": True, "dispatch_enabled": False,
            "items": [{"profile": profile, "name": name, "role": role,
                       "present": profile in existing,
                       "chat_url": "/chat?profile=" + profile if profile in existing else None}
                      for profile, name, role in ROLES]}
