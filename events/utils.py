# MIT License
# Copyright (c) 2024 awolverp

from telethon.tl import types
from telethon.utils import _encode_telegram_base64, _rle_encode
import struct


def pack_bot_file_id(file):
    """
    Inverse operation for `resolve_bot_file_id`.

    The only parameters this method will accept are :tl:`Document` and
    :tl:`Photo`, and it will return a variable-length ``file_id`` string.

    If an invalid parameter is given, it will ``return None``.
    """
    if isinstance(file, types.MessageMediaDocument):
        file = file.document
    elif isinstance(file, types.MessageMediaPhoto):
        file = file.photo

    if isinstance(file, types.Document):
        file_type = 5
        for attribute in file.attributes:
            if isinstance(attribute, types.DocumentAttributeAudio):
                file_type = 3 if attribute.voice else 9
            elif isinstance(attribute, types.DocumentAttributeVideo):
                file_type = 13 if attribute.round_message else 4
            elif isinstance(attribute, types.DocumentAttributeSticker):
                file_type = 8
            elif isinstance(attribute, types.DocumentAttributeAnimated):
                file_type = 10
            else:
                continue
            break

        return _encode_telegram_base64(
            _rle_encode(struct.pack("<iiqqb", file_type, file.dc_id, file.id, file.access_hash, 2))
        )

    elif isinstance(file, types.Photo):
        size = next(
            (
                x
                for x in reversed(file.sizes)
                if isinstance(x, (types.PhotoSize, types.PhotoCachedSize))
            ),
            None,
        )

        if not size:
            return None

        return _encode_telegram_base64(
            _rle_encode(
                struct.pack(
                    "<iiqqqqib",
                    2,
                    file.dc_id,
                    file.id,
                    file.access_hash,
                    0,
                    0,
                    0,
                    2,  # 0 = old `secret`
                )
            )
        )
    else:
        return None
