from __future__ import annotations

from typing import Any

from app.data.environmentRepository import EnvironmentRepository
from app.data.jobRepository import JobRepository
from app.data.mediaRepository import MediaRepository
from app.data.musicRepository import MusicRepository
from app.data.planningRepository import PlanningRepository
from app.data.projectRepository import ProjectRepository
from app.data.reviewRepository import ReviewRepository
from app.data.soundRepository import SoundRepository
from app.data.storyRepository import StoryRepository
from app.data.workflowRepository import WorkflowRepository
from app.data.worldRepository import WorldRepository
from app.data.lifecycleRepository import LifecycleRepository
from app.data.libraryRepository import LibraryRepository
from app.data.runtimeRepository import RuntimeRepository
from app.data.batchGenerationRepository import BatchGenerationRepository
from app.data.authRepository import AuthRepository
from app.data.rulesRepository import RulesRepository
from app.data.spatialV3Repository import SpatialV3Repository


class DataProvider:
    """Typed repository facade; not a generic SQL/query API."""

    def __init__(self, db: Any) -> None:
        self.db = db
        self.projects = ProjectRepository(db)
        self.stories = StoryRepository(db)
        self.jobs = JobRepository(db)
        self.planning = PlanningRepository(db)
        self.music = MusicRepository(db)
        self.sound = SoundRepository(db)
        self.environment = EnvironmentRepository(db)
        self.media = MediaRepository(db)
        self.reviews = ReviewRepository(db)
        self.workflows = WorkflowRepository(db)
        self.world = WorldRepository(db)
        self.auth = AuthRepository(db)
        self.lifecycle = LifecycleRepository(db)
        self.library = LibraryRepository(db)
        self.runtime = RuntimeRepository(db)
        self.batch_generation = BatchGenerationRepository(db)
        self.rules = RulesRepository(db)
        self.spatial_v3 = SpatialV3Repository(db)
