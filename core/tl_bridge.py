# language: Python, file: core/tl_bridge.py, target: Python 3.10+, Pyrogram + Telethon
"""
Dynamic MTProto Layer 170+ Constructor Bridge for Pyrogram.
Resolves modern Telegram constructors (e.g. 0xd49f34c6 Channel, Layer 180+ Updates)
by bridging to Telethon's Layer 229 schema without desynchronizing the MTProto packet stream.
"""

import io
import datetime
import logging
from typing import Any, cast
import pyrogram.raw.core.tl_object as tl_mod
import pyrogram.raw.all as pyro_all
import pyrogram.raw.types as pyro_types
import telethon.tl.alltlobjects as tele_all
from telethon.extensions import BinaryReader
from telethon.tl.types import Channel as TeleChannel

logger = logging.getLogger(__name__)

class Layer170Channel:
    """Native Pyrogram deserializer for modern Telegram 0xd49f34c6 Channel."""
    ID = 0xd49f34c6
    QUALNAME = "types.Channel"

    @classmethod
    def read(cls, b: io.BytesIO, *args: Any) -> pyro_types.Channel:
        start_pos = b.tell()
        remaining = b.read()
        reader = BinaryReader(remaining)
        tc = TeleChannel.from_reader(reader)
        b.seek(start_pos + reader.position)

        d_val = int(tc.date.timestamp()) if isinstance(tc.date, datetime.datetime) else (tc.date or 0)

        return pyro_types.Channel(
            id=tc.id,
            title=tc.title or "",
            photo=pyro_types.ChatPhotoEmpty(),
            date=d_val,
            creator=tc.creator,
            left=tc.left,
            broadcast=tc.broadcast,
            verified=tc.verified,
            megagroup=tc.megagroup,
            restricted=tc.restricted,
            signatures=tc.signatures,
            min=tc.min,
            scam=tc.scam,
            has_link=tc.has_link,
            has_geo=tc.has_geo,
            slowmode_enabled=tc.slowmode_enabled,
            call_active=tc.call_active,
            call_not_empty=tc.call_not_empty,
            fake=tc.fake,
            gigagroup=tc.gigagroup,
            noforwards=tc.noforwards,
            join_to_send=tc.join_to_send,
            join_request=tc.join_request,
            forum=tc.forum,
            access_hash=tc.access_hash,
            username=tc.username,
            participants_count=tc.participants_count,
        )


class SmartTLObjectsDict(dict):
    """
    Fallback dictionary that intercepts unknown MTProto constructor lookups.
    Uses Telethon's Layer 229 schema to safely consume exact packet bytes.
    """
    def __missing__(self, key: int):
        # Known hot constructor: modern Channel
        if key == 0xd49f34c6:
            self[key] = Layer170Channel
            return Layer170Channel

        # General Telethon Layer 229 fallback
        if key in tele_all.tlobjects:
            tele_cls = tele_all.tlobjects[key]
            class TeleBridgeGeneric:
                ID = key
                QUALNAME = f"telethon.{tele_cls.__name__}"

                @classmethod
                def read(cls, b: io.BytesIO, *args: Any) -> Any:
                    start_pos = b.tell()
                    remaining = b.read()
                    reader = BinaryReader(remaining)
                    try:
                        res = tele_cls.from_reader(reader)
                        b.seek(start_pos + reader.position)
                        return res
                    except Exception as e:
                        logger.debug("[TLBridge] Failed to decode 0x%08x: %s", key, e)
                        return None

            self[key] = TeleBridgeGeneric
            return TeleBridgeGeneric

        raise KeyError(key)


def install_tl_bridge():
    """Installs the universal Layer 170+ MTProto constructor bridge into Pyrogram."""
    smart_dict = SmartTLObjectsDict(tl_mod.objects)
    smart_dict[0xd49f34c6] = Layer170Channel
    tl_mod.objects = smart_dict
    pyro_all.objects = smart_dict
    logger.info("[TLBridge] Universal MTProto Layer 170-229 constructor bridge active.")
