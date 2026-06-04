from app.models import MeetingState, MeetingStatus, MeetingStatusResponse


def test_status_response_exposes_voiceprint_state():
    state = MeetingState(
        id="meeting-1",
        status=MeetingStatus.TRANSCRIBED,
        speaker_embeddings={"Speaker 1": [1.0, 0.0]},
        voiceprint_status="ready",
    )

    response = MeetingStatusResponse.from_state(state)

    assert response.voiceprints_ready is True
    assert response.voiceprint_status == "ready"
