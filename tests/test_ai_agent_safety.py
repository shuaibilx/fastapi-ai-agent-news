import pytest

from app.ai.agent.safety import SensitiveDataBlocked, sanitize_text, sanitize_value


@pytest.mark.parametrize(
    "value",
    [
        "联系 alice@example.com",
        "银行卡 4111 1111 1111 1111",
        "服务器 192.168.1.10",
        "手机号 13812345678",
        "身份证 11010119900307001X",
    ],
)
def test_personal_information_is_redacted(value):
    redacted = sanitize_text(value)

    assert redacted != value
    assert all(secret not in redacted for secret in [
        "alice@example.com", "4111 1111 1111 1111", "192.168.1.10",
        "13812345678", "11010119900307001X",
    ])


@pytest.mark.parametrize(
    "value",
    [
        "api_key=sk-test-12345678901234567890",
        "Authorization: Bearer abcdefghijklmnop123456",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.signature-value-1234",
        "-----BEGIN RSA PRIVATE KEY-----\nsecret\n-----END RSA PRIVATE KEY-----",
    ],
)
def test_credentials_are_blocked_before_model_or_persistence(value):
    with pytest.raises(SensitiveDataBlocked):
        sanitize_text(value)


def test_nested_artifacts_are_sanitized_without_mutating_original_value():
    artifact = {"title": "联系 alice@example.com", "items": ["手机号 13812345678"]}

    redacted = sanitize_value(artifact)

    assert redacted != artifact
    assert artifact["title"] == "联系 alice@example.com"
    assert "alice@example.com" not in redacted["title"]
    assert "13812345678" not in redacted["items"][0]
