import pytest

from opsctl.config import (
    DEFAULT_CPU_THRESHOLD_PERCENT,
    DEFAULT_RESOURCE_GROUP,
    ConfigError,
    load_config,
)

VALID_SUBSCRIPTION_ID = "00000000-0000-0000-0000-000000000000"


def test_uses_defaults_when_optional_settings_are_missing():
    environ = {"AZURE_SUBSCRIPTION_ID": VALID_SUBSCRIPTION_ID}

    config = load_config(environ)

    assert config.resource_group == DEFAULT_RESOURCE_GROUP
    assert config.cpu_threshold_percent == DEFAULT_CPU_THRESHOLD_PERCENT
    assert config.webhook_url is None


def test_reads_and_strips_all_settings():
    # Arrange: values padded with whitespace, as often happens when editing .env by hand
    environ = {
        "AZURE_SUBSCRIPTION_ID": f"  {VALID_SUBSCRIPTION_ID}  ",
        "RESOURCE_GROUP": " rg-custom ",
        "WEBHOOK_URL": " https://example.com/hook ",
        "CPU_THRESHOLD": " 65.5 ",
    }

    # Act
    config = load_config(environ)

    # Assert
    assert config.subscription_id == VALID_SUBSCRIPTION_ID
    assert config.resource_group == "rg-custom"
    assert config.webhook_url == "https://example.com/hook"
    assert config.cpu_threshold_percent == 65.5


def test_treats_blank_webhook_url_as_not_configured():
    environ = {"AZURE_SUBSCRIPTION_ID": VALID_SUBSCRIPTION_ID, "WEBHOOK_URL": "   "}

    config = load_config(environ)

    assert config.webhook_url is None


@pytest.mark.parametrize("subscription_id", [None, "", "   "])
def test_raises_when_subscription_id_is_missing(subscription_id):
    environ = {} if subscription_id is None else {"AZURE_SUBSCRIPTION_ID": subscription_id}

    with pytest.raises(ConfigError, match="AZURE_SUBSCRIPTION_ID is not set"):
        load_config(environ)


def test_raises_when_subscription_id_is_not_a_guid():
    environ = {"AZURE_SUBSCRIPTION_ID": "my-subscription"}

    with pytest.raises(ConfigError, match="must be a GUID"):
        load_config(environ)


def test_raises_when_cpu_threshold_is_not_a_number():
    environ = {"AZURE_SUBSCRIPTION_ID": VALID_SUBSCRIPTION_ID, "CPU_THRESHOLD": "high"}

    with pytest.raises(ConfigError, match="must be a number"):
        load_config(environ)


@pytest.mark.parametrize("threshold", ["0", "-5", "100.1", "250"])
def test_raises_when_cpu_threshold_is_out_of_range(threshold):
    environ = {"AZURE_SUBSCRIPTION_ID": VALID_SUBSCRIPTION_ID, "CPU_THRESHOLD": threshold}

    with pytest.raises(ConfigError, match="CPU_THRESHOLD must be greater than"):
        load_config(environ)


def test_accepts_cpu_threshold_at_upper_bound():
    environ = {"AZURE_SUBSCRIPTION_ID": VALID_SUBSCRIPTION_ID, "CPU_THRESHOLD": "100"}

    config = load_config(environ)

    assert config.cpu_threshold_percent == 100.0
