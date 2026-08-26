import os
import unittest


class SettingsTest(unittest.TestCase):
    def test_builds_mysql_and_redis_urls_from_one_settings_object(self):
        os.environ.update({
            "MYSQL_HOST": "db.example",
            "MYSQL_PORT": "3307",
            "MYSQL_USER": "app",
            "MYSQL_PASSWORD": "secret",
            "MYSQL_DATABASE": "toutiao",
            "REDIS_HOST": "cache.example",
            "REDIS_PORT": "6380",
            "REDIS_DB": "2",
        })

        from app.core.config import Settings

        settings = Settings()

        self.assertEqual(
            settings.mysql_url,
            "mysql+aiomysql://app:secret@db.example:3307/toutiao?charset=utf8mb4",
        )
        self.assertEqual(settings.redis_url, "redis://cache.example:6380/2")

    def test_reads_ai_summary_settings_from_server_environment(self):
        os.environ.update({
            "LLM_BASE_URL": "https://llm.example/v1",
            "LLM_API_KEY": "server-only-key",
            "LLM_MODEL": "summary-model",
            "LLM_TIMEOUT_SECONDS": "18",
            "AI_SUMMARY_MAX_CHARACTERS": "360",
            "AI_SUMMARY_CACHE_TTL_SECONDS": "7200",
        })

        from app.core.config import Settings

        settings = Settings()

        self.assertEqual(getattr(settings, "llm_base_url", None), "https://llm.example/v1")
        self.assertEqual(getattr(settings, "llm_api_key", None), "server-only-key")
        self.assertEqual(getattr(settings, "llm_model", None), "summary-model")
        self.assertEqual(getattr(settings, "llm_timeout_seconds", None), 18)
        self.assertEqual(getattr(settings, "ai_summary_max_characters", None), 360)
        self.assertEqual(getattr(settings, "ai_summary_cache_ttl_seconds", None), 7200)

    def tearDown(self):
        for key in (
            "MYSQL_HOST", "MYSQL_PORT", "MYSQL_USER", "MYSQL_PASSWORD",
            "MYSQL_DATABASE", "REDIS_HOST", "REDIS_PORT", "REDIS_DB",
            "LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL", "LLM_TIMEOUT_SECONDS",
            "AI_SUMMARY_MAX_CHARACTERS", "AI_SUMMARY_CACHE_TTL_SECONDS",
        ):
            os.environ.pop(key, None)


if __name__ == "__main__":
    unittest.main()
