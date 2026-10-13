"""Default Vercel entrypoint. The app itself lives in backend.main."""
from backend.main import app as fastapi_app

app = fastapi_app
