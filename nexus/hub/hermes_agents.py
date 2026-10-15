"""Read-only links to existing Hermes profiles, not a second bot manager."""

ROLES = (
    ("default", "Hermes", "Genel sohbet"),
    ("writer-agent", "Writer Agent", "Yazım"),
    ("research-agent", "Research Agent", "Araştırma"),
    ("coder-agent", "Coder Agent", "Geliştirme"),
    ("scheduler-agent", "Scheduler Agent", "Planlama"),
    ("control-room", "Control Room", "Koordinasyon"),
)

# Bounded alternatives only: never expose arbitrary private profile names.
PROFILE_ALTERNATIVES = {
    "writer-agent": "yazar",
    "research-agent": "arastirmaci",
    "coder-agent": "kodcu",
}


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
    items = []
    for profile, name, role in ROLES:
        alternative = PROFILE_ALTERNATIVES.get(profile)
        selected = profile if profile in existing else (
            alternative if alternative in existing else profile
        )
        present = selected in existing
        items.append({"profile": selected,
                      "name": name if selected == profile else f"{name} ({selected})",
                      "role": role, "present": present,
                      "chat_url": "/chat?profile=" + selected if present else None})
    return {"available": True, "read_only": True, "dispatch_enabled": False,
            "items": items}
