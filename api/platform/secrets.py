"""Credential encryption: CMS secrets are ciphertext at rest, always.

``FernetCipher`` (AES-128-CBC + HMAC via cryptography's Fernet) is the local
and design-partner implementation; ``KmsCipher`` is the GCP Cloud KMS
envelope for production. Both sit behind ``SecretsCipher`` so switching is a
config change (guiding principle #3). Plaintext credentials never touch the
database — the schema column is ``cms_credentials_enc`` on purpose.
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod

from cryptography.fernet import Fernet


class SecretsCipher(ABC):
    @abstractmethod
    def encrypt(self, secrets: dict) -> str: ...

    @abstractmethod
    def decrypt(self, ciphertext: str) -> dict: ...


class FernetCipher(SecretsCipher):
    def __init__(self, key: str):
        self._fernet = Fernet(key.encode())

    @staticmethod
    def generate_key() -> str:
        return Fernet.generate_key().decode()

    def encrypt(self, secrets: dict) -> str:
        return self._fernet.encrypt(json.dumps(secrets).encode()).decode()

    def decrypt(self, ciphertext: str) -> dict:
        return json.loads(self._fernet.decrypt(ciphertext.encode()))


class KmsCipher(SecretsCipher):
    """GCP Cloud KMS envelope encryption. Constructed only when
    CASELINE_KMS_KEY_NAME is configured on a GCP deployment."""

    def __init__(self, key_name: str):
        from google.cloud import kms  # type: ignore[import-not-found]

        self._client = kms.KeyManagementServiceClient()
        self._key_name = key_name

    def encrypt(self, secrets: dict) -> str:
        import base64

        resp = self._client.encrypt(
            request={"name": self._key_name, "plaintext": json.dumps(secrets).encode()}
        )
        return base64.b64encode(resp.ciphertext).decode()

    def decrypt(self, ciphertext: str) -> dict:
        import base64

        resp = self._client.decrypt(
            request={"name": self._key_name, "ciphertext": base64.b64decode(ciphertext)}
        )
        return json.loads(resp.plaintext)


def make_cipher(
    fernet_key: str | None = None, kms_key_name: str | None = None
) -> SecretsCipher:
    kms_key_name = kms_key_name or os.getenv("CASELINE_KMS_KEY_NAME")
    if kms_key_name:
        return KmsCipher(kms_key_name)
    fernet_key = fernet_key or os.getenv("CASELINE_SECRETS_KEY")
    if not fernet_key:
        raise RuntimeError(
            "No secrets key configured. Set CASELINE_SECRETS_KEY (generate one with"
            " `python -c 'from api.platform.secrets import FernetCipher;"
            " print(FernetCipher.generate_key())'`) or CASELINE_KMS_KEY_NAME on GCP."
        )
    return FernetCipher(fernet_key)
