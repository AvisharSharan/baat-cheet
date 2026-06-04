from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from app.models import SpeakerTurn
from app.services.speaker_id import SpeakerIdentifier


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract speaker voiceprint embeddings.")
    parser.add_argument("--audio", required=True)
    parser.add_argument("--transcript", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--min-segment-ms", type=int, required=True)
    parser.add_argument("--max-seconds-per-speaker", type=float, required=True)
    args = parser.parse_args()

    os.environ["VOICEPRINTING_ENABLED"] = "1"
    os.environ["VOICEPRINTING_USE_WORKER"] = "0"
    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("MKL_NUM_THREADS", "1")
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

    payload = json.loads(Path(args.transcript).read_text(encoding="utf-8"))
    transcript = [SpeakerTurn.model_validate(item) for item in payload]
    identifier = SpeakerIdentifier(
        min_segment_ms=args.min_segment_ms,
        max_seconds_per_speaker=args.max_seconds_per_speaker,
    )
    embeddings = identifier._extract_speaker_embeddings_direct(args.audio, transcript)
    Path(args.output).write_text(json.dumps(embeddings), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
