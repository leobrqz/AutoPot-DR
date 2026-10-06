"""Shared helpers for read-only standalone value inspectors."""

import os
import struct
import sys

import pymem
import pymem.process

SRC_DIRECTORY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SRC_DIRECTORY not in sys.path:
    sys.path.insert(0, SRC_DIRECTORY)

from unreal_reader import UnrealReflectionReader


PROCESS_NAME = "ProjectAlpha-Win64-Shipping.exe"


def attach_and_resolve():
    process = pymem.Pymem(PROCESS_NAME)
    try:
        module = pymem.process.module_from_name(
            process.process_handle, PROCESS_NAME
        )
        targets = UnrealReflectionReader(
            process, module.lpBaseOfDll
        ).resolve()
        return process, targets
    except Exception:
        process.close_process()
        raise


def read_double(process, address):
    return struct.unpack("<d", process.read_bytes(address, 8))[0]


def read_int(process, address):
    return process.read_int(address)
