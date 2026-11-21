from pathlib import Path

from fastapi.templating import Jinja2Templates

WEB_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"

templates = Jinja2Templates(directory=TEMPLATES_DIR)
templates.env.globals["asset_version"] = max(int(p.stat().st_mtime) for p in STATIC_DIR.iterdir())
