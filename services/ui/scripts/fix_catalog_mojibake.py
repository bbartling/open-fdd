"""Fix UTF-8 mojibake in cookbook_catalog equation / label strings."""

from __future__ import annotations

from pathlib import Path

REPLACEMENTS = [
    ("ΓÇö", "—"),
    ("ΓÇô", "–"),
    ("ΓåÆ", "→"),
    ("ΓêÆ", "−"),
    ("ΓëÑ", "≥"),
    ("Γëñ", "≤"),
    ("Γëê", "≈"),
    ("ΓçÆ", "→"),
    ("┬░F", "°F"),
    ("┬░", "°"),
    ("╬öT", "ΔT"),
    ("╬ö", "Δ"),
    ("ΓêÜ", "√"),
    ("┬▓", "²"),
    ("ΓÇª", "…"),
]


def main() -> None:
    path = Path("app/rules/cookbook_catalog.py")
    text = path.read_text(encoding="utf-8")
    orig = text
    for bad, good in REPLACEMENTS:
        text = text.replace(bad, good)
    if text == orig:
        print("No mojibake replacements needed")
    else:
        path.write_text(text, encoding="utf-8")
        print(f"Updated {path}")


if __name__ == "__main__":
    main()
