from app.auth.events import UserRegistered
from app.auth.models import AuthSession, User
from app.auth.service import AuthService


def register_routes(app) -> None:
	from app.auth.routes import register_routes as register

	register(app)


__all__ = ["AuthSession", "AuthService", "User", "UserRegistered", "register_routes"]