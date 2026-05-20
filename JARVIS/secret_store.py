import os
from dataclasses import dataclass

import keyring
from keyring.errors import KeyringError


SERVICE_NAME = "JARVIS Assistant"


@dataclass(frozen=True)
class SecretSpec:
    id: str
    label: str
    env_name: str
    keyring_name: str
    expected_prefix: str


LLM_TOKEN = SecretSpec(
    id="llm_token",
    label="io.net token",
    env_name="JARVIS_LLM_TOKEN",
    keyring_name="llm_token",
    expected_prefix="io-v2-",
)

OPENROUTER_API_KEY = SecretSpec(
    id="openrouter_api_key",
    label="OpenRouter API key",
    env_name="JARVIS_OPENROUTER_API_KEY",
    keyring_name="openrouter_api_key",
    expected_prefix="sk-or-",
)

REQUIRED_SECRETS = (LLM_TOKEN, OPENROUTER_API_KEY)


class SecretStoreError(RuntimeError):
    pass


def get_secret(spec: SecretSpec) -> str | None:
    env_value = os.getenv(spec.env_name)
    if env_value:
        return env_value.strip()

    try:
        value = keyring.get_password(SERVICE_NAME, spec.keyring_name)
    except KeyringError as exc:
        raise SecretStoreError(f"Не удалось прочитать {spec.label} из системного хранилища: {exc}") from exc

    return value.strip() if value else None


def set_secret(spec: SecretSpec, value: str) -> None:
    try:
        keyring.set_password(SERVICE_NAME, spec.keyring_name, value.strip())
    except KeyringError as exc:
        raise SecretStoreError(f"Не удалось сохранить {spec.label} в системное хранилище: {exc}") from exc


def has_all_required_secrets() -> bool:
    return all(get_secret(spec) for spec in REQUIRED_SECRETS)


def missing_required_secrets() -> list[SecretSpec]:
    return [spec for spec in REQUIRED_SECRETS if not get_secret(spec)]


def validate_secret_format(spec: SecretSpec, value: str) -> str | None:
    value = value.strip()
    if not value:
        return f"{spec.label}: ключ не заполнен."
    if not value.startswith(spec.expected_prefix):
        return f"{spec.label}: похоже, ключ перепутан. Ожидается начало `{spec.expected_prefix}`."
    return None


def save_required_secrets(values: dict[str, str]) -> None:
    for spec in REQUIRED_SECRETS:
        error = validate_secret_format(spec, values.get(spec.id, ""))
        if error:
            raise SecretStoreError(error)

    for spec in REQUIRED_SECRETS:
        set_secret(spec, values[spec.id])
