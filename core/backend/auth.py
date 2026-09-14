from os import PathLike, getenv
from secrets import compare_digest

from fastapi import HTTPException, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from logtools import getLogger

logger = getLogger()
security = HTTPBasic()

AUTH_USERNAME: str | None = getenv("DLF_AUTH_USERNAME")
AUTH_PASSWORD: str | None = getenv("DLF_AUTH_PASSWORD")


class AuthStaticFiles(StaticFiles):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

    async def __call__(self, scope, receive, send) -> None:
        assert scope["type"] == "http"
        request = Request(scope, receive)
        await self.authenticate(request)
        await super().__call__(scope, receive, send)

    async def authenticate(self, request: Request) -> None:
        """Require valid basic-auth credentials for frontend entry points when configured."""
        if AUTH_USERNAME is None or AUTH_PASSWORD is None:
            return  # No authentication required
        if request.url.path not in ["/", "/index.html"]:
            return  # No authentication required for other paths
        credentials: HTTPBasicCredentials | None = await security(request)
        if credentials is None:
            raise HTTPException(
                status_code=401,
                detail="Invalid authentication credentials",
                headers={
                    "WWW-Authenticate": "Basic",
                },
            )
        correct_username: bool = compare_digest(credentials.username, AUTH_USERNAME)
        correct_password: bool = compare_digest(credentials.password, AUTH_PASSWORD)
        if not (correct_username and correct_password):
            raise HTTPException(
                status_code=401,
                detail="Invalid authentication token",
                headers={"WWW-Authenticate": "Basic"},
            )


def create_auth_enabled_static_files(
    directory: PathLike[str] | None = None,
    packages: list[str | tuple[str, str]] | None = None,
    html: bool = False,
    check_dir: bool = True,
    follow_symlink: bool = False,
) -> StaticFiles:
    """Injects basic authentication into the StaticFiles class if the AUTH_ env variables are set.

    Returns:
        StaticFiles: the StaticFiles class with or without basic authentication
    """
    if AUTH_USERNAME and AUTH_PASSWORD:
        logger.info("Basic authentication enabled, no requests for frontend will be accepted without credentials.")
        return AuthStaticFiles(directory=directory, packages=packages, html=html, check_dir=check_dir, follow_symlink=follow_symlink)
    else:
        logger.info("Basic authentication for frontend disabled.")
        return StaticFiles(directory=directory, packages=packages, html=html, check_dir=check_dir, follow_symlink=follow_symlink)
