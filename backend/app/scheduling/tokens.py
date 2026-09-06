"""Random token generation for signed links.

Used for the candidate availability / slot-selection links and interviewer seat
offers (the link *handling* is teammate-owned; this is just the token primitive).
Kept in its own tiny module so any layer can import it without a cycle.
"""

from __future__ import annotations

import secrets


def generate_link_token() -> str:
    """Return a URL-safe, unguessable token (~43 chars, CSPRNG).

    Enough entropy to be the bearer credential for a link on its own. A real
    deployment could swap this for an HMAC of the target id if it wanted stateless
    verification.
    """

    return secrets.token_urlsafe(32)


# Backwards-compatible alias.
generate_confirmation_token = generate_link_token
