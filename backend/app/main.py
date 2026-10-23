from __future__ import annotations

import shutil
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.api.score_routes import router as score_router
from app.api.conversion_routes import router as conversion_router


# ── Dependency check ──
def _check_dependencies():
    missing = []
    for cmd in ("ffmpeg", "ffprobe"):
        if shutil.which(cmd) is None:
            missing.append(cmd)
    if missing:
        print(
            f"❌ 缺少系统依赖: {', '.join(missing)}",
            file=sys.stderr,
        )
        print("   安装方法:", file=sys.stderr)
        print("   macOS:  brew install ffmpeg", file=sys.stderr)
        print("   Ubuntu: sudo apt install ffmpeg", file=sys.stderr)
        print("   Windows: winget install --id=Gyan.FFmpeg -e", file=sys.stderr)
        sys.exit(1)
    else:
        print("✅ 系统依赖检查通过 (ffmpeg / ffprobe)")


_check_dependencies()


app = FastAPI(title="Guitar Score Extraction API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")
app.include_router(score_router, prefix="/api")
app.include_router(conversion_router, prefix="/api")

# Serve the production frontend from the same origin as the API.
frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if (frontend_dist / "index.html").is_file():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
