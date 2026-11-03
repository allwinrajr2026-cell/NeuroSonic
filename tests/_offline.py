"""Test helper: forbid any network access except to this machine (loopback).

Used to show that voice synthesis, map search and routing work without internet *in-process*. It does not replace
a test with the network physically disconnected (see docs/FEATURE_STATUS.md).
"""
import contextlib
import ipaddress
import socket


class NetworkBlocked(AssertionError):
    pass


def _is_local(host):
    if host in ("localhost", "", None):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@contextlib.contextmanager
def no_internet():
    attempts = []
    orig_connect, orig_cc, orig_gai = socket.socket.connect, socket.create_connection, socket.getaddrinfo

    def connect(self, address):
        host = address[0] if isinstance(address, tuple) else address
        if not _is_local(host):
            attempts.append(address)
            raise NetworkBlocked(f"blocked network access to {address}")
        return orig_connect(self, address)

    def create_connection(address, *a, **kw):
        if not _is_local(address[0]):
            attempts.append(address)
            raise NetworkBlocked(f"blocked network access to {address}")
        return orig_cc(address, *a, **kw)

    def getaddrinfo(host, *a, **kw):
        if not _is_local(host):
            attempts.append(host)
            raise NetworkBlocked(f"blocked DNS lookup of {host}")
        return orig_gai(host, *a, **kw)

    socket.socket.connect, socket.create_connection, socket.getaddrinfo = connect, create_connection, getaddrinfo
    try:
        yield attempts
    finally:
        socket.socket.connect, socket.create_connection, socket.getaddrinfo = orig_connect, orig_cc, orig_gai
