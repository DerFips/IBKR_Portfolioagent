import uvicorn
from .settings import Settings

if __name__ == "__main__":
    s = Settings()
    uvicorn.run(
        "src.agent.api.main:app",
        host=s.dashboard_host,
        port=s.dashboard_port,
        reload=False,
    )
