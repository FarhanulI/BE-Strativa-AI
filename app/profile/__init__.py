from app.profile.events import (
    BusinessContextUpdated,
    ProfileArchived,
    ProfileCreated,
    ProfileMaturityChanged,
    ProfileRestored,
    ProfileUpdated,
)
from app.profile.maturity import MaturityThresholds, compute_stage
from app.profile.models import (
    ContentProfile,
    ProfileBusinessContext,
    ProfileOffer,
    ProfileProduct,
    ProfileServiceItem,
)
from app.profile.service import ProfileService, ProfileVersionConflict


def register_routes(app) -> None:
    from app.profile.routes import register_routes as register

    register(app)


__all__ = [
    "BusinessContextUpdated",
    "ContentProfile",
    "MaturityThresholds",
    "ProfileArchived",
    "ProfileBusinessContext",
    "ProfileCreated",
    "ProfileMaturityChanged",
    "ProfileOffer",
    "ProfileProduct",
    "ProfileRestored",
    "ProfileService",
    "ProfileServiceItem",
    "ProfileUpdated",
    "ProfileVersionConflict",
    "compute_stage",
    "register_routes",
]