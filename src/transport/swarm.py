"""
Swarm Transfer - Torrent-style multi-peer chunk exchange over RNS.

Used when link speed is MEDIUM (62.5 Kbps – 1 Mbps): too slow for
WireGuard overhead to be worthwhile, fast enough for chunked file transfer.

Design:
  - Each file is identified by its SHA-256 hash (content-addressed)
  - The file is split into fixed-size chunks (default 384 bytes — fits in
    one RNS packet with framing overhead)
  - Any node that has one or more chunks announces them via a small
    HAVE message: {type: "have", file_hash, chunks: [0,3,7,...]}
  - Nodes that need chunks send REQUEST messages to any peer that has them
  - Bandwidth is throttled to stay within the 70% bulk budget

Wire protocol (JSON, sent via PeerLinkService.send_json_to_peer):
  HAVE    {t:"have",    fh:<sha256_hex>, name:<filename>, size:<bytes>, chunks:[...]}
  REQUEST {t:"request", fh:<sha256_hex>, chunk:<int>}
  CHUNK   {t:"chunk",   fh:<sha256_hex>, chunk:<int>, data:<hex>}
  DONE    {t:"done",    fh:<sha256_hex>}

Integration:
  SyncEngine calls swarm.announce(file_hash, path) when it wants to share.
  SyncEngine calls swarm.want(file_hash, dest_path, total_chunks) to download.
  swarm calls peer_link.send_json_to_peer() for all wire messages.
  swarm calls peer_link.register_data_callback() per peer to receive replies.
  The on_complete callback is invoked when all chunks are assembled.
"""
from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# Chunk size in bytes — must fit in one RNS packet after hex-encoding in JSON.
# RNS.Link.MDU = 431; JSON envelope overhead ≈ 80 bytes; hex doubles size.
# So: (431 - 80) / 2 ≈ 175 bytes of binary data per chunk.
# We use 160 to leave comfortable headroom.
CHUNK_SIZE = 160

MSG_HAVE    = "have"
MSG_REQUEST = "request"
MSG_CHUNK   = "chunk"
MSG_DONE    = "done"


@dataclass
class _SwarmFile:
    """State for one file being seeded (outbound)."""
    file_hash:    str
    name:         str
    path:         str
    size:         int
    total_chunks: int
    chunks_have:  Set[int] = field(default_factory=set)  # chunk indices we have


@dataclass
class _WantFile:
    """State for one file being downloaded (inbound)."""
    file_hash:    str
    dest_path:    str
    total_chunks: int
    chunks_have:  Dict[int, bytes] = field(default_factory=dict)
    on_complete:  Optional[Callable[[str], None]] = None  # called with dest_path
    started_at:   float = field(default_factory=time.monotonic)


class SwarmManager:
    """
    Manages torrent-style chunk exchange with all connected peers.

    Thread-safe — all methods can be called from RNS callbacks.
    """

    def __init__(self, peer_link_service, bandwidth_governor=None):
        self._pls       = peer_link_service
        self._bwg       = bandwidth_governor
        self._lock      = threading.Lock()
        self._seeding:  Dict[str, _SwarmFile] = {}   # file_hash → _SwarmFile
        self._wanting:  Dict[str, _WantFile]  = {}   # file_hash → _WantFile
        self._peers_with: Dict[str, Set[str]] = {}   # file_hash → set of peer_ids

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def announce(self, file_hash: str, path: str):
        """
        Start seeding a file — announce it to all connected peers.
        """
        if not os.path.exists(path):
            logger.warning(f"SwarmManager.announce: file not found: {path}")
            return

        size  = os.path.getsize(path)
        name  = os.path.basename(path)
        total = _total_chunks(size)

        sf = _SwarmFile(
            file_hash=file_hash,
            name=name,
            path=path,
            size=size,
            total_chunks=total,
            chunks_have=set(range(total)),   # we have all chunks
        )

        with self._lock:
            self._seeding[file_hash] = sf

        self._broadcast_have(sf)
        logger.info(f"Swarm: seeding {name} ({size} bytes, {total} chunks)")

    def want(self, file_hash: str, dest_path: str, total_chunks: int,
             on_complete: Optional[Callable[[str], None]] = None):
        """
        Express interest in a file — send REQUEST messages to any peer
        that has it.
        """
        with self._lock:
            if file_hash in self._wanting:
                return  # already in progress
            self._wanting[file_hash] = _WantFile(
                file_hash=file_hash,
                dest_path=dest_path,
                total_chunks=total_chunks,
                on_complete=on_complete,
            )
            peers = list(self._peers_with.get(file_hash, set()))

        logger.info(f"Swarm: wanting {file_hash[:16]}… ({total_chunks} chunks), "
                    f"{len(peers)} peer(s) can supply")

        for peer_id in peers:
            self._request_chunks_from(peer_id, file_hash)

    def handle_message(self, peer_id: str, msg: dict):
        """
        Dispatch an inbound swarm wire message.
        Called by SyncEngine._handle_peer_data when msg["t"] is a swarm type.
        """
        t = msg.get("t")
        if t == MSG_HAVE:
            self._on_have(peer_id, msg)
        elif t == MSG_REQUEST:
            self._on_request(peer_id, msg)
        elif t == MSG_CHUNK:
            self._on_chunk(peer_id, msg)
        elif t == MSG_DONE:
            self._on_done(peer_id, msg)
        else:
            logger.debug(f"SwarmManager: unknown message type '{t}' from {peer_id}")

    def stop(self):
        """Clean up all in-progress transfers."""
        with self._lock:
            self._seeding.clear()
            self._wanting.clear()
            self._peers_with.clear()

    # ------------------------------------------------------------------ #
    # Outbound message helpers                                             #
    # ------------------------------------------------------------------ #

    def _broadcast_have(self, sf: _SwarmFile):
        peers = self._pls.get_connected_peers()
        msg = {
            "t":      MSG_HAVE,
            "fh":     sf.file_hash,
            "name":   sf.name,
            "size":   sf.size,
            "chunks": sorted(sf.chunks_have),
        }
        for peer_id in peers:
            self._pls.send_json_to_peer(peer_id, msg)

    def _request_chunks_from(self, peer_id: str, file_hash: str):
        with self._lock:
            wf = self._wanting.get(file_hash)
            if not wf:
                return
            needed = [i for i in range(wf.total_chunks)
                      if i not in wf.chunks_have]

        for chunk_idx in needed:
            self._pls.send_json_to_peer(peer_id, {
                "t":  MSG_REQUEST,
                "fh": file_hash,
                "chunk": chunk_idx,
            })

    def _send_chunk(self, peer_id: str, sf: _SwarmFile, chunk_idx: int):
        try:
            with open(sf.path, "rb") as f:
                f.seek(chunk_idx * CHUNK_SIZE)
                data = f.read(CHUNK_SIZE)

            if self._bwg:
                profile = self._pls.get_link_profile(peer_id)
                if profile:
                    ok, warn = self._bwg.check_transfer(profile, len(data))
                    if not ok:
                        return
                    if warn:
                        logger.warning(warn)

            self._pls.send_json_to_peer(peer_id, {
                "t":     MSG_CHUNK,
                "fh":    sf.file_hash,
                "chunk": chunk_idx,
                "data":  data.hex(),
            })

            if self._bwg:
                self._bwg.record_transfer(peer_id, len(data), "bulk")

        except Exception as exc:
            logger.error(f"Swarm: error sending chunk {chunk_idx} of "
                         f"{sf.file_hash[:16]} to {peer_id}: {exc}")

    # ------------------------------------------------------------------ #
    # Inbound message handlers                                             #
    # ------------------------------------------------------------------ #

    def _on_have(self, peer_id: str, msg: dict):
        fh     = msg.get("fh", "")
        name   = msg.get("name", "")
        size   = msg.get("size", 0)
        chunks = set(msg.get("chunks", []))

        with self._lock:
            if fh not in self._peers_with:
                self._peers_with[fh] = set()
            self._peers_with[fh].add(peer_id)

            wf = self._wanting.get(fh)

        if wf:
            # We want this file — request the missing chunks from this peer
            logger.info(f"Swarm: peer {peer_id[:12]} has {len(chunks)} chunks "
                        f"of {name} we want")
            self._request_chunks_from(peer_id, fh)
        else:
            logger.debug(f"Swarm: peer {peer_id[:12]} has {name} "
                         f"({size} bytes) — not currently wanted")

    def _on_request(self, peer_id: str, msg: dict):
        fh        = msg.get("fh", "")
        chunk_idx = msg.get("chunk", 0)

        with self._lock:
            sf = self._seeding.get(fh)

        if not sf or chunk_idx not in sf.chunks_have:
            logger.debug(f"Swarm: requested chunk {chunk_idx} of {fh[:16]} "
                         f"but we don't have it")
            return

        threading.Thread(
            target=self._send_chunk,
            args=(peer_id, sf, chunk_idx),
            daemon=True,
            name=f"swarm-send-{fh[:8]}-{chunk_idx}",
        ).start()

    def _on_chunk(self, peer_id: str, msg: dict):
        fh        = msg.get("fh", "")
        chunk_idx = msg.get("chunk", 0)
        data_hex  = msg.get("data", "")

        try:
            data = bytes.fromhex(data_hex)
        except ValueError:
            logger.error(f"Swarm: invalid hex data in chunk from {peer_id}")
            return

        with self._lock:
            wf = self._wanting.get(fh)
            if not wf:
                return
            wf.chunks_have[chunk_idx] = data
            complete = (len(wf.chunks_have) == wf.total_chunks)
            if complete:
                del self._wanting[fh]

        if self._bwg:
            self._bwg.record_transfer(peer_id, len(data), "bulk")

        if complete:
            self._assemble(fh, wf)

    def _on_done(self, peer_id: str, msg: dict):
        fh = msg.get("fh", "")
        logger.debug(f"Swarm: peer {peer_id[:12]} signalled DONE for {fh[:16]}")

    # ------------------------------------------------------------------ #
    # Assembly                                                             #
    # ------------------------------------------------------------------ #

    def _assemble(self, file_hash: str, wf: _WantFile):
        """Write all chunks to dest_path and verify hash."""
        try:
            parent = os.path.dirname(wf.dest_path)
            if parent:
                os.makedirs(parent, exist_ok=True)

            hasher = hashlib.sha256()
            with open(wf.dest_path, "wb") as f:
                for i in range(wf.total_chunks):
                    chunk = wf.chunks_have[i]
                    f.write(chunk)
                    hasher.update(chunk)

            actual_hash = hasher.hexdigest()
            if actual_hash != file_hash:
                logger.error(
                    f"Swarm: hash mismatch for {wf.dest_path}! "
                    f"expected {file_hash[:16]} got {actual_hash[:16]}")
                os.remove(wf.dest_path)
                return

            elapsed = time.monotonic() - wf.started_at
            size    = sum(len(c) for c in wf.chunks_have.values())
            rate    = size / elapsed if elapsed > 0 else 0
            logger.info(
                f"Swarm: assembled {os.path.basename(wf.dest_path)} "
                f"({size} bytes in {elapsed:.1f}s, {rate/1000:.1f} KB/s)")

            if wf.on_complete:
                wf.on_complete(wf.dest_path)

        except Exception as exc:
            logger.error(f"Swarm: assembly failed for {file_hash[:16]}: {exc}",
                         exc_info=True)


# ── Utility ──────────────────────────────────────────────────────────────── #

def _total_chunks(file_size: int) -> int:
    """Number of CHUNK_SIZE chunks needed for file_size bytes."""
    return max(1, (file_size + CHUNK_SIZE - 1) // CHUNK_SIZE)


def file_hash(path: str) -> str:
    """SHA-256 hash of a file's contents (hex string)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()
