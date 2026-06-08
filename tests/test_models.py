from app.models import MeetingHistoryItem, MeetingState, MeetingStatus, MeetingStatusResponse, SpeakerTurn


def test_status_response_exposes_voiceprint_state():
    state = MeetingState(
        id="meeting-1",
        name="Weekly Sync",
        status=MeetingStatus.TRANSCRIBED,
        speaker_embeddings={"Speaker 1": [1.0, 0.0]},
        voiceprint_status="ready",
    )

    response = MeetingStatusResponse.from_state(state)

    assert response.voiceprints_ready is True
    assert response.voiceprint_status == "ready"


def test_history_item_summarizes_meeting():
    state = MeetingState(
        id="meeting-1",
        name="Weekly Sync",
        status=MeetingStatus.READY,
        transcript=[
            SpeakerTurn(speaker="Speaker 1", text="Ship the history view."),
            SpeakerTurn(speaker="Speaker 2", text="Add meeting labels."),
        ],
        speaker_names={"Speaker 1": "Avi", "Speaker 2": "Priya"},
        mom_markdown="# Minutes",
    )

    item = MeetingHistoryItem.from_state(state)

    assert item.name == "Weekly Sync"
    assert item.speakers == ["Avi", "Priya"]
    assert item.transcript_turns == 2
    assert item.word_count == 7
    assert item.mom_available is True


def test_meeting_state_history_visibility_defaults_to_true():
    state = MeetingState(id="meeting-1", name="Weekly Sync", status=MeetingStatus.UPLOADED)

    assert state.visible_in_history is True
