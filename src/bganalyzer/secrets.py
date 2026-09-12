"""Secrets management using system keyring."""

import keyring
from keyring.errors import KeyringError, KeyringLocked, NoKeyringError

from bganalyzer.config import AppConfig
from bganalyzer.logging_config import get_logger

logger = get_logger(__name__)

SERVICE_NAME = "bganalyzer"
KEYRING_USERNAME = "nightscout"


class CredentialProvider:
    """Manages Nightscout credentials using system keyring with session fallback."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._session_token: str | None = None
        self._session_origin: str | None = None

    def get_token(self) -> str | None:
        """Get the stored access token."""
        if self._session_token and self._session_origin == self.config.nightscout.origin:
            return self._session_token
        return self._get_from_keyring()

    def _get_from_keyring(self) -> str | None:
        """Retrieve token from system keyring."""
        try:
            token = keyring.get_password(SERVICE_NAME, self.config.nightscout.origin)
            if token:
                logger.debug("Retrieved token from keyring")
            return token
        except (KeyringError, NoKeyringError) as e:
            logger.warning(
                "Keyring unavailable, using session fallback", error_type=type(e).__name__
            )
            return None
        except KeyringLocked:
            logger.warning("Keyring locked, using session fallback")
            return None

    def set_token(self, token: str, persistent: bool = True) -> bool:
        """Store the access token."""
        self._session_token = token
        self._session_origin = self.config.nightscout.origin
        if not persistent:
            logger.info("Stored token in session only")
            return True
        try:
            keyring.set_password(SERVICE_NAME, self.config.nightscout.origin, token)
            logger.info("Stored token in keyring")
            return True
        except (KeyringError, NoKeyringError) as e:
            logger.warning(
                "Failed to store token in keyring, using session only", error_type=type(e).__name__
            )
            return False
        except KeyringLocked:
            logger.warning("Keyring locked, stored token in session only")
            return False

    def clear_token(self) -> None:
        """Clear stored token."""
        self._session_token = None
        try:
            keyring.delete_password(SERVICE_NAME, self.config.nightscout.origin)
            logger.info("Cleared token from keyring")
        except (KeyringError, NoKeyringError):
            pass
        except KeyringLocked:
            logger.warning("Keyring locked, could not clear persistent token")

    def is_available(self) -> bool:
        """Check if keyring is available."""
        try:
            keyring.get_keyring()
            return True
        except (NoKeyringError, KeyringError):
            return False


class AtlasCredentialProvider(CredentialProvider):
    """Separate keyring namespace, bound to Nightscout origin and Atlas database."""

    def __init__(self, config):
        super().__init__(config)
        self._atlas_session = {}

    def _identity(self):
        return "atlas:" + self.config.nightscout.origin + ":" + self.config.atlas.database

    def get_token(self):
        identity = self._identity()
        if identity in self._atlas_session:
            return self._atlas_session[identity]
        try:
            return keyring.get_password(SERVICE_NAME, identity)
        except KeyringError:
            return None

    def set_token(self, token, persistent=True):
        identity = self._identity()
        self._atlas_session[identity] = token
        if persistent:
            try:
                keyring.set_password(SERVICE_NAME, identity, token)
            except KeyringError:
                return False
        return True
