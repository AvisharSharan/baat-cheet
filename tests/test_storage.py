from app.models import MeetingState, MeetingStatus, SpeakerTurn
from app.storage import MeetingStore


def test_meeting_store_persists_history(tmp_path):
    path = tmp_path / "meetings.json"
    store = MeetingStore(path)
    store.add(
        MeetingState(
            id="meeting-1",
            name="Weekly Sync",
            status=MeetingStatus.TRANSCRIBED,
            transcript=[SpeakerTurn(speaker="Speaker 1", text="Persist this meeting.")],
        )
    )

    reloaded = MeetingStore(path)
    meeting = reloaded.get("meeting-1")

    assert meeting.name == "Weekly Sync"
    assert meeting.transcript[0].text == "Persist this meeting."
    assert reloaded.list()[0].id == "meeting-1"


def test_meeting_store_delete_updates_persisted_history(tmp_path):
    path = tmp_path / "meetings.json"
    store = MeetingStore(path)
    store.add(MeetingState(id="meeting-1", name="Weekly Sync", status=MeetingStatus.READY))
    store.delete("meeting-1")

    reloaded = MeetingStore(path)

    assert reloaded.list() == []
