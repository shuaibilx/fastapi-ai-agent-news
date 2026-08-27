import os
import unittest

from pydantic import ValidationError


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
        self.assertEqual(
            settings.agent_checkpointer_redis_url,
            "redis://cache.example:6380/0",
        )

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

    def test_reads_bounded_agent_settings_from_server_environment(self):
        os.environ.update({
            "AI_AGENT_HISTORY_MAX_ROUNDS": "5",
            "AI_AGENT_HISTORY_MAX_TOKENS": "2500",
            "AI_AGENT_TOOL_RESULT_MAX_TOKENS": "3500",
            "AI_AGENT_INPUT_MAX_TOKENS": "9000",
            "AI_AGENT_MEMORY_TTL_SECONDS": "7200",
            "AI_AGENT_MAX_ITERATIONS": "4",
        })

        from app.core.config import Settings

        settings = Settings()

        self.assertEqual(settings.ai_agent_history_max_rounds, 5)
        self.assertEqual(settings.ai_agent_history_max_tokens, 2500)
        self.assertEqual(settings.ai_agent_tool_result_max_tokens, 3500)
        self.assertEqual(settings.ai_agent_input_max_tokens, 9000)
        self.assertEqual(settings.ai_agent_memory_ttl_seconds, 7200)
        self.assertEqual(settings.ai_agent_max_iterations, 4)

    def test_rejects_non_positive_agent_limits(self):
        from app.core.config import Settings

        with self.assertRaises(ValidationError):
            Settings(
                ai_agent_history_max_rounds=0,
                ai_agent_max_iterations=0,
            )

    def test_reads_token_memory_settings_and_allows_optional_summary_model(self):
        from app.core.config import Settings

        settings = Settings(
            ai_agent_summary_trigger_tokens=6000,
            ai_agent_summary_keep_tokens=2500,
            ai_agent_summary_model=None,
            ai_agent_input_max_tokens=10000,
            ai_agent_memory_ttl_seconds=7200,
        )

        self.assertEqual(settings.ai_agent_summary_trigger_tokens, 6000)
        self.assertEqual(settings.ai_agent_summary_keep_tokens, 2500)
        self.assertIsNone(settings.ai_agent_summary_model)
        self.assertEqual(settings.ai_agent_memory_ttl_seconds, 7200)

    def test_reads_semantic_retrieval_settings_from_server_environment(self):
        os.environ.update({
            "EMBEDDING_BASE_URL": "http://embedding.example:8081",
            "EMBEDDING_MODEL": "bge-large-zh-v1.5",
            "EMBEDDING_TIMEOUT_SECONDS": "20",
            "AI_SEMANTIC_INDEX_NAME": "idx:news:vector:v1",
            "AI_SEMANTIC_KEY_PREFIX": "ai:news:vector:v1:",
            "AI_SEMANTIC_VECTOR_DIMENSIONS": "1024",
            "AI_SEMANTIC_BATCH_SIZE": "24",
            "AI_SEMANTIC_RETRIEVAL_LIMIT": "6",
            "AI_SEMANTIC_SCORE_THRESHOLD": "0.35",
        })

        from app.core.config import Settings

        settings = Settings()

        self.assertEqual(settings.embedding_base_url, "http://embedding.example:8081")
        self.assertEqual(settings.embedding_model, "bge-large-zh-v1.5")
        self.assertEqual(settings.embedding_timeout_seconds, 20)
        self.assertEqual(settings.ai_semantic_index_name, "idx:news:vector:v1")
        self.assertEqual(settings.ai_semantic_key_prefix, "ai:news:vector:v1:")
        self.assertEqual(settings.ai_semantic_vector_dimensions, 1024)
        self.assertEqual(settings.ai_semantic_batch_size, 24)
        self.assertEqual(settings.ai_semantic_retrieval_limit, 6)
        self.assertEqual(settings.ai_semantic_score_threshold, 0.35)

    def test_uses_a_safe_default_batch_size_for_the_local_tei_cpu_backend(self):
        from app.core.config import Settings

        settings = Settings()

        self.assertEqual(settings.ai_semantic_batch_size, 4)

    def test_rejects_summary_keep_window_that_is_not_smaller_than_trigger(self):
        from app.core.config import Settings

        with self.assertRaises(ValidationError):
            Settings(
                ai_agent_summary_trigger_tokens=3000,
                ai_agent_summary_keep_tokens=3000,
            )

    def test_rejects_summary_trigger_that_exceeds_input_budget(self):
        from app.core.config import Settings

        with self.assertRaises(ValidationError):
            Settings(
                ai_agent_summary_trigger_tokens=10000,
                ai_agent_summary_keep_tokens=4000,
                ai_agent_input_max_tokens=10000,
            )

    def tearDown(self):
        for key in (
            "MYSQL_HOST", "MYSQL_PORT", "MYSQL_USER", "MYSQL_PASSWORD",
            "MYSQL_DATABASE", "REDIS_HOST", "REDIS_PORT", "REDIS_DB",
            "LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL", "LLM_TIMEOUT_SECONDS",
            "AI_SUMMARY_MAX_CHARACTERS", "AI_SUMMARY_CACHE_TTL_SECONDS",
            "AI_AGENT_HISTORY_MAX_ROUNDS", "AI_AGENT_HISTORY_MAX_TOKENS",
            "AI_AGENT_TOOL_RESULT_MAX_TOKENS", "AI_AGENT_INPUT_MAX_TOKENS",
            "AI_AGENT_MEMORY_TTL_SECONDS", "AI_AGENT_MAX_ITERATIONS",
            "AI_AGENT_SUMMARY_TRIGGER_TOKENS", "AI_AGENT_SUMMARY_KEEP_TOKENS",
            "AI_AGENT_SUMMARY_MODEL",
            "EMBEDDING_BASE_URL", "EMBEDDING_MODEL", "EMBEDDING_TIMEOUT_SECONDS",
            "AI_SEMANTIC_INDEX_NAME", "AI_SEMANTIC_KEY_PREFIX",
            "AI_SEMANTIC_VECTOR_DIMENSIONS", "AI_SEMANTIC_BATCH_SIZE",
            "AI_SEMANTIC_RETRIEVAL_LIMIT", "AI_SEMANTIC_SCORE_THRESHOLD",
        ):
            os.environ.pop(key, None)


if __name__ == "__main__":
    unittest.main()
