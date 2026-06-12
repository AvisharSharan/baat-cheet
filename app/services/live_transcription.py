from __future__ import annotations


def new_suffix(previous: str, current: str) -> str:
    """Return only the novel portion of *current* that wasn't already in *previous*.

    Whisper re-transcribes overlapping audio chunks, so successive results share
    a common prefix of words.  This function strips that overlap so the live
    caption stream only appends genuinely new words.

    Usage in main.py _flush():
        from .live_transcription import new_suffix
        # Keep the last emitted text per speaker across flush calls (e.g. a dict).
        suffix = new_suffix(last_text.get(turn.speaker, ""), turn.text)
        if suffix:
            last_text[turn.speaker] = turn.text
            # send suffix to client instead of full turn.text
    """
    previous_words = previous.strip().split()
    current_words = current.strip().split()
    if not previous_words:
        return " ".join(current_words)
    if not current_words:
        return ""
    if current.startswith(previous):
        return current[len(previous):].strip()

    max_overlap = min(len(previous_words), len(current_words))
    for size in range(max_overlap, 0, -1):
        if previous_words[-size:] == current_words[:size]:
            return " ".join(current_words[size:])
    return " ".join(current_words)


# Keep the original private name as an alias so any existing internal
# references don't break while the codebase migrates to the public name.
_new_suffix = new_suffix