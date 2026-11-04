"""NIN / BVN lookup.

The setup screen shows the name registered to a NIN or BVN once all 11
digits are entered. That needs a licensed identity provider (for example
Dojah, Prembly/IdentityPass, Smile ID or VerifyMe). Implement a subclass of
IdentityVerifier for the chosen provider and point the IDENTITY_VERIFIER
setting at it. Until then NullIdentityVerifier is used and no name is shown.
"""

from dataclasses import dataclass

from django.conf import settings
from django.utils.module_loading import import_string


@dataclass(frozen=True)
class IdentityRecord:
    full_name: str


class IdentityVerifier:
    def lookup(self, method, number):
        """Return an IdentityRecord, or None if the number isn't found.

        method is an IdentityMethod value ("nin" or "bvn"). Raise
        IdentityProviderError if the provider can't be reached.
        """
        raise NotImplementedError


class IdentityProviderError(Exception):
    pass


class NullIdentityVerifier(IdentityVerifier):
    def lookup(self, method, number):
        return None


def get_identity_verifier():
    return import_string(settings.IDENTITY_VERIFIER)()
