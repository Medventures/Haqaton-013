"""Conservative transcript cleanup. Clinical terms and numbers are untouched."""

import re


def normalize_transcript(text: str) -> str:
    lines = [re.sub(r"[ \t\f\v]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)
