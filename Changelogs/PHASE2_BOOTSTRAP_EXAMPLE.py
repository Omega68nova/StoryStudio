from __future__ import annotations

"""Reference bootstrap for the consolidated Phase 1 + Phase 2 architecture."""

from app.services.events import EventHub
from app.services.runtimes import ProcessSupervisor
from app.services.scheduler import GenerationScheduler


def create_generation_scheduler(db):
    events = EventHub()
    supervisor = ProcessSupervisor()

    # Default Story/Image/Planning handlers are registered lazily by the
    # scheduler for migration compatibility.
    scheduler = GenerationScheduler(
        db,
        events,
        supervisor,
    )
    return scheduler, events, supervisor
