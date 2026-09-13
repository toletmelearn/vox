"""compose_whatsapp_message (spec Section 6B): drafts only, never sends —
CLAUDE.md invariant 6. No `pynput.keyboard.Controller` (or any synthesised
keystroke) anywhere in this module or anything it calls; the Enter keypress
that actually sends the message is left entirely to the human. See
DECISIONS.md for the reasoning the spec asks to be written down."""
from __future__ import annotations

import difflib
import logging
from dataclasses import dataclass
from urllib.parse import quote

from vox.config import get_settings
from vox.memory.aliases import get_alias_store
from vox.resolver.resolve import resolve_channel
from vox.resolver.targets import get_target_catalogue
from vox.tools.registry import ToolResult, tool

logger = logging.getLogger("vox.tools.messaging")


@dataclass(frozen=True)
class ContactMatch:
    display: str | None
    phone: str | None
    suggestions: list[str]


def _resolve_contact(contact: str, cutoff: float) -> ContactMatch:
    """Exact key -> case-insensitive -> fuzzy (spec Section 6B, cutoff from
    `config.messaging.contact_match_cutoff`). Never guesses a phone number:
    below cutoff, returns the two closest contact names instead of a
    match."""
    contacts = get_alias_store().contacts.all()
    key = contact.strip().lower()
    by_lower = {k.strip().lower(): k for k in contacts}

    matched_key: str | None = None
    if key in by_lower:
        matched_key = by_lower[key]
    else:
        close = difflib.get_close_matches(key, by_lower.keys(), n=1, cutoff=cutoff)
        if close:
            matched_key = by_lower[close[0]]

    if matched_key is not None:
        entry = contacts[matched_key]
        return ContactMatch(display=entry.get("display", matched_key), phone=entry.get("phone"), suggestions=[])

    loose = difflib.get_close_matches(key, by_lower.keys(), n=6, cutoff=0.0)
    suggestions: list[str] = []
    for name in loose:
        display = contacts[by_lower[name]].get("display", name)
        if display not in suggestions:
            suggestions.append(display)
        if len(suggestions) == 2:
            break
    return ContactMatch(display=None, phone=None, suggestions=suggestions)


@tool(
    name="compose_whatsapp_message",
    risk="medium",
    description=(
        "Open a WhatsApp chat with a contact and pre-fill a message. The "
        "message is NOT sent automatically; the user presses Enter."
    ),
)
def compose_whatsapp_message(contact: str, message: str) -> ToolResult:
    settings = get_settings()
    match = _resolve_contact(contact, settings.messaging.contact_match_cutoff)
    if match.phone is None:
        if match.suggestions:
            options = " or ".join(match.suggestions)
            return ToolResult(ok=False, speech=f"I don't have a contact called {contact}. Did you mean {options}?")
        return ToolResult(ok=False, speech=f"I don't have a contact called {contact}.")

    whatsapp = get_target_catalogue().get("whatsapp")
    if whatsapp is None:
        return ToolResult(ok=False, speech="WhatsApp isn't set up.")

    # WhatsApp's click-to-chat convention wants the full international
    # number as digits only — no "+", no spaces/dashes (a literal "+" in a
    # URL query string is otherwise decoded as a space).
    phone_digits = "".join(ch for ch in match.phone if ch.isdigit())
    encoded_message = quote(message)
    deep_link = f"whatsapp://send?phone={phone_digits}&text={encoded_message}"
    web_url = f"https://web.whatsapp.com/send?phone={phone_digits}&text={encoded_message}"

    resolution = resolve_channel(whatsapp, settings, deep_link=deep_link, web_url=web_url)
    if not resolution.ok:
        return ToolResult(ok=False, speech="Couldn't open WhatsApp.")

    return ToolResult(ok=True, speech=f"Message ready for {match.display}. Press Enter to send.")
