MARKETS = ("US", "UK", "DE", "FR")


def normalize(code: str) -> str:
    code = (code or "").strip().upper()
    # Common aliases.
    if code in ("GB", "EN-GB"):
        code = "UK"
    if code not in MARKETS:
        raise ValueError(f"Unknown market {code!r}; expected one of {MARKETS}")
    return code
