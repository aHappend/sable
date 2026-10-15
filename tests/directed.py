"""Directed public-pin witnesses for boundaries and simultaneous operations."""
import collections
import itertools
import json

from model import beats, frame
from retain import command
from scenarios import MessageOracle
from sim import Sim, vector


class Bench:
    def __init__(self, out, **config):
        self.sim = Sim(out, **config)
        self.frames = []
        self.status = []
        self.app = []
        self.last = None
        self.mr = self.sr = self.lr = 1
        self.input_beats = []
        self.output_beats = []

    def tick(self, app=None, incoming=None, **ready):
        drive = vector(app, incoming, ready.get("mr", self.mr),
                       ready.get("sr", self.sr), ready.get("lr", self.lr))
        if app is None and "select_stream" in ready:
            drive[5] = ready["select_stream"]
            drive[6] = 1
        obs, emitted = self.sim.step(drive)
        o = obs[0]
        self.last = o
        for node, words, d in emitted:
            assert node == 0
            self.frames.append((self.sim.cycle, words, d))
        if o["sv"] and drive[8]:
            self.status.append((self.sim.cycle, o["ss"], o["sc"]))
        if o["mv"] and drive[7]:
            self.app.append((self.sim.cycle, o.copy()))
        if o["tv"] and drive[9]:
            self.output_beats.append((self.sim.cycle, o["td"], o["tk"], o["tf"], o["tl"]))
        if incoming is not None and o["rr"]:
            self.input_beats.append((self.sim.cycle, *incoming))
        return o

    def idle(self, count, **ready):
        for _ in range(count):
            self.tick(**ready)

    def application(self, data, stream=0):
        for beat in beats(data, True, stream):
            for _ in range(200000):
                if self.tick(app=beat)["ir"]:
                    break
            else:
                raise AssertionError("APPLICATION_ACCEPT_DEADLINE")

    def wire(self, words, **ready):
        for beat in words:
            for _ in range(200000):
                if self.tick(incoming=beat, **ready)["rr"]:
                    break
            else:
                raise AssertionError("FRAME_ACCEPT_DEADLINE")

    def until(self, condition, bound=10000, **ready):
        for _ in range(bound):
            if condition():
                return
            self.tick(**ready)
        raise AssertionError(("DIRECTED_DEADLINE", self.sim.cycle, self.status,
                              [(d["stream"], d["identity"]) for _, _, d in self.frames[-12:]]))

    def result(self, name, **coverage):
        record = dict(name=name, cycles=self.sim.cycle, frames=len(self.frames),
                      statuses=self.status, application_beats=len(self.app),
                      coverage=coverage, outcome="passed")
        (self.sim.out / "coverage.json").write_text(json.dumps(record, indent=2))
        return record


def window(out):
    b = Bench(out, mode=0)
    try:
        messages = [bytes((i + s) % 256 for i in range(4096)) for s in range(4)]
        streams = [beats(data, True, s) for s, data in enumerate(messages)]
        for pos in range(512):
            for s in range(4):
                beat = streams[s][pos]
                assert b.tick(app=beat)["ir"], ("unexpected collection stall", s, pos)
        b.until(lambda: len(b.frames) == 32, 5000)
        b.idle(200)
        ids = collections.defaultdict(set)
        order = []
        for _, _, d in b.frames:
            assert d["payload"] == messages[d["stream"]][d["offset"]:d["offset"] + 256]
            ids[d["stream"]].add(d["identity"])
            order.append(d["stream"])
        assert all(ids[s] == set(range(8)) for s in range(4)), ids
        assert len(b.frames) == 32, ("unexpected retransmission before timeout", len(b.frames))
        assert all(set(order[i:i + 4]) == set(range(4)) for i in range(0, 32, 4)), order
        # ACK seven later positions, but withhold the oldest hole.
        for identity in range(1, 8):
            b.wire(frame(1, 0, b.sim.session, identity))
        b.idle(100)
        assert all(d["identity"] < 8 for _, _, d in b.frames if d["stream"] == 0)
        # An unrelated stream advances into its second window while stream 0 waits.
        for identity in range(8):
            b.wire(frame(1, 1, b.sim.session, identity))
        b.until(lambda: any(d["stream"] == 1 and d["identity"] == 8 for _, _, d in b.frames))
        assert not b.status
        return b.result("frozen_ack_window", per_stream_unacked=[8] * 4,
                        aggregate_unacked=32, oldest_hole_blocks_ninth=True,
                        other_stream_progress=True, round_robin_frames=32)
    finally:
        b.sim.close()


def ack_integrity(out):
    b = Bench(out, mode=0)
    try:
        b.application(b"123456789")
        b.until(lambda: len(b.frames) == 1)
        from model import crc32c
        words = b.frames[0][1]
        prefix = b"".join(d.to_bytes(8, "little") for d, _, _, _ in words[:3])
        # Remove the protected prefix's affine CRC contribution, using public wire bytes.
        payload_crc = words[-1][0] ^ crc32c(prefix + bytes(9)) ^ crc32c(bytes(9))
        assert payload_crc == 0xe3069283, ("RTL_STANDARD_VECTOR", hex(payload_crc))
        valid = frame(1, 0, b.sim.session, 0)
        from scenarios import corrupted
        tested = []
        for byte in (0, 1, 2, 3, 4, 5, 6, 8, 12, 13, 16, 18, 20, 24):
            b.wire(corrupted(valid, byte))
            b.idle(3)
            assert not b.status, ("corrupt ACK advanced TX", byte)
            tested.append(byte)
        b.wire(frame(1, 0, b.sim.session ^ 1, 0))
        b.wire(frame(1, 0, b.sim.session, 1))
        b.wire(frame(1, 1, b.sim.session, 0))
        b.idle(5)
        assert not b.status
        b.wire(valid)
        b.until(lambda: len(b.status) == 1)
        assert b.status[0][1:] == (0, 0)
        b.wire(valid)
        b.idle(20)
        assert len(b.status) == 1
        return b.result("ACK_integrity", single_bit_rejected_bytes=tested,
                        wrong_session=True, future=True, wrong_stream=True, duplicate=True,
                        RTL_standard_vector_crc=hex(payload_crc))
    finally:
        b.sim.close()


def rx_integrity(out):
    b = Bench(out, mode=1)
    try:
        from scenarios import corrupted
        data = b"123456789"
        valid = frame(0, 0, b.sim.session, 0, data)
        tested = []
        for byte in (0, 1, 2, 3, 4, 5, 6, 8, 12, 13, 16, 18, 20, 24, 40):
            b.wire(corrupted(valid, byte))
            b.idle(4)
            assert not b.frames and not b.app, ("bad DATA accepted", byte)
            tested.append(byte)
        # CRC-correct structural errors must also be rejected.
        malformed = []
        import struct
        from model import crc32c
        for byte, mask in ((5, 4), (4, 4), (20, 1), (18, 1)):
            raw = bytearray(b"".join(d.to_bytes(8, "little") for d, _, _, _ in valid[:3]))
            raw[byte] ^= mask
            words = [(int.from_bytes(raw[i:i + 8], "little"), 255, int(i == 0), 0)
                     for i in range(0, 24, 8)]
            words += valid[3:-1]
            words += [(crc32c(raw + data), 15, 0, 1)]
            malformed.append(words)
        wrong_keep = list(valid)
        d, _, f, l = wrong_keep[3]
        wrong_keep[3] = (d, 0x7f, f, l)
        malformed.append(wrong_keep)
        nested = list(valid)
        d, k, _, l = nested[1]
        nested[1] = (d, k, 1, l)
        malformed.append(nested)
        malformed.append(valid[:-1] + [(0, 255, 0, 0), valid[-1]])
        malformed.append([valid[0], (0, 15, 0, 1)])
        for words in malformed:
            b.wire(words)
            b.idle(4)
            assert not b.frames and not b.app, ("malformed accepted", words)
        b.wire(frame(0, 0, b.sim.session ^ 1, 0, data))
        b.idle(5)
        assert not b.frames and not b.app
        b.wire(valid)
        b.until(lambda: len(b.app) == 2 and len(b.frames) == 1)
        oracle = MessageOracle({s: [data] if s == 0 else [] for s in range(4)})
        for _, o in b.app:
            oracle.observe(o, 1)
        assert oracle.done()
        assert b.frames[0][2]["identity"] == 0
        return b.result("DATA_integrity", single_bit_rejected_bytes=tested,
                        crc_correct_malformed=len(malformed), wrong_session=True,
                        standard_vector_payload=True)
    finally:
        b.sim.close()


def reverse_and_fifo(out):
    results = []
    b = Bench(out / "reverse", mode=1)
    try:
        data = bytes(i % 251 for i in range(4096))
        for part in range(7, 0, -1):
            b.wire(frame(0, 0, b.sim.session, part, data, part * 256))
        b.idle(80)
        assert not b.app
        assert {d["identity"] for _, _, d in b.frames} == set(range(1, 8))
        b.wire(frame(0, 0, b.sim.session, 8, data, 2048))
        b.idle(80)
        assert not b.app and all(d["identity"] != 8 for _, _, d in b.frames)
        b.wire(frame(0, 0, b.sim.session, 0, data))
        b.until(lambda: {d["identity"] for _, _, d in b.frames} == set(range(8)))
        # All eight ACKs prove durable reverse-window acceptance, not array declarations.
        for part in range(8, 16):
            b.wire(frame(0, 0, b.sim.session, part, data, part * 256))
        b.until(lambda: len(b.app) == 512)
        oracle = MessageOracle({s: [data] if s == 0 else [] for s in range(4)})
        for _, o in b.app:
            oracle.observe(o, 1)
        assert oracle.done()
        b.wire(frame(0, 0, b.sim.session, 0, data))
        b.idle(100)
        assert len(b.app) == 512
        results.append(b.result("reverse_eight_slots", retained_reverse_slots=8,
                                future_ninth_rejected=True, compared_bytes=oracle.compared,
                                missing_oldest_prevents_delivery=True, duplicate_old=True))
    finally:
        b.sim.close()
    b = Bench(out / "fifo", mode=1)
    try:
        b.mr = b.lr = 0
        data = b"x"
        for _ in range(41):
            b.wire(frame(0, 0, b.sim.session, 0, data))
        assert not b.app and not b.frames
        b.mr = b.lr = 1
        b.idle(400)
        assert len(b.frames) == 33, ("ACK FIFO capacity/drop", len(b.frames))
        assert len(b.app) == 1 and b.app[0][1]["md"] == ord("x")
        b.wire(frame(0, 0, b.sim.session, 0, data))
        b.until(lambda: len(b.frames) == 34)
        assert len(b.app) == 1
        results.append(b.result("ACK_FIFO_full_recovery", blocked_duplicate_requests=41,
                                retained_ACKs=33, regenerated_after_drop=True))
    finally:
        b.sim.close()
    return results


def timers(out):
    results = []
    b = Bench(out / "coincident", mode=0, timeout=1, retries=0)
    try:
        b.application(b"x")
        b.until(lambda: len(b.output_beats) == 2)
        b.wire(frame(1, 0, b.sim.session, 0))
        ack_tail = b.input_beats[-1][0]
        data_tail = [c for c, _, _, _, last in b.output_beats if last][0]
        assert ack_tail == data_tail + 1, ("ACK/timeout coincidence not achieved", ack_tail, data_tail)
        b.until(lambda: len(b.status) == 1)
        assert b.status[0][2] == 0 and b.last["fail"] == 0
        results.append(b.result("ACK_timeout_same_edge", data_crc_cycle=data_tail,
                                ack_crc_cycle=ack_tail, timeout_cycles=1, ACK_wins=True))
    finally:
        b.sim.close()
    b = Bench(out / "in_retransmit", mode=0, timeout=8, retries=4)
    try:
        b.application(bytes(range(256)))
        b.until(lambda: len([x for x in b.output_beats if x[3]]) == 2)
        b.lr = 0
        b.idle(40)
        assert not b.status
        b.wire(frame(1, 0, b.sim.session, 0))
        ack_cycle = b.input_beats[-1][0]
        b.until(lambda: len(b.status) == 1)
        assert b.status[0][2] == 0 and b.tick()["ir"] == 0
        b.lr = 1
        b.until(lambda: len(b.frames) == 2 and len(b.status) == 1)
        assert b.frames[0][0] < ack_cycle < b.frames[1][0]
        assert b.status[0][2] == 0
        b.idle(30)
        assert len(b.frames) == 2 and len(b.status) == 1
        results.append(b.result("ACK_during_retransmission", ack_cycle=ack_cycle,
                                retransmit_crc_cycle=b.frames[1][0], unique_status=True))
    finally:
        b.sim.close()
    b = Bench(out / "public_crc_stall", mode=2, timeout=8, retries=0)
    try:
        b.application(b"x")
        b.until(lambda: len(b.output_beats) == 4)
        b.lr = 0
        b.idle(40)
        assert not b.status and b.last["fail"] == 0
        assert b.last["tv"] and b.last["tl"] and b.last["tk"] == 15
        b.lr = 1
        b.until(lambda: len(b.frames) == 1)
        tail = b.frames[0][0]
        b.until(lambda: len(b.status) == 1)
        assert b.status[0][2] == 1 and b.status[0][0] >= tail + 8
        results.append(b.result("timer_starts_public_CRC", stalled_crc_cycles=40,
                                timeout_cycles=8, crc_handshake_cycle=tail))
    finally:
        b.sim.close()
    b = Bench(out / "exhaust", mode=0, timeout=8, retries=4)
    try:
        b.application(b"failure")
        b.until(lambda: len(b.status) == 1)
        assert len(b.frames) == 5 and b.status[0][1:] == (0, 1)
        assert b.last["fail"] == 1 and b.tick()["ir"] == 0
        b.application(b"other", 1)
        b.until(lambda: any(d["stream"] == 1 for _, _, d in b.frames))
        b.wire(frame(1, 1, b.sim.session, 0))
        b.until(lambda: len(b.status) == 2)
        assert b.status[1][1:] == (1, 0)
        results.append(b.result("retry_exhaustion", transmissions=5, retries=4,
                                failure_closes_only_one_stream=True))
    finally:
        b.sim.close()
    return results


def mailbox(out):
    b = Bench(out, mode=0)
    try:
        b.sr = 0
        for s in range(4):
            b.application(bytes([s]), s)
        b.until(lambda: len(b.frames) == 4)
        for s in range(4):
            b.wire(frame(1, s, b.sim.session, 0))
        b.idle(30)
        assert not b.status and b.last["sv"]
        for s in range(4):
            assert b.tick(select_stream=s)["ir"] == 0
        b.sr = 1
        b.until(lambda: len(b.status) == 4)
        assert {s for _, s, c in b.status if c == 0} == set(range(4))
        return b.result("completion_mailboxes_full", retained_statuses=4, overwrite_prevented=True)
    finally:
        b.sim.close()


def receive_fairness(out):
    b = Bench(out, mode=1)
    try:
        b.mr = 0
        data = bytes(i % 251 for i in range(4096))
        for identity in range(16):
            b.wire(frame(0, 0, b.sim.session, identity, data, identity * 256))
        b.idle(80)
        assert b.last["mv"] and b.last["ms"] == 0 and not b.app
        # A blocked complete stream must not prevent another stream's acceptance/ACK.
        b.wire(frame(0, 1, b.sim.session, 0, b"z"))
        b.until(lambda: any(d["stream"] == 1 for _, _, d in b.frames))
        assert not b.app
        # New message for the still-owned stream is drained, not positively ACKed.
        old_count = len(b.frames)
        b.wire(frame(0, 0, b.sim.session, 16, b"next"))
        b.idle(30)
        assert len(b.frames) == old_count
        b.mr = 1
        b.until(lambda: len(b.app) >= 5)
        first = b.app[:5]
        assert any(o["ms"] == 1 for _, o in first), ("RX_APP_STARVATION", first)
        b.until(lambda: len(b.app) == 513)
        oracle = MessageOracle({0: [data], 1: [b"z"], 2: [], 3: []})
        for _, o in b.app:
            oracle.observe(o, 1)
        assert oracle.done()
        # Once the previous tail retires, the exact same next-message DATA is legal.
        b.wire(frame(0, 0, b.sim.session, 16, b"next"))
        b.until(lambda: len(b.app) == 514)
        assert b.app[-1][1]["md"] == int.from_bytes(b"next", "little")
        return b.result("receive_fairness_and_ownership", blocked_stream_bytes=4096,
                        other_stream_ACK_while_blocked=True, other_stream_within_beats=5,
                        next_message_rejected_until_tail=True, compared_bytes=oracle.compared + 4)
    finally:
        b.sim.close()


def endpoint_ack_independence(out):
    b = Bench(out, mode=2)
    try:
        b.mr = 0
        tx_data = bytes(i % 239 for i in range(4096))
        rx_data = bytes(i % 251 for i in range(4096))
        b.application(tx_data)
        data_frames = lambda: [d for _, _, d in b.frames if d["kind"] == 0]
        ack_frames = lambda: [d for _, _, d in b.frames if d["kind"] == 1]
        b.until(lambda: len(data_frames()) == 8)
        assert {d["identity"] for d in data_frames()} == set(range(8))
        for identity in range(16):
            b.wire(frame(0, 0, b.sim.session, identity, rx_data, identity * 256))
        b.until(lambda: b.last["mv"] and len(ack_frames()) >= 16)
        assert not b.app and {d["identity"] for d in data_frames()} == set(range(8))
        assert {d["identity"] for d in ack_frames()} == set(range(16))
        b.wire(frame(0, 0, b.sim.session, 16, b"next"))
        b.idle(20)
        assert all(d["identity"] != 16 for d in ack_frames())
        # This ACK follows a drained resource-rejected DATA frame.
        b.wire(frame(1, 0, b.sim.session, 0))
        b.until(lambda: any(d["identity"] == 8 for d in data_frames()))
        for d in data_frames():
            assert d["payload"] == tx_data[d["offset"]:d["offset"] + 256]
        assert not b.status
        return b.result("endpoint_ACK_independence", full_TX_window=8,
                        ACKs_sent_while_TX_full=16, full_RX_message_bytes=4096,
                        rejected_DATA_did_not_block_following_ACK=True,
                        TX_window_advanced_after_ACK=True)
    finally:
        b.sim.close()


def wrap(out, generation, count, exhausted_message_length=1):
    b = Bench(out, mode=0, generation=generation)
    old = None
    try:
        for identity in range(count):
            b.application(bytes([identity % 256]))
            b.until(lambda: len(b.frames) == identity + 1)
            d = b.frames[-1][2]
            assert (d["identity"], d["payload"]) == (identity, bytes([identity % 256]))
            if identity == 0:
                old = frame(1, 0, b.sim.session, 0)
            if identity == 256:
                before = len(b.status)
                b.wire(old)
                b.idle(8)
                assert len(b.status) == before, "old ACK aliased across sequence wrap"
            b.wire(frame(1, 0, b.sim.session, identity))
            b.until(lambda: len(b.status) == identity + 1)
            assert b.status[-1][2] == 0
        if generation == 1:
            offered = beats(bytes(exhausted_message_length), True, 0)[0]
            assert not b.tick(app=offered)["ir"]
            assert b.tick(app=offered)["exhaust"] == 1
            assert not b.tick(app=offered)["ir"]
            assert len(b.frames) == count
        return b.result("identity_lifetime", generation_bits=generation,
                        allocated_packets=count, sequence_wrap=True, old_ACK_rejected=True,
                        full_identity_exhaustion=generation == 1,
                        rejected_message_bytes=exhausted_message_length if generation == 1 else None)
    finally:
        b.sim.close()


def rx_wrap(out):
    b = Bench(out, mode=1)
    try:
        for identity in range(260):
            before = len(b.app)
            b.wire(frame(0, 0, b.sim.session, identity, bytes([identity % 256])))
            b.until(lambda: len(b.app) == before + 1)
            assert b.app[-1][1]["md"] == identity % 256
            if identity == 256:
                b.wire(frame(0, 0, b.sim.session, 0, b"\x00"))
                b.idle(20)
                assert len(b.app) == before + 1
        return b.result("RX_sequence_wrap", delivered_messages=260, delayed_old_DATA_suppressed=True)
    finally:
        b.sim.close()


def resets(out):
    results = []
    # Legacy cancellation cases; precise wire-phase witnesses are separate below.
    for mode, offsets in ((0, (0, 2, 5, 12, 45)), (1, (0, 2, 5, 10, 45)), (2, (0, 3, 8, 20, 70))):
        b = Bench(out / f"mode{mode}", mode=mode)
        try:
            for index, offset in enumerate(offsets):
                old_session = b.sim.session
                data = bytes(range(17))
                if mode != 1:
                    first = beats(data, True)[0]
                    b.tick(app=first, lr=0, sr=0)
                    if index:
                        for beat in beats(data, True)[1:]:
                            b.tick(app=beat, lr=0, sr=0)
                if mode != 0:
                    raw = frame(0, 0, old_session, 0, data)
                    count = len(raw) if index >= len(offsets) - 2 else min(len(raw), index + 1)
                    b.wire(raw[:count], mr=0, lr=0)
                b.idle(offset, mr=0, sr=0, lr=int(index == 4))
                if index == 4 and mode != 1:
                    b.wire(frame(1, 0, old_session, 0), mr=0, sr=0)
                    b.idle(6, mr=0, sr=0)
                    assert b.last["sv"], ("completion reset precondition not reached", mode)
                b.sim.session += 1
                b.sim.reset()
                b.frames.clear()
                b.app.clear()
                b.status.clear()
                if mode != 1:
                    b.wire(frame(1, 0, old_session, 0))
                if mode != 0:
                    b.wire(frame(0, 0, old_session, 0, data))
                    # Continuation of a reset-interrupted old frame is not a new frame.
                    b.wire([(0, 255, 0, 0), (0, 15, 0, 1)])
                b.idle(40)
                assert not b.frames and not b.app and not b.status, ("stale reset traffic", mode, index)
                if mode == 1:
                    b.wire(frame(0, 0, b.sim.session, 0, b"new"))
                    b.until(lambda: len(b.app) == 1)
                    assert b.app[0][1]["md"] == int.from_bytes(b"new", "little")
                else:
                    b.application(b"new")
                    b.until(lambda: len(b.frames) == 1)
                    b.wire(frame(1, 0, b.sim.session, 0))
                    b.until(lambda: len(b.status) == 1)
                    assert b.status[0][2] == 0
                b.sim.session += 1
                b.sim.reset()
                b.frames.clear()
                b.app.clear()
                b.status.clear()
            results.append(b.result("reset_cancellation", mode=mode, reset_offsets=list(offsets),
                                    stale_DATA_ACK_rejected=True, recovery_transactions=len(offsets)))
        finally:
            b.sim.close()
    return results


RESET_PHASE_CASES = ("tx-payload", "tx-crc-stall", "rx-payload",
                     "tx-partial-ack", "endpoint-input-lock", "endpoint-output-lock")


def reset_phase_witness(out):
    results = []
    for case in RESET_PHASE_CASES:
        mode = 1 if case == "rx-payload" else (2 if case.startswith("endpoint") else 0)
        b = Bench(out / case, mode=mode)
        witness = dict(case=case, mode=mode, outcome="not_completed", channels=[],
                       reset_cycles=[], reset_public_zero_checks=0)
        try:
            old_session = b.sim.session
            old_data = bytes(range(17))
            old_words = frame(0, 0, old_session, 0, old_data)
            old_ack = frame(1, 0, old_session, 0)
            witness.update(old_session=old_session, new_session=old_session + 1)
            b.mr = b.sr = 0
            crc_stalls = []
            if case in ("tx-payload", "tx-crc-stall", "endpoint-output-lock"):
                b.application(old_data)
                count = len(old_words) - 1 if case == "tx-crc-stall" else 4
                b.until(lambda: len(b.output_beats) == count, bound=1000)
                b.lr = 0
                assert [beat[1:] for beat in b.output_beats] == old_words[:count]
                assert b.output_beats[0][3] == 1 and not any(beat[-1] for beat in b.output_beats)
                if case == "tx-crc-stall":
                    for _ in range(1000):
                        o = b.tick()
                        if o["tv"] and o["tl"]:
                            break
                    else:
                        raise AssertionError(("RESET_PHASE_NOT_REACHED", case, "CRC stall"))
                    for _ in range(3):
                        assert (b.last["tv"], b.lr) == (1, 0)
                        assert tuple(b.last[k] for k in ("td", "tk", "tf", "tl")) == old_words[-1]
                        crc_stalls.append(b.sim.cycle)
                        if len(crc_stalls) < 3:
                            b.tick()
                interrupted = old_words
                accepted = b.output_beats.copy()
                direction = "TX.DATA" if mode == 0 else "endpoint.link_tx.DATA"
            elif case == "tx-partial-ack":
                b.application(old_data)
                b.until(lambda: len(b.frames) == 1, bound=1000)
                assert b.frames[0][1] == old_words
                b.wire(old_ack[:2])
                interrupted = old_ack
                accepted = b.input_beats.copy()
                direction = "TX.ACK"
            else:
                b.wire(old_words[:4])
                interrupted = old_words
                accepted = b.input_beats.copy()
                direction = "RX.DATA" if mode == 1 else "endpoint.link_rx.DATA"
            count = len(accepted)
            assert [beat[1:] for beat in accepted] == interrupted[:count]
            assert 0 < count < len(interrupted), ("RESET_PHASE_NOT_PARTIAL", case, accepted)
            assert accepted[0][3] == 1 and not any(beat[-1] for beat in accepted)
            if case == "tx-partial-ack":
                assert count == 2, ("RESET_PHASE_NOT_REACHED", case, "partial ACK header")
            else:
                assert count >= 4, ("RESET_PHASE_NOT_REACHED", case, "payload handshake")
            suffix = interrupted[count:]
            witness["channels"].append(dict(
                direction=direction, session=old_session, identity=0,
                header_handshake_cycles=[beat[0] for beat in accepted[:3]],
                payload_handshake_cycles=[beat[0] for beat in accepted[3:]],
                crc_handshake_cycle=None, crc_stall_observation_cycles=crc_stalls,
                accepted_beats=accepted, remaining_beats=suffix))
            if case == "tx-partial-ack":
                witness["completed_DATA_before_partial_ACK"] = b.output_beats.copy()
            witness["phase_precondition_observed"] = True
            (b.sim.out / "witness.json").write_text(json.dumps(witness, indent=2))

            b.sim.session = old_session + 1
            for _ in range(2):
                obs, emitted = b.sim.step(rst=1)
                assert not emitted and all(not any(o.values()) for o in obs)
                witness["reset_cycles"].append(b.sim.cycle)
                witness["reset_public_zero_checks"] += len(obs)
            b.frames.clear()
            b.app.clear()
            b.status.clear()
            b.input_beats.clear()
            b.output_beats.clear()
            b.mr = b.sr = b.lr = 1
            b.tick()

            new_tx = b"new TX epoch!"
            new_rx = b"new RX epoch!"
            if mode != 1:
                b.application(new_tx)
                b.until(lambda: len(b.frames) == 1, bound=1000)
                assert b.frames[0][1] == frame(0, 0, b.sim.session, 0, new_tx)
                assert not b.status, ("unexpected completion before stale ACK challenge", case)
                witness["new_identity_zero_pending_cycle"] = b.sim.cycle
            # Replay the exact unaccepted suffix, not a fabricated generic fragment.
            # For interrupted DATA output, the link loops its residual beats to ingress.
            b.wire(suffix)
            b.wire(old_words)
            b.wire(old_ack)
            b.idle(40)
            assert not b.app and not b.status, ("RESET_STALE_DELIVERY_OR_STATUS", case)
            assert len(b.frames) == int(mode != 1), ("RESET_STALE_POSITIVE_ACK_OR_FRAME", case)
            witness["stale_challenge"] = dict(
                suffix=suffix, complete_old_DATA=old_words, complete_old_ACK=old_ack,
                accepted_beats=b.input_beats.copy(), checked_through_cycle=b.sim.cycle,
                application_beats=0, statuses=0, positive_ACKs=0)
            if mode != 0:
                b.wire(frame(0, 0, b.sim.session, 0, new_rx))
            if mode != 1:
                b.wire(frame(1, 0, b.sim.session, 0))
            b.until(lambda: len(b.status) == int(mode != 1)
                    and len(b.app) == (len(beats(new_rx)) if mode != 0 else 0)
                    and len(b.frames) == (2 if mode == 2 else 1), bound=1000)
            b.idle(80)
            oracle = MessageOracle({s: [new_rx] if mode != 0 and s == 0 else []
                                    for s in range(4)})
            for _, o in b.app:
                oracle.observe(o, 1)
            assert oracle.done(), ("RESET_RECOVERY_NOT_DELIVERED", case)
            assert [(s, code) for _, s, code in b.status] == ([(0, 0)] if mode != 1 else [])
            expected_frames = []
            if mode != 1:
                expected_frames.append(frame(0, 0, b.sim.session, 0, new_tx))
            if mode != 0:
                expected_frames.append(frame(1, 0, b.sim.session, 0))
            assert [words for _, words, _ in b.frames] == expected_frames, (
                "RESET_RECOVERY_FRAME_MISMATCH", case, b.frames)
            assert len(b.app) == (len(beats(new_rx)) if mode != 0 else 0)
            assert b.last["fail"] == 0 and b.last["exhaust"] == 0
            witness.update(outcome="passed", recovery_checked_through_cycle=b.sim.cycle,
                           recovery_statuses=b.status, recovery_compared_RX_bytes=oracle.compared,
                           recovery_compared_TX_bytes=len(new_tx) if mode != 1 else 0,
                           recovery_frames=[dict(cycle=c, words=w) for c, w, _ in b.frames])
            results.append(b.result("reset-phase-witness", **witness))
        except Exception as error:
            witness.update(outcome="failed", failure=repr(error), failure_cycle=b.sim.cycle)
            raise
        finally:
            (b.sim.out / "witness.json").write_text(json.dumps(witness, indent=2))
            b.sim.close()
    return results


def ambiguity(out):
    sim = Sim(out, mode=2, timeout=128, retries=0)
    from scenarios import Wire
    wire = Wire()
    source = collections.deque(beats(b"delivered", True))
    oracle = MessageOracle({s: [b"delivered"] if s == 0 else [] for s in range(4)})
    status = []
    dropped = 0
    try:
        for _ in range(1000):
            app = source[0] if source else None
            incoming = wire.offer(sim.cycle)
            obs, emitted = sim.step(vector(app), vector(incoming=incoming))
            if app and obs[0]["ir"]:
                source.popleft()
            if incoming and obs[1]["rr"]:
                wire.accept()
            oracle.observe(obs[1], 1)
            for node, words, d in emitted:
                if node == 0:
                    assert d["kind"] == 0 and d["payload"] == b"delivered"
                    wire.put(words)
                else:
                    assert d["kind"] == 1
                    dropped += 1
            if obs[0]["sv"]:
                status.append(obs[0]["sc"])
            if status and oracle.done():
                break
        assert status == [1] and oracle.done() and dropped == 1
        result = dict(name="unacknowledged_despite_actual_delivery", outcome="passed",
                      status=status, receiver_compared_bytes=oracle.compared,
                      ACKs_dropped=dropped, cycles=sim.cycle)
        (sim.out / "coverage.json").write_text(json.dumps(result, indent=2))
        return result
    finally:
        sim.close()


def parameters(out):
    out.mkdir()
    reset_vectors = out / "reset.txt"
    reset_vectors.write_text("1 1234 0 0\n1 1234 0 0\n")
    legal = []
    for generation, timeout, retries in itertools.product((1, 24), (1, 4096), (0, 4)):
        label = f"g{generation}-t{timeout}-r{retries}"
        binary = out / (label + ".vvp")
        command(out, label + "-compile", ["iverilog", "-g2012", "-Wall", "-s", "bridge",
                f"-Pbridge.GENERATION_BITS={generation}", f"-Pbridge.TIMEOUT_CYCLES={timeout}",
                f"-Pbridge.MAX_RETRIES={retries}", "-o", binary, "tests/bridge.sv",
                "rtl/sable_tx.sv", "rtl/sable_rx.sv", "rtl/sable_endpoint.sv"])
        command(out, label + "-reset", ["vvp", binary, "+INPUT=" + str(reset_vectors)], timeout=5)
        legal.append([generation, timeout, retries])
    rejected = []
    for param, value in (("GENERATION_BITS", 0), ("GENERATION_BITS", 25),
                         ("TIMEOUT_CYCLES", 0), ("TIMEOUT_CYCLES", 65536),
                         ("MAX_RETRIES", -1), ("MAX_RETRIES", 16)):
        label = f"illegal-{param}-{value}"
        binary = out / (label + ".vvp")
        command(out, label + "-compile", ["iverilog", "-g2012", "-Wall", "-s", "bridge",
                f"-Pbridge.{param}={value}", "-o", binary, "tests/bridge.sv",
                "rtl/sable_tx.sv", "rtl/sable_rx.sv", "rtl/sable_endpoint.sv"])
        argv = ["vvp", str(binary), "+INPUT=" + str(reset_vectors)]
        execution = command(out, label, argv, timeout=5, allow_failure=True)
        text = (out / (label + ".stdout")).read_text() + (out / (label + ".stderr")).read_text()
        assert execution["exit_code"] != 0 and "PARAMETER ERROR: " + param in text, (
            "illegal parameter not explicitly rejected", param, value, execution["exit_code"], text)
        rejected.append([param, value])
    result = dict(name="parameter_matrix", outcome="passed", elaborated_and_reset=legal, explicitly_rejected=rejected)
    (out / "coverage.json").write_text(json.dumps(result, indent=2))
    return result


def directed(out, max_cycles):
    results = [window(out / "window"), ack_integrity(out / "ack-integrity"),
               rx_integrity(out / "rx-integrity"), mailbox(out / "mailbox"),
               receive_fairness(out / "receive-fairness"),
               endpoint_ack_independence(out / "endpoint-ack-independence")]
    results.extend(reverse_and_fifo(out / "rx-resources"))
    results.extend(timers(out / "timers"))
    results.append(ambiguity(out / "ambiguity"))
    results.extend(resets(out / "resets"))
    results.extend(reset_phase_witness(out / "reset-phase-witness"))
    results.append(wrap(out / "wrap-default", 24, 260))
    results.append(wrap(out / "identity-exhaustion", 1, 512))
    results.append(wrap(out / "atomic-identity-exhaustion", 1, 504, 4096))
    results.append(rx_wrap(out / "rx-wrap"))
    results.append(parameters(out / "parameters"))
    return results
