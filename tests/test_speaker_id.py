import pytest

from app.models import SpeakerTurn
from app.services.speaker_id import SpeakerIdentificationUnavailable, SpeakerIdentifier, VoiceProfileStore


def test_voice_profile_store_upserts_normalized_profiles(tmp_path):
    store = VoiceProfileStore(tmp_path / "profiles.json")

    store.upsert_many({"Asha": [3.0, 4.0]})
    profiles = store.load()

    assert set(profiles) == {"Asha"}
    assert round(sum(value * value for value in profiles["Asha"]), 6) == 1.0


def test_speaker_identifier_matches_profile_above_threshold(tmp_path):
    store = VoiceProfileStore(tmp_path / "profiles.json")
    store.upsert_many({"Asha": [1.0, 0.0, 0.0]})

    identifier = SpeakerIdentifier(store, threshold=0.9)
    labels = identifier.label_speakers({"Speaker 1": [0.99, 0.01, 0.0]}, ["Speaker 1"])

    assert labels == {"Speaker 1": "Asha"}


def test_speaker_identifier_keeps_fallback_below_threshold(tmp_path):
    store = VoiceProfileStore(tmp_path / "profiles.json")
    store.upsert_many({"Asha": [1.0, 0.0, 0.0]})

    identifier = SpeakerIdentifier(store, threshold=0.9)
    labels = identifier.label_speakers({"Speaker 1": [0.0, 1.0, 0.0]}, ["Speaker 1"])

    assert labels == {"Speaker 1": "Speaker 1"}


def test_remember_labels_ignores_unchanged_diarized_labels(tmp_path):
    store = VoiceProfileStore(tmp_path / "profiles.json")
    identifier = SpeakerIdentifier(store)

    identifier.remember_labels(
        {"Speaker 1": [1.0, 0.0], "Speaker 2": [0.0, 1.0]},
        {"Speaker 1": "Speaker 1", "Speaker 2": "Ravi"},
    )

    assert set(store.load()) == {"Ravi"}


def test_extract_embeddings_is_disabled_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv("VOICEPRINTING_ENABLED", raising=False)
    identifier = SpeakerIdentifier(VoiceProfileStore(tmp_path / "profiles.json"))

    with pytest.raises(SpeakerIdentificationUnavailable, match="disabled"):
        identifier._extract_speaker_embeddings_sync(
            "missing.wav",
            [SpeakerTurn(speaker="Speaker 1", text="Hello", start_ms=0, end_ms=1500)],
        )
