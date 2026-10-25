from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    ollama_base_url: str  = Field("http://host.docker.internal:11434/v1")
    ollama_timeout:  int  = Field(600)   # Sekunden pro Anfrage
    ollama_model:    str  = Field("gemma4:e4b")
    llm_provider:      str = Field("ollama")   # ollama | anthropic | nvidia | hermes
    anthropic_api_key: str = Field("")
    anthropic_model:   str = Field("claude-opus-5-5")
    anthropic_effort:  str = Field("medium")  # low|medium|high|xhigh|max
    nvidia_api_key:  str = Field("")        # nvapi-…
    nvidia_model:    str = Field("nvidia/nemotron-3-ultra-550b-a55b")
    nvidia_timeout:  int = Field(900)        # Gesamtdauer pro Anfrage (s)
    nvidia_base_url: str = Field("https://integrate.api.nvidia.com/v1")
    tavily_api_key:  str = Field("")        # tvly-… (Websuche fuer Ollama/NVIDIA)
    hermes_base_url: str = Field("http://host.docker.internal:8642/v1")
    hermes_api_key:  str = Field("")
    hermes_model:    str = Field("hermes-agent")
    hermes_timeout:  int = Field(900)
    ibkr_host:      str   = Field("host.docker.internal")
    ibkr_port:      int   = Field(7497)
    ibkr_client_id: int   = Field(1)
    ibkr_dry_run:   bool  = Field(True)
    dashboard_host:     str = Field("0.0.0.0")
    dashboard_port:     int = Field(8888)
    dashboard_password: str = Field("")
    agent_schedule_enabled: bool = Field(False)   # automatische Runs nach Zeitplan (opt-in)
    agent_run_hour:   int = Field(17)
    agent_run_minute: int = Field(5)
    agent_run_days:   str = Field("mon-fri")
    telegram_enabled:   bool = Field(False)
    telegram_bot_token: str  = Field("")
    telegram_chat_id:   str  = Field("")
    email_enabled:    bool = Field(False)
    email_smtp_host:  str  = Field("smtp.gmail.com")
    email_smtp_port:  int  = Field(587)
    email_smtp_user:  str  = Field("")
    email_smtp_pass:  str  = Field("", validation_alias="EMAIL_SMTP_PASSWORD")
    email_from:       str  = Field("")
    email_to:         str  = Field("")
    nextcloud_enabled:       bool = Field(False)
    nextcloud_url:           str  = Field("")
    nextcloud_user:          str  = Field("")
    nextcloud_password:      str  = Field("")
    nextcloud_remote_folder: str  = Field("Portfolio-Agent")
    benchmark_symbol: str  = Field("SPY")   # Vergleichsindex (ETF), leer = aus
    stop_loss_pct:    float = Field(10.0)      # angenommener Stopp fuer Positionsgroesse
    max_position_pct:       float = Field(10.0)
    max_daily_trades:       int   = Field(5)
    min_confidence:         float = Field(0.65)
    max_risk_pct_per_trade: float = Field(1.0)
    backup_enabled: bool = Field(True)   # taegliche automatische Sicherung
    backup_hour:    int  = Field(3)
    backup_keep:    int  = Field(14)       # so viele automatische Sicherungen behalten
    db_path: str = Field("data/portfolio.db")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8",
                                      extra="ignore", populate_by_name=True)
