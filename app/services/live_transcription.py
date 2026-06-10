from __future__ import annotations


def _new_suffix(previous: str, current: str) -> str:
    previous_words = previous.strip().split()
    current_words = current.strip().split()
    if not previous_words:
        return " ".join(current_words)
    if not current_words:
        return ""
    if current.startswith(previous):
        return current[len(previous) :].strip()

    max_overlap = min(len(previous_words), len(current_words))
    for size in range(max_overlap, 0, -1):
        if previous_words[-size:] == current_words[:size]:
            return " ".join(current_words[size:])
    return " ".join(current_words)
