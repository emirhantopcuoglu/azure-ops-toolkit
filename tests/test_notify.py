from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from opsctl.notify import (
    MAX_MESSAGE_LENGTH,
    NotificationError,
    build_payload,
    send_webhook_message,
)

DISCORD_URL = "https://discord.com/api/webhooks/123/secret-token"
SLACK_URL = "https://hooks.slack.com/services/T000/B000/secret-token"


def _ok_response():
    return SimpleNamespace(raise_for_status=lambda: None)


def test_build_payload_uses_content_field_for_discord():
    assert build_payload(DISCORD_URL, "CPU high") == {"content": "CPU high"}


def test_build_payload_uses_text_field_for_slack():
    assert build_payload(SLACK_URL, "CPU high") == {"text": "CPU high"}


def test_build_payload_truncates_messages_over_the_discord_limit():
    payload = build_payload(DISCORD_URL, "x" * (MAX_MESSAGE_LENGTH + 500))

    assert len(payload["content"]) == MAX_MESSAGE_LENGTH
    assert payload["content"].endswith("...")


def test_send_webhook_message_posts_json_with_timeout():
    sent = {}

    def fake_post(url, json, timeout):
        sent.update(url=url, json=json, timeout=timeout)
        return _ok_response()

    send_webhook_message(DISCORD_URL, "CPU high", post=fake_post)

    assert sent == {"url": DISCORD_URL, "json": {"content": "CPU high"}, "timeout": 5}


def test_send_webhook_message_reports_rejection_without_leaking_url():
    # Arrange: requests includes the full URL in HTTPError messages
    def rejecting_post(url, json, timeout):
        error_response = SimpleNamespace(status_code=404)
        http_error = requests.HTTPError(f"404 Client Error for url: {url}", response=error_response)
        return Mock(raise_for_status=Mock(side_effect=http_error))

    # Act
    with pytest.raises(NotificationError) as error_info:
        send_webhook_message(DISCORD_URL, "CPU high", post=rejecting_post)

    # Assert
    assert "status 404" in str(error_info.value)
    assert "secret-token" not in str(error_info.value)
    assert error_info.value.__cause__ is None


def test_send_webhook_message_reports_network_failure_without_leaking_url():
    def failing_post(url, json, timeout):
        raise requests.ConnectionError(f"Max retries exceeded with url: {url}")

    with pytest.raises(NotificationError) as error_info:
        send_webhook_message(DISCORD_URL, "CPU high", post=failing_post)

    assert "ConnectionError" in str(error_info.value)
    assert "secret-token" not in str(error_info.value)
