"""Requirement-driven traffic; expected results are bytes and wire transactions."""
import collections
import json
import random

from model import LENGTHS, beats, frame, payload
from sim import Sim, vector


class Wire:
    def __init__(self):
        self.pending = []
        self.active = None
        self.pos = 0
        self.serial = 0

    def put(self, words, due=0):
        self.serial += 1
        self.pending.append((due, self.serial, list(words)))

    def offer(self, cycle):
        if self.active is None:
            eligible = [x for x in self.pending if x[0] <= cycle]
            if eligible:
                item = min(eligible)
                self.pending.remove(item)
                self.active = item[2]
                self.pos = 0
        return self.active[self.pos] if self.active is not None else None

    def accept(self):
        self.pos += 1
        if self.pos == len(self.active):
            self.active = None

    def empty(self):
        return self.active is None and not self.pending


class MessageOracle:
    def __init__(self, messages):
        self.expected = {s: collections.deque(items) for s, items in messages.items()}
        self.offset = collections.Counter()
        self.completed = collections.Counter()
        self.compared = 0

    def observe(self, o, ready):
        if not (o["mv"] and ready):
            return
        s = o["ms"]
        assert self.expected[s], ("UNEXPECTED_MESSAGE", s, o)
        data = self.expected[s][0]
        pos = self.offset[s]
        count = min(8, len(data) - pos)
        expected = (int.from_bytes(data[pos:pos + count], "little"), (1 << count) - 1,
                    int(pos == 0), int(pos + count == len(data)), len(data))
        actual = tuple(o[k] for k in ("md", "mk", "mf", "ml", "mn"))
        assert actual == expected, ("BYTE_MISMATCH", s, pos, "actual", actual, "expected", expected)
        self.compared += count
        if o["ml"]:
            self.expected[s].popleft()
            self.completed[s] += 1
            self.offset[s] = 0
        else:
            self.offset[s] += count

    def done(self):
        return not any(self.expected.values())


def traffic(seed, smoke=False):
    rng = random.Random(seed)
    result = {}
    for s in range(4):
        lengths = (1, 4096, 9, 257) if smoke else tuple(dict.fromkeys((1, 4096, *LENGTHS[s::4])))
        result[s] = [payload(s, length, n, rng) for n, length in enumerate(lengths)]
    assert smoke or set(LENGTHS) <= {len(data) for items in result.values() for data in items}
    assert all({1, 4096} <= {len(data) for data in items} for items in result.values())
    return result


def corrupted(words, byte, bit=0):
    result = list(words)
    index, lane = divmod(byte, 8)
    d, k, f, l = result[index]
    result[index] = (d ^ (1 << (lane * 8 + bit)), k, f, l)
    return result


def fault_packet(wire, words, decoded, cycle, attempts, counts, rng, decisions, faults=True):
    key = (decoded["kind"], decoded["stream"], decoded["identity"])
    attempt = attempts[key]
    attempts[key] += 1
    kind = "ACK" if decoded["kind"] else "DATA"
    # At most two unavailable events per DATA identity across DATA + ACK.
    identity = decoded["identity"]
    action = "deliver"
    delay = None
    damage_byte = None
    unavailable = faults and identity < 16
    if unavailable and not decoded["kind"] and attempt == 0 and identity % 5 == 0:
        counts[kind + "_drop"] += 1
        action = "drop"
    elif unavailable and decoded["kind"] and attempt == 0 and identity % 5 == 1:
        counts[kind + "_drop"] += 1
        action = "drop"
    elif unavailable and attempt == 0 and identity % 5 in (2, 3):
        field = (identity // 5 + decoded["stream"]) % 3
        if field == 0:
            byte = (4, 8, 12, 16, 18, 20)[rng.randrange(6)]
            label = "header"
        elif field == 1 and not decoded["kind"]:
            byte = 24
            label = "payload"
        else:
            byte = (len(words) - 1) * 8
            label = "crc"
        wire.put(corrupted(words, byte), cycle + rng.randrange(1, 65))
        damage_byte = byte
        counts[kind + "_corrupt_" + label] += 1
        action = "corrupt_" + label
    else:
        delay = rng.randrange(1, 65) if faults else 1
        wire.put(words, cycle + delay)
        counts[kind + "_delay"] += 1
        if faults and attempt == 0:
            # A second copy may overtake the delayed first copy.
            wire.put(words, cycle + 1)
            counts[kind + "_duplicate"] += 1
            counts[kind + "_reorder_scheduled"] += int(delay > 1)
    decisions.append(dict(cycle=cycle, kind=kind, stream=decoded["stream"],
                          identity=identity, attempt=attempt, action=action,
                          delay_cycles=delay, damaged_byte=damage_byte))


def run_transport(out, seed, mode, max_cycles=200000, smoke=False, mutant=None):
    rng = random.Random(seed)
    messages = traffic(seed, smoke)
    sim = Sim(out, mode=mode, mutant=mutant, seed=seed)
    wires = [Wire(), Wire()]
    counts = collections.Counter()
    attempts = [collections.Counter(), collections.Counter()]
    decisions = []
    oracles = [MessageOracle(messages), MessageOracle(messages)]
    statuses = [collections.Counter(), collections.Counter()]
    send_index = [collections.Counter(), collections.Counter()]
    send_offset = [collections.Counter(), collections.Counter()]
    allocated = [collections.Counter(), collections.Counter()]
    obligations = [{}, {}]
    identities = [{}, {}]
    current = [None, None]
    round_robin = [0, 0]
    outstanding = [set(), set()]
    oldest = [collections.Counter(), collections.Counter()]
    acked = [collections.defaultdict(set), collections.defaultdict(set)]
    last_sequence = {}
    observed_reorder = collections.Counter()
    received_order = {}
    nodes = 2 if mode == 2 else 1
    deadlines = {}
    incoming_frames = [[], []]
    tx_seen = [collections.defaultdict(set), collections.defaultdict(set)]
    highest_occupancy = [collections.Counter(), collections.Counter()]
    rx_expected = set()
    rx_acknowledged = set()
    received_packets = [collections.defaultdict(dict), collections.defaultdict(dict)]
    receive_base = [collections.Counter(), collections.Counter()]
    packet_arrival = [{}, {}]

    def rx_enqueue(words, identity, due=0):
        from model import decode
        d = decode(words)
        rx_expected.add((d["stream"], identity))
        if not smoke and identity < 16:
            action = identity % 5
            if action == 0:
                counts["DATA_drop"] += 1
                decisions.append(dict(kind="DATA", stream=d["stream"], identity=identity,
                                      action="drop_initial_model_TX_attempt", cycle=sim.cycle))
                due += 32
            elif action in (2, 3):
                choice = (identity // 5 + d["stream"]) % 3
                byte, label = ((4, "header") if choice == 0 else
                               (24, "payload") if choice == 1 else
                               ((len(words) - 1) * 8, "crc"))
                wires[0].put(corrupted(words, byte), due)
                counts["DATA_corrupt_" + label] += 1
                due += 32
        wires[0].put(words, due)
        decisions.append(dict(kind="DATA", stream=d["stream"], identity=identity,
                              action="model_TX_send_or_repair", scheduled_cycle=due,
                              queued_cycle=sim.cycle))
        counts["DATA_delay"] += 1
        if identity % 4 == 0 and not smoke:
            wires[0].put(words, due + rng.randrange(1, 65))
            counts["DATA_duplicate"] += 1

    def choose(node):
        if current[node] is not None:
            return current[node]
        for delta in range(4):
            s = (round_robin[node] + delta) % 4
            idx = send_index[node][s]
            if s in obligations[node] and obligations[node][s]["accepted"] and not obligations[node][s]["done"]:
                continue
            if idx < len(messages[s]) and (send_offset[node][s] > 0 or
                                          s not in obligations[node] or obligations[node][s]["done"]):
                data = messages[s][idx]
                pos = send_offset[node][s]
                if pos == 0:
                    base = allocated[node][s]
                    allocated[node][s] += (len(data) + 255) // 256
                    obligations[node][s] = dict(data=data, base=base, accepted=False, done=False)
                    for offset in range(0, len(data), 256):
                        identities[node][s, base + offset // 256] = (data, offset)
                current[node] = (s, beats(data, application=True, stream=s)[pos // 8])
                round_robin[node] = (s + 1) % 4
                return current[node]
        return None

    try:
        if mode == 1:
            for s in range(4):
                # Model TX queues one whole message per stream; next is added on delivery.
                data = messages[s][0]
                ids = list(range((len(data) + 255) // 256))
                for identity in reversed(ids[:8]):
                    rx_enqueue(frame(0, s, sim.session, identity, data, identity * 256), identity)
                # Later-window packets follow only after the older window has had time to copy.
                for identity in ids[8:]:
                    rx_enqueue(frame(0, s, sim.session, identity, data, identity * 256), identity, 4000)
            rx_enqueued = collections.Counter({s: 1 for s in range(4)})
            rx_base = collections.Counter({s: (len(messages[s][0]) + 255) // 256 for s in range(4)})

        limit = max_cycles if not smoke else min(max_cycles, 50000)
        for tick in range(limit):
            cycle = sim.cycle
            drives = []
            offered = []
            for node in range(2):
                allow_source = current[node] is not None or cycle % 4 != seed % 4
                chosen = choose(node) if node < nodes and mode != 1 and allow_source else None
                # Gaps occur between accepted beats, never while a beat is stalled.
                app = chosen[1] if chosen is not None else None
                incoming = wires[node].offer(cycle)
                mr = int(cycle >= 512 and cycle % 2 == 0)
                sr = int(cycle % 2 == 0)
                lr = int(cycle % 2 == 0)
                drives.append(vector(app, incoming, mr, sr, lr))
                offered.append(chosen)
            observations, emitted = sim.step(*drives)
            for node in range(2):
                o, drive = observations[node], drives[node]
                if drive[10] and o["rr"]:
                    word = tuple(drive[11:])
                    if word[2]:
                        assert not incoming_frames[node], ("model link nested first", word)
                    incoming_frames[node].append(word)
                    if word[-1]:
                        from model import decode
                        try:
                            incoming_decoded = decode(incoming_frames[node])
                        except AssertionError:
                            counts["actual_invalid_input_frames"] += 1
                        else:
                            if incoming_decoded["kind"] == 1:
                                acked[node][incoming_decoded["stream"]].add(incoming_decoded["identity"])
                            else:
                                s = incoming_decoded["stream"]
                                part = incoming_decoded["offset"] // 256
                                base = incoming_decoded["identity"] - part
                                key = s, base, incoming_decoded["length"]
                                received_packets[node][key].setdefault(incoming_decoded["offset"], sim.cycle)
                                packet_arrival[node].setdefault((s, incoming_decoded["identity"]), sim.cycle)
                            counts["actual_valid_input_frames"] += 1
                        incoming_frames[node] = []
                    # Observe actual overtaking, not only randomized scheduling labels.
                    if wires[node].pos == 0:
                        from model import decode
                        try:
                            transaction = decode(wires[node].active)
                        except AssertionError:
                            transaction = None
                        if transaction is not None:
                            k = node, transaction["kind"], transaction["stream"]
                            previous = received_order.get(k, -1)
                            if transaction["identity"] < previous:
                                observed_reorder["ACK" if transaction["kind"] else "DATA"] += 1
                            received_order[k] = transaction["identity"]
                    wires[node].accept()
                if offered[node] and o["ir"]:
                    s, beat = offered[node]
                    assert 1 <= beat[-1] <= 4096
                    send_offset[node][s] += beat[1].bit_count()
                    counts["application_input_beats"] += 1
                    if beat[3]:
                        obligations[node][s]["accepted"] = True
                        deadlines[node, s, send_index[node][s]] = cycle + max_cycles
                    current[node] = None
                if mode != 0 and node < nodes:
                    if o["mv"] and o["mf"]:
                        s = o["ms"]
                        key = s, receive_base[node][s], o["mn"]
                        arrivals = received_packets[node][key]
                        required_offsets = set(range(0, o["mn"], 256))
                        assert required_offsets <= arrivals.keys(), ("DELIVERY_BEFORE_ALL_VALID_CRC", key, arrivals)
                        assert sim.cycle >= max(arrivals[offset] for offset in required_offsets) + 2, (
                            "REGISTERED_RX_LATENCY", sim.cycle, key, arrivals)
                    before = dict(oracles[node].completed)
                    oracles[node].observe(o, drive[7])
                    if o["mv"] and drive[7] and o["ml"]:
                        receive_base[node][o["ms"]] += (o["mn"] + 255) // 256
                    if mode == 1:
                        for s in range(4):
                            if oracles[node].completed[s] > before.get(s, 0):
                                idx = rx_enqueued[s]
                                if idx < len(messages[s]):
                                    data = messages[s][idx]
                                    base = rx_base[s]
                                    packets = (len(data) + 255) // 256
                                    order = list(range(min(8, packets)))
                                    rng.shuffle(order)
                                    for part in order:
                                        words = frame(0, s, sim.session, base + part, data, part * 256)
                                        rx_enqueue(words, base + part, cycle + rng.randrange(1, 65))
                                    for part in range(8, packets):
                                        rx_enqueue(frame(0, s, sim.session, base + part, data, part * 256),
                                                   base + part, cycle + 4000)
                                    rx_enqueued[s] += 1
                                    rx_base[s] += packets
                if o["sv"] and drive[8]:
                    s = o["ss"]
                    assert s in obligations[node] and obligations[node][s]["accepted"]
                    obligation = obligations[node][s]
                    expected = 0
                    assert o["sc"] == expected, ("STATUS_MISMATCH", node, s, "actual", o["sc"], "expected", expected)
                    assert not obligation["done"], ("DUPLICATE_STATUS", node, s)
                    assert cycle <= deadlines[node, s, send_index[node][s]], ("STATUS_LIVENESS_DEADLINE", node, s)
                    if mode == 0:
                        count = (len(obligation["data"]) + 255) // 256
                        expected_ids = set(range(obligation["base"], obligation["base"] + count))
                        assert expected_ids <= acked[node][s], ("PREMATURE_ACKED", s, expected_ids, acked[node][s])
                    obligation["done"] = True
                    statuses[node][s] += 1
                    send_index[node][s] += 1
                    send_offset[node][s] = 0
                    counts["status_compares"] += 1
                if mode != 1:
                    assert o["fail"] == 0 and o["exhaust"] == 0, ("unexpected failure", cycle, node, o)
            for node, words, d in emitted:
                assert d["session"] == sim.session
                if d["kind"] == 0:
                    key = d["stream"], d["identity"]
                    assert key in identities[node], ("unallocated DATA", node, d)
                    data, offset = identities[node][key]
                    assert (d["length"], d["offset"], d["payload"]) == (len(data), offset, data[offset:offset + 256]), ("DATA_FRAGMENT_MISMATCH", d)
                    assert obligations[node][d["stream"]]["accepted"], ("send before complete input", d)
                    counts["fragment_compares"] += 1
                    s = d["stream"]
                    live = tx_seen[node][s] - acked[node][s]
                    if key[1] not in tx_seen[node][s]:
                        assert not live or key[1] <= min(live) + 7, ("WINDOW_OVERFLOW", node, s, key[1], live)
                    tx_seen[node][s].add(key[1])
                    highest_occupancy[node][s] = max(highest_occupancy[node][s],
                                                    len(tx_seen[node][s] - acked[node][s]))
                    assert highest_occupancy[node][s] <= 8, ("WINDOW_OCCUPANCY", node, s)
                    if mode == 0:
                        # Only valid model ACKs are counted as acknowledgement events below.
                        ack = frame(1, d["stream"], sim.session, d["identity"])
                        ad = dict(d, kind=1)
                        fault_packet(wires[0], ack, ad, cycle, attempts[0], counts, rng, decisions, not smoke)
                    else:
                        fault_packet(wires[1 - node], words, d, cycle, attempts[node], counts, rng, decisions, not smoke)
                else:
                    counts["ack_compares"] += 1
                    key = d["stream"], d["identity"]
                    assert key in packet_arrival[node], ("ACK_BEFORE_VALID_DATA", node, key)
                    assert d["start_cycle"] >= packet_arrival[node][key] + 2, (
                        "REGISTERED_ACK_LATENCY", node, d, packet_arrival[node][key])
                    if mode == 1:
                        assert key in rx_expected, ("ACK_FOR_UNSENT_MODEL_DATA", key)
                        rx_acknowledged.add(key)
                    if mode == 2:
                        fault_packet(wires[1 - node], words, d, cycle, attempts[node], counts, rng, decisions, not smoke)
            settled = all(statuses[n][s] == len(messages[s]) for n in range(nodes) for s in range(4)) if mode != 1 else oracles[0].done()
            delivered = mode == 0 or all(oracles[n].done() for n in range(nodes))
            if settled and delivered:
                # Drain duplicate traffic and enforce no late duplicate messages/status.
                quiet = 0
                for _ in range(4000):
                    inputs = [w.offer(sim.cycle) for w in wires]
                    obs, late = sim.step(*(vector(incoming=word) for word in inputs))
                    for n in range(2):
                        if inputs[n] is not None and obs[n]["rr"]:
                            wires[n].accept()
                    for n in range(nodes):
                        if mode != 0:
                            oracles[n].observe(obs[n], 1)
                        assert not obs[n]["sv"], ("late duplicate status", obs[n])
                    for n, words, d in late:
                        if d["kind"] == 0:
                            data, offset = identities[n][d["stream"], d["identity"]]
                            assert d["payload"] == data[offset:offset + 256]
                        elif mode == 1:
                            key = d["stream"], d["identity"]
                            assert key in rx_expected
                            rx_acknowledged.add(key)
                        if mode == 2:
                            wires[1 - n].put(words, sim.cycle + 1)
                    quiet = quiet + 1 if not late and all(w.empty() for w in wires) else 0
                    if quiet >= 200:
                        break
                else:
                    raise AssertionError("DUPLICATE_DRAIN_DEADLINE")
                break
        else:
            raise AssertionError(("LIVENESS_DEADLINE", mode, seed, sim.cycle,
                                  [dict(x) for x in statuses], [dict(x.completed) for x in oracles]))
        if mode != 1:
            assert counts["fragment_compares"] and counts["status_compares"]
        if mode != 0:
            assert all(oracles[n].compared for n in range(nodes))
        if mode == 1:
            assert rx_expected <= rx_acknowledged, ("MISSING_RX_ACKS", rx_expected - rx_acknowledged)
        if not smoke:
            required = (["DATA_drop", "DATA_duplicate", "DATA_delay", "DATA_corrupt_header",
                         "DATA_corrupt_payload", "DATA_corrupt_crc"] if mode != 0 else [])
            if mode != 1:
                required += ["ACK_drop", "ACK_duplicate", "ACK_delay", "ACK_corrupt_header", "ACK_corrupt_crc"]
            assert all(counts[k] > 0 for k in required), ("UNTRIGGERED_FAULT_COVERAGE", dict(counts), required)
            if mode == 2:
                assert observed_reorder["DATA"] > 0 and observed_reorder["ACK"] > 0
            elif mode == 1:
                assert observed_reorder["DATA"] > 0
            else:
                assert observed_reorder["ACK"] > 0
        result = dict(seed=seed, mode=mode, config=sim.config, cycles=sim.cycle,
                      counts=dict(counts), observed_reorder=dict(observed_reorder),
                      compared_bytes=[o.compared for o in oracles[:nodes]],
                      messages=[dict(o.completed) for o in oracles[:nodes]],
                      statuses=[dict(s) for s in statuses[:nodes]], outcome="passed")
        result["highest_outstanding_per_stream"] = [dict(x) for x in highest_occupancy[:nodes]]
        (sim.out / "coverage.json").write_text(json.dumps(result, indent=2))
        return result
    finally:
        (sim.out / "fault_decisions.json").write_text(json.dumps(decisions, indent=2))
        sim.close()
