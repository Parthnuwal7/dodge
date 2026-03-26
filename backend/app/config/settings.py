from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Neo4j Aura
    neo4j_uri: str
    neo4j_user: str
    neo4j_password: str

    # LLM via OpenRouter (primary)
    openrouter_api_key: str
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    llm_model: str = ""

    # LLM via Groq (fallback)
    groq_api_key: str = ""
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_model: str = "llama-3.3-70b-versatile"

    # Data
    data_dir: str = str(Path(__file__).resolve().parents[3] / "sap-order-to-cash-dataset" / "sap-o2c-data")
    cypher_template_dir: str = str(Path(__file__).resolve().parents[2] / "templates" / "cypher")

    # General
    log_level: str = "INFO"

    # Supabase (optional chat logging)
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    supabase_chat_table: str = "chat_logs"
    supabase_db_url: str = ""

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }


def get_settings() -> Settings:
    return Settings()
