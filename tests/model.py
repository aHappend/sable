"""Wire-level oracle derived from SPEC, with no implementation state."""
import struct

LENGTHS = (1, 2, 7, 8, 9, 255, 256, 257, 511, 512, 513, 2047,
           2048, 2049, 4095, 4096)


def crc32c(data):
    c = 0xffffffff
    for byte in data:
        c ^= byte
        for _ in range(8):
            c = (c >> 1) ^ (0x82f63b78 if c & 1 else 0)
    return c ^ 0xffffffff


assert crc32c(b"123456789") == 0xe3069283


def beats(data, application=False, stream=0):
    result = []
    for pos in range(0, len(data), 8):
        part = data[pos:pos + 8]
        result.append((int.from_bytes(part, "little"), (1 << len(part)) - 1,
                       int(pos == 0), int(pos + 8 >= len(data)), stream, len(data))
                      if application else
                      (int.from_bytes(part, "little"), (1 << len(part)) - 1,
                       int(pos == 0), int(pos + 8 >= len(data))))
    return result


def frame(kind, stream, session, identity, message=b"", offset=0):
    payload = message[offset:offset + 256] if kind == 0 else b""
    flags = ((offset == 0) | ((offset + len(payload) == len(message)) << 1)) if kind == 0 else 0
    header = struct.pack("<4sBBHIIHHI", b"SB\x01" + bytes([kind]), stream,
                         flags, len(payload), session, identity,
                         len(message) if kind == 0 else 0, offset if kind == 0 else 0, 0)
    raw = header + payload
    words = beats(header)
    words = [(d, k, int(i == 0), 0) for i, (d, k, _, _) in enumerate(words)]
    words += [(d, k, 0, 0) for d, k, _, _ in beats(payload)]
    words += [(crc32c(raw), 15, 0, 1)]
    return words


def decode(words):
    assert len(words) >= 4, ("short frame", words)
    assert all(k == 255 and f == (i == 0) and not l
               for i, (_, k, f, l) in enumerate(words[:3])), ("header shape", words)
    d, k, f, l = words[-1]
    assert (k, f, l, d >> 32) == (15, 0, 1, 0), ("CRC shape", words[-1])
    header = b"".join(d.to_bytes(8, "little") for d, _, _, _ in words[:3])
    magic, stream, flags, n, session, identity, length, offset, reserved = struct.unpack("<4sBBHIIHHI", header)
    assert magic in (b"SB\x01\x00", b"SB\x01\x01"), ("magic", magic)
    kind = magic[-1]
    assert stream < 4 and reserved == 0
    if kind == 1:
        assert (flags, n, length, offset, len(words)) == (0, 0, 0, 0, 4)
    else:
        assert 1 <= length <= 4096 and offset % 256 == 0 and offset < length
        assert n == min(256, length - offset)
        assert flags == ((offset == 0) | ((offset + n == length) << 1))
        assert len(words) == 4 + (n + 7) // 8
    payload = bytearray()
    for i, (data, keep, first, last) in enumerate(words[3:-1]):
        count = min(8, n - i * 8)
        assert (keep, first, last) == ((1 << count) - 1, 0, 0)
        payload.extend(data.to_bytes(8, "little")[:count])
    assert d == crc32c(header + payload), ("CRC mismatch", hex(d), hex(crc32c(header + payload)))
    return dict(kind=kind, stream=stream, session=session, identity=identity,
                length=length, offset=offset, payload=bytes(payload))


def payload(stream, length, serial, rng):
    return bytes((rng.randrange(256) ^ stream ^ serial) for _ in range(length))
