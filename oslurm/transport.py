"""Bounded, checksum-acknowledged TCP loopback transport for hardware-free integration.

This moves real bytes through the IP stack. It is neither an RF device driver
nor an authenticated remote service; binding is deliberately loopback-only.
"""
from __future__ import annotations

import hashlib
import json
import queue
import socket
import threading
from pathlib import Path


class LoopbackTCPTransport:
    def __init__(self, timeout_s=10, max_bytes=256 * 1024 * 1024):
        if timeout_s <= 0 or max_bytes <= 0:
            raise ValueError("invalid TCP limits")
        self.timeout_s, self.max_bytes = timeout_s, max_bytes

    def copy(self, source: Path, destination: Path) -> dict:
        size = source.stat().st_size
        if not 0 < size <= self.max_bytes:
            raise ValueError("TCP payload outside configured bounds")
        with source.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        outcome = queue.Queue(maxsize=1)
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.settimeout(self.timeout_s)
        try:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
        except Exception:
            listener.close()
            raise

        def receive():
            try:
                connection, _ = listener.accept()
                with connection:
                    connection.settimeout(self.timeout_s)
                    with connection.makefile("rb") as stream:
                        header = stream.readline(1025)
                        if len(header) > 1024 or not header.endswith(b"\n"):
                            raise ValueError("invalid TCP header")
                        request = json.loads(header)
                        if request != {"version": 1, "bytes": size, "sha256": digest}:
                            raise ValueError("invalid TCP payload metadata")
                        remaining, hasher = size, hashlib.sha256()
                        with destination.open("wb") as output:
                            while remaining:
                                block = stream.read(min(65536, remaining))
                                if not block:
                                    raise ValueError("truncated TCP payload")
                                output.write(block)
                                hasher.update(block)
                                remaining -= len(block)
                        if hasher.hexdigest() != digest:
                            raise ValueError("TCP receiver checksum mismatch")
                        connection.sendall((digest + "\n").encode("ascii"))
                outcome.put(None)
            except Exception as exc:
                outcome.put(exc)

        worker = threading.Thread(target=receive, name="oslurm-tcp-receiver", daemon=True)
        worker.start()
        try:
            with socket.create_connection(listener.getsockname(), self.timeout_s) as connection:
                connection.settimeout(self.timeout_s)
                connection.sendall((json.dumps({"version": 1, "bytes": size, "sha256": digest}) + "\n").encode())
                with source.open("rb") as stream:
                    while block := stream.read(65536):
                        connection.sendall(block)
                connection.shutdown(socket.SHUT_WR)
                with connection.makefile("rb") as stream:
                    if stream.readline(66) != (digest + "\n").encode():
                        raise ValueError("TCP acknowledgement mismatch")
        finally:
            listener.close()
            worker.join(self.timeout_s + 1)
        if worker.is_alive():
            raise TimeoutError("TCP receiver did not terminate")
        error = outcome.get_nowait()
        if error:
            raise error
        return {"transport": "tcp-loopback", "bytes": size, "sha256": digest}
