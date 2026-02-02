import pymem
import pymem.process
import struct
import sys

PROCESS_NAME = "ProjectAlpha-Win64-Shipping.exe"

# Cheat Engine pointer info (Current Health)
BASE_OFFSET = 0x064D8FD0
OFFSETS = [
    0x30,
    0x8C8,
    0xB0,
    0x2F0,
    0x368
]

def resolve_pointer_chain(pm, base_address, offsets):
    """
    Resolves a multi-level pointer chain and returns the final address.
    """
    addr = base_address

    for level, offset in enumerate(offsets):
        try:
            addr = pm.read_ulonglong(addr)
        except pymem.exception.MemoryReadError:
            raise RuntimeError(
                f"Failed to read pointer at level {level} (address: {hex(addr)})"
            )

        addr += offset

    return addr


def main():
    try:
        pm = pymem.Pymem(PROCESS_NAME)
    except pymem.exception.ProcessNotFound:
        print(f"[ERROR] Process '{PROCESS_NAME}' not found.")
        sys.exit(1)

    print(f"[OK] Attached to {PROCESS_NAME} (PID: {pm.process_id})")

    try:
        module = pymem.process.module_from_name(
            pm.process_handle,
            PROCESS_NAME
        )
    except Exception as e:
        print("[ERROR] Failed to get module base address:", e)
        sys.exit(1)

    module_base = module.lpBaseOfDll
    print(f"[OK] Module base address: {hex(module_base)}")

    base_address = module_base + BASE_OFFSET
    print(f"[OK] Base pointer address: {hex(base_address)}")

    try:
        final_address = resolve_pointer_chain(pm, base_address, OFFSETS)
    except RuntimeError as e:
        print("[ERROR]", e)
        sys.exit(1)

    print(f"[OK] Final address: {hex(final_address)}")

    try:
        raw = pm.read_bytes(final_address, 8)
        current_health = struct.unpack("<d", raw)[0]
    except pymem.exception.MemoryReadError:
        print("[ERROR] Failed to read current health value.")
        sys.exit(1)

    print(f"[RESULT] Player Current Health: {current_health}")


if __name__ == "__main__":
    main()
