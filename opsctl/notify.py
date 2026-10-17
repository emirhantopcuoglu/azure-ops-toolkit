"""Send alert messages to a Discord or Slack incoming webhook."""

from collections.abc import Callable
from urllib.parse import urlparse

import requests

WEBHOOK_TIMEOUT_SECONDS = 5
SLACK_WEBHOOK_HOST = "hooks.slack.com"
# Discord rejects messages longer than 2000 characters
MAX_MESSAGE_LENGTH = 2000
TRUNCATION_MARKER = "..."


class NotificationError(Exception):
    """Raised when the webhook does not accept the message."""


def build_payload(webhook_url: str, message: str) -> dict[str, str]:
    """Discord expects the text under "content", Slack under "text"."""
    text = _truncate(message)
    if urlparse(webhook_url).hostname == SLACK_WEBHOOK_HOST:
        return {"text": text}
    return {"content": text}


def send_webhook_message(
    webhook_url: str, message: str, post: Callable[..., requests.Response] = requests.post
) -> None:
    try:
        response = post(webhook_url, json=build_payload(webhook_url, message), timeout=WEBHOOK_TIMEOUT_SECONDS)
        response.raise_for_status()
    except requests.HTTPError as error:
        # requests puts the full URL in its messages; the webhook URL is a secret
        raise NotificationError(f"webhook rejected the message with status {error.response.status_code}") from None
    except requests.RequestException as error:
        raise NotificationError(f"webhook request failed: {type(error).__name__}") from None


def _truncate(message: str) -> str:
    if len(message) <= MAX_MESSAGE_LENGTH:
        return message
    return message[: MAX_MESSAGE_LENGTH - len(TRUNCATION_MARKER)] + TRUNCATION_MARKER
