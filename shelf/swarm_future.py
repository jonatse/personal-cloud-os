"""
SHELVED: Swarm / Torrent-style Multi-Peer Chunk Transfer
=========================================================

Status: Shelved — not needed for current 2-device sync.
        Bring back when there are 3+ peers or files > 100 MB.

Why it was shelved
------------------
On a LAN, a single RNS.Resource already saturates the physical medium:
  - WINDOW_MAX_FAST = 75 segments * 464 bytes/segment / 0.002s RTT = 139 Mbps
  - AutoInterface physical cap = 10 Mbps
  - Single link saturates LAN before a second link can help

RNS.Resource handles chunking, windowing, retransmission, and flow control
internally. There is no need to implement any of this manually.

Correct future implementation
------------------------------
Use link.request() + destination.register_request_handler() — the native
RNS request/response system. This gives you:
  - Automatic chunking via RNS.Resource if response > MDU
  - Independent window/rate-control per link
  - Retransmission built in
  - Zero custom protocol

SEEDER side:
    for i, chunk in enumerate(split_file(path, chunk_size)):
        destination.register_request_handler(
            path     = f"/sync/chunk/{file_hash}/{i}",
            response_generator = lambda path, data, req_id, link_id, identity, ts,
                                         chunk=chunk: chunk,
            allow    = RNS.Destination.ALLOW_ALL,
        )

LEECHER side (one link per peer, N requests in flight):
    for i in missing_chunks:
        link.request(
            f"/sync/chunk/{file_hash}/{i}",
            response_callback = lambda receipt, i=i: got_chunk(i, receipt),
        )
    # RNS queues all requests on the single link.
    # Each response is delivered as RNS.Resource if > MDU bytes.
    # No custom protocol needed at all.

Optimal parallelism (number of links) by link type
---------------------------------------------------
The question "how many parallel links?" depends entirely on what the
bottleneck is for a given link type:

LAN (>1 Mbps)
  Sweet spot: 1 link per peer
  Reason: A single RNS link with WINDOW_MAX_FAST=75 already exceeds the
  AutoInterface 10 Mbps physical cap. More links add OS threads with zero
  throughput gain. Cost = 1 watchdog thread per link (50 KB RAM, wakes
  every 5s, sends keepalive every 360s).

HaLow / MANET (250 Kbps – 1 Mbps)
  Sweet spot: 2–4 links per peer
  Reason: Physical medium is not saturated by one link. RNS window starts
  at 4 and takes FAST_RATE_THRESHOLD=4 rounds to reach 75. On a slow link
  each round takes longer, so ramp-up time is the bottleneck. Running 2-4
  links in parallel means each ramps independently, and combined they fill
  the pipe faster than a single link's slow ramp.

LoRa / Radio (< 250 Kbps)
  Sweet spot: 2–3 links per peer
  Reason: Above 3 links, keepalive overhead starts to matter. Each link
  sends a keepalive packet (~60 bytes = 400 bits) every 360 seconds. At
  1200 bps that's 0.3 seconds of airtime per keepalive per link. With 10
  links = 3 seconds of keepalive traffic per 6 minutes — manageable. With
  50 links it becomes a constant trickle that crowds out data. 2-3 links
  gives meaningful parallelism without burning keepalive budget.

Implementation notes for when this gets un-shelved
----------------------------------------------------
1. Chunk size: match to RNS.Resource.MAX_EFFICIENT_SIZE (1 MB) per segment.
   RNS.Resource auto-segments larger data, so you could just use one Resource
   per file and let RNS handle it. Only implement manual chunking if you need
   multi-peer chunk sourcing (different peers provide different chunks).

2. For multi-peer sourcing: use content-addressed chunks (SHA-256 of each
   chunk), register handlers on the destination, let any peer request any
   chunk. The leecher tracks which chunks it has and requests missing ones
   from whichever peer has them.

3. Sliding window for requests: don't fire all N chunk requests at once.
   Use a window of (N_links * WINDOW_MAX_FAST) outstanding requests, sliding
   forward as responses arrive. This prevents flooding the RNS queue.

4. Bandwidth reservation: use transport/bandwidth.py BandwidthGovernor to
   reserve 20% for messaging/IoT before allocating bulk transfer budget.

5. Resume across reconnects: store received chunks in a temp directory with
   content-addressed names. On reconnect, re-register wants for only the
   missing chunks. RNS.Resource handles retransmission within a session;
   cross-session resume is application-layer.

6. The N-link sweet spot is worth auto-detecting:
      if link.get_expected_rate() > 1_000_000:  # >1 Mbps
          n_links = 1
      elif link.get_expected_rate() > 250_000:  # 250 Kbps – 1 Mbps
          n_links = 3
      else:                                      # slow link
          n_links = 2

   This can be read from transport/detector.py LinkProfile.

Original swarm.py location: src/transport/swarm.py (still present but not called)
"""

# Nothing to import or run — this is a design document only.
