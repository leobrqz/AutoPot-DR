#!/usr/bin/env python3
"""Single-file, console-only AutoPot for offline Dwarven Realms sessions.

Requires: pip install pymem keyboard
Usage:    python src/standalone/autopot_standalone.py --threshold 30
Dry run:  python src/standalone/autopot_standalone.py --dry-run

The Unreal reflection reader below is embedded so this file can be shared by
itself. It reads process memory but never writes to game memory.
"""
import argparse
import ctypes
import math
import struct
import sys
import time
from ctypes import wintypes

import keyboard
import pymem
import pymem.process

GAME_PROCESS_NAME = "ProjectAlpha-Win64-Shipping.exe"
DEFAULT_POTION_KEY = "r"
POLL_INTERVAL_SECONDS = 0.05
RESOLVE_INTERVAL_SECONDS = 0.25
POTION_COOLDOWN_SECONDS = 0.5
MAX_VALID_VALUE = 100000000

"""Read player state from Unreal's live object graph and reflected properties.

Only the module-relative engine globals are build-specific. Object links and
field offsets are resolved from the running game's UObject/FField metadata.
This reader is read-only.
"""

import struct
import time


class UnrealReflectionError(RuntimeError):
    """Raised when the expected Unreal object graph cannot be validated."""


class UnrealReflectionReader:
    # Current-build hints. If either moves, scan writable PE data for the
    # matching Unreal global and validate it through live UObject metadata.
    GWORLD_RVA = 0x6500248
    FNAME_POOL_RVA = 0x62ED0C0

    MAX_CLASS_DEPTH = 40
    MAX_FIELDS_PER_CLASS = 4096
    MAX_NAME_LENGTH = 1024

    def __init__(self, process_memory, module_base):
        self.pm = process_memory
        self.module_base = module_base
        self._name_cache = {}
        self._property_cache = {}
        self._writable_sections_cache = None
        self._world_candidate_sources = None
        self._world_candidate_scan_after = 0.0
        self._world_candidate_scan_performed = False
        self._world_source_address = None
        self._fname_pool = self._find_fname_pool()

    def _bytes(self, address, size):
        if not isinstance(address, int) or address < 0x10000 or size <= 0:
            raise UnrealReflectionError("Invalid memory range")
        try:
            data = self.pm.read_bytes(address, size)
        except Exception as exc:
            raise UnrealReflectionError(f"Unreadable memory at 0x{address:X}") from exc
        if len(data) != size:
            raise UnrealReflectionError(f"Short read at 0x{address:X}")
        return data

    def _u8(self, address):
        return self._bytes(address, 1)[0]

    def _u32(self, address):
        return struct.unpack("<I", self._bytes(address, 4))[0]

    def _i32(self, address):
        return struct.unpack("<i", self._bytes(address, 4))[0]

    def _ptr(self, address, allow_null=False):
        value = struct.unpack("<Q", self._bytes(address, 8))[0]
        if value == 0 and allow_null:
            return 0
        if value < 0x10000 or value >= 0x0000800000000000:
            raise UnrealReflectionError(f"Invalid pointer read at 0x{address:X}")
        return value

    def _is_heap_pointer(self, value):
        image_end = self.module_base + 0x100000000
        return (
            0x10000000000 <= value < 0x0000800000000000
            and not self.module_base <= value < image_end
        )

    def _read_writable_sections(self):
        """Read non-executable writable sections used for Unreal globals."""
        if self._writable_sections_cache is not None:
            return self._writable_sections_cache

        dos_header = self._bytes(self.module_base, 0x40)
        if dos_header[:2] != b"MZ":
            raise UnrealReflectionError("Game module is not a PE image")
        nt_offset = struct.unpack_from("<I", dos_header, 0x3C)[0]
        if nt_offset > 0x100000:
            raise UnrealReflectionError("PE header offset did not validate")

        nt_header = self._bytes(self.module_base + nt_offset, 24)
        if nt_header[:4] != b"PE\0\0":
            raise UnrealReflectionError("PE signature did not validate")
        section_count = struct.unpack_from("<H", nt_header, 6)[0]
        optional_size = struct.unpack_from("<H", nt_header, 20)[0]
        if section_count == 0 or section_count > 32 or optional_size > 0x1000:
            raise UnrealReflectionError("PE section table did not validate")

        section_table = self.module_base + nt_offset + 24 + optional_size
        raw_sections = self._bytes(section_table, section_count * 40)
        sections = []
        for index in range(section_count):
            start = index * 40
            header = raw_sections[start:start + 40]
            virtual_size, virtual_address = struct.unpack_from("<II", header, 8)
            characteristics = struct.unpack_from("<I", header, 36)[0]
            readable = bool(characteristics & 0x40000000)
            writable = bool(characteristics & 0x80000000)
            executable = bool(characteristics & 0x20000000)
            if not readable or not writable or executable or virtual_size < 0x20:
                continue
            if virtual_size > 0x4000000:
                raise UnrealReflectionError("Writable PE section is unexpectedly large")
            address = self.module_base + virtual_address
            sections.append((address, self._bytes(address, virtual_size)))

        if not sections:
            raise UnrealReflectionError("No writable PE data section was found")
        self._writable_sections_cache = sections
        return sections

    def _is_fname_pool(self, address):
        try:
            current_block = self._u32(address + 0x8)
            cursor = self._u32(address + 0xC)
            if current_block > 0xFFFF or cursor < 6 or cursor > 0x20000:
                return False
            first_block = self._ptr(address + 0x10)
            if not self._is_heap_pointer(first_block):
                return False
            header = struct.unpack("<H", self._bytes(first_block, 2))[0]
            length = header >> 6
            if length != 4 or header & 1:
                return False
            return self._bytes(first_block + 2, 4) == b"None"
        except Exception:
            return False

    def _find_fname_pool(self):
        hint = self.module_base + self.FNAME_POOL_RVA
        if self._is_fname_pool(hint):
            return hint

        matches = []
        for section_address, data in self._read_writable_sections():
            for offset in range(0, len(data) - 0x18, 8):
                current_block, cursor = struct.unpack_from("<II", data, offset + 8)
                if current_block > 0xFFFF or cursor < 6 or cursor > 0x20000:
                    continue
                first_block = struct.unpack_from("<Q", data, offset + 0x10)[0]
                if not self._is_heap_pointer(first_block):
                    continue
                candidate = section_address + offset
                if self._is_fname_pool(candidate):
                    matches.append(candidate)

        if len(matches) != 1:
            raise UnrealReflectionError(
                f"FNamePool discovery found {len(matches)} valid candidates"
            )
        return matches[0]

    def _name_from_id(self, name_id):
        if name_id in self._name_cache:
            return self._name_cache[name_id]

        block_index = (name_id >> 16) & 0xFFFF
        entry_offset = (name_id & 0xFFFF) * 2
        current_block = self._u32(self._fname_pool + 0x8)
        if block_index > current_block:
            raise UnrealReflectionError("FName refers to an unallocated block")

        block = self._ptr(self._fname_pool + 0x10 + block_index * 8)
        entry = block + entry_offset
        header = struct.unpack("<H", self._bytes(entry, 2))[0]
        length = header >> 6
        wide = bool(header & 1)
        if length > self.MAX_NAME_LENGTH:
            raise UnrealReflectionError("FName entry length did not validate")

        byte_length = length * (2 if wide else 1)
        raw = self._bytes(entry + 2, byte_length) if byte_length else b""
        encoding = "utf-16-le" if wide else "utf-8"
        value = raw.decode(encoding, errors="replace")
        self._name_cache[name_id] = value
        return value

    def _object_name(self, obj):
        name_id = self._u32(obj + 0x18)
        number = self._u32(obj + 0x1C)
        name = self._name_from_id(name_id)
        return f"{name}_{number - 1}" if number else name

    def _field_name(self, field):
        name_id = self._u32(field + 0x20)
        number = self._u32(field + 0x24)
        name = self._name_from_id(name_id)
        return f"{name}_{number - 1}" if number else name

    def _class_pointer(self, obj):
        return self._ptr(obj + 0x10)

    def _class_name(self, obj):
        return self._object_name(self._class_pointer(obj))

    def _class_lineage(self, class_pointer):
        seen = set()
        current = class_pointer
        for _ in range(self.MAX_CLASS_DEPTH):
            if not current or current in seen:
                break
            seen.add(current)
            yield current, self._object_name(current)
            current = self._ptr(current + 0x40, allow_null=True)

    def _has_parent_named(self, class_pointer, expected_name):
        return any(name == expected_name for _, name in self._class_lineage(class_pointer))

    @staticmethod
    def _matches_property(actual_name, requested_name):
        if actual_name == requested_name:
            return True
        # Blueprint-generated FFields may add a numeric suffix and GUID.
        prefix = requested_name + "_"
        if not actual_name.startswith(prefix):
            return False
        suffix = actual_name[len(prefix):].split("_", 1)[0]
        return suffix.isdigit()

    def _find_property(self, class_pointer, requested_name):
        cache_key = (class_pointer, requested_name)
        if cache_key in self._property_cache:
            return self._property_cache[cache_key]

        class_seen = set()
        current_class = class_pointer
        for _ in range(self.MAX_CLASS_DEPTH):
            if not current_class or current_class in class_seen:
                break
            class_seen.add(current_class)

            field = self._ptr(current_class + 0x50, allow_null=True)
            field_seen = set()
            for _ in range(self.MAX_FIELDS_PER_CLASS):
                if not field or field in field_seen:
                    break
                field_seen.add(field)
                if self._matches_property(self._field_name(field), requested_name):
                    offset = self._u32(field + 0x44)
                    size = self._u32(field + 0x34)
                    class_size = self._u32(current_class + 0x58)
                    if size == 0 or offset + size > class_size:
                        raise UnrealReflectionError(
                            f"Reflected field {requested_name!r} is outside its class"
                        )
                    result = (offset, size)
                    self._property_cache[cache_key] = result
                    return result
                field = self._ptr(field + 0x18, allow_null=True)

            current_class = self._ptr(current_class + 0x40, allow_null=True)

        raise UnrealReflectionError(f"Reflected property {requested_name!r} was not found")

    def _property(self, obj, requested_name, expected_size=None):
        class_pointer = self._class_pointer(obj)
        offset, size = self._find_property(class_pointer, requested_name)
        if expected_size is not None and size != expected_size:
            raise UnrealReflectionError(
                f"Reflected property {requested_name!r} has size {size}, expected {expected_size}"
            )
        return obj + offset, size

    def _object_property(self, obj, requested_name, allow_null=False):
        address, size = self._property(obj, requested_name, expected_size=8)
        return self._ptr(address, allow_null=allow_null)

    def _array_first_pointer(self, obj, requested_name):
        address, size = self._property(obj, requested_name, expected_size=16)
        data = self._ptr(address, allow_null=True)
        count = self._i32(address + 8)
        capacity = self._i32(address + 12)
        if data == 0 or count < 1 or count > 64 or capacity < count:
            raise UnrealReflectionError(f"Reflected array {requested_name!r} is not populated")
        return self._ptr(data)

    def resolve(self):
        """Resolve and validate live health and potion field addresses."""
        if self._world_source_address is not None:
            try:
                world = self._ptr(self._world_source_address)
                return self._resolve_from_world(world, self._world_source_address)
            except Exception:
                self._world_source_address = None

        hint_address = self.module_base + self.GWORLD_RVA
        try:
            world = self._ptr(hint_address)
            targets = self._resolve_from_world(world, hint_address)
            self._world_source_address = hint_address
            return targets
        except Exception:
            pass

        candidates = self._find_world_candidates()
        valid_worlds = {}
        for source_address, world in candidates:
            try:
                targets = self._resolve_from_world(world, source_address)
            except Exception:
                continue
            valid_worlds[world] = (source_address, targets)

        if not valid_worlds and candidates:
            # Cached slots can still point to UWorld objects whose player graph
            # is obsolete. Drop them and allow one fresh scan; subsequent scans
            # remain rate-limited below while the world graph is unavailable.
            self._world_candidate_sources = None
            if not self._world_candidate_scan_performed:
                self._world_candidate_scan_after = 0.0

        if len(valid_worlds) != 1:
            raise UnrealReflectionError(
                f"Active UWorld discovery found {len(valid_worlds)} valid worlds"
            )

        source_address, targets = next(iter(valid_worlds.values()))
        self._world_source_address = source_address
        return targets

    def _find_world_candidates(self):
        """Find UWorld object references in writable module data."""
        now = time.monotonic()
        self._world_candidate_scan_performed = False

        if self._world_candidate_sources is not None:
            if not self._world_candidate_sources:
                if now < self._world_candidate_scan_after:
                    return []
            else:
                candidates = []
                for source_address in self._world_candidate_sources:
                    try:
                        obj = self._ptr(source_address)
                        if self._is_heap_pointer(obj):
                            if self._object_name(self._class_pointer(obj)) == "World":
                                candidates.append((source_address, obj))
                    except Exception:
                        continue
                if candidates:
                    return candidates

                # The old references have stopped pointing to UWorld objects.
                # A fresh scan may find the global slot after a map/layout change.
                self._world_candidate_sources = None

        if now < self._world_candidate_scan_after:
            return []

        self._world_candidate_scan_after = now + 2.0
        self._world_candidate_scan_performed = True

        candidates = []
        seen_objects = set()
        for section_address, data in self._read_writable_sections():
            for offset in range(0, len(data) - 7, 8):
                obj = struct.unpack_from("<Q", data, offset)[0]
                if not self._is_heap_pointer(obj) or obj in seen_objects:
                    continue
                seen_objects.add(obj)
                try:
                    class_pointer = self._class_pointer(obj)
                    if self._object_name(class_pointer) == "World":
                        candidates.append((section_address + offset, obj))
                except Exception:
                    continue
        self._world_candidate_sources = tuple(
            source_address for source_address, _ in candidates
        )
        return candidates

    def _resolve_from_world(self, world, source_address):
        """Follow reflected properties from one candidate UWorld."""
        world_class = self._class_pointer(world)
        if not self._has_parent_named(world_class, "World"):
            raise UnrealReflectionError("GWorld did not point to a UWorld object")

        game_instance = self._object_property(world, "OwningGameInstance")
        if not self._has_parent_named(self._class_pointer(game_instance), "GameInstance"):
            raise UnrealReflectionError("UWorld's game instance did not validate")

        local_player = self._array_first_pointer(game_instance, "LocalPlayers")
        if self._class_name(local_player) != "LocalPlayer":
            raise UnrealReflectionError("First local player did not validate")

        controller = self._object_property(local_player, "PlayerController")
        controller_class = self._class_pointer(controller)
        if not self._has_parent_named(controller_class, "PlayerController"):
            raise UnrealReflectionError("LocalPlayer's controller did not validate")

        pawn = self._object_property(controller, "Pawn", allow_null=True)
        pawn_class = self._class_pointer(pawn) if pawn else 0
        if not pawn or not self._has_parent_named(pawn_class, "Pawn"):
            # AcknowledgedPawn is available on PlayerController and is the
            # canonical fallback during possession transitions.
            pawn = self._object_property(
                controller, "AcknowledgedPawn", allow_null=True
            )
            if not pawn:
                raise UnrealReflectionError("PlayerController has no possessed pawn")
            pawn_class = self._class_pointer(pawn)
            if not self._has_parent_named(pawn_class, "Pawn"):
                raise UnrealReflectionError("PlayerController's pawn did not validate")

        potion_manager = self._object_property(controller, "BP_PotionManager")
        manager_class = self._class_pointer(potion_manager)
        manager_class_name = self._object_name(manager_class)
        if "PotionManager" not in manager_class_name:
            raise UnrealReflectionError("PlayerController's potion manager did not validate")
        if self._ptr(potion_manager + 0x20, allow_null=True) != controller:
            raise UnrealReflectionError("Potion manager is not owned by the local controller")

        health_address, health_size = self._property(pawn, "Health", expected_size=8)
        max_health_address, max_health_size = self._property(pawn, "MaxHealth", expected_size=8)
        current_potions_address, current_potions_size = self._property(
            potion_manager, "Available Potions", expected_size=4
        )
        max_potions_address, max_potions_size = self._property(
            potion_manager, "Max Potions", expected_size=4
        )

        return {
            "world": world,
            "world_source": source_address,
            "game_instance": game_instance,
            "local_player": local_player,
            "controller": controller,
            "pawn": pawn,
            "potion_manager": potion_manager,
            "health": health_address,
            "max_health": max_health_address,
            "current_potions": current_potions_address,
            "max_potions": max_potions_address,
            "health_size": health_size,
            "max_health_size": max_health_size,
            "current_potions_size": current_potions_size,
            "max_potions_size": max_potions_size,
            "pawn_class": self._object_name(pawn_class),
            "manager_class": manager_class_name,
        }


def parse_args():
    parser = argparse.ArgumentParser(
        description="Offline console AutoPot for Dwarven Realms (no GUI)."
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=30.0,
        help="Use a potion below this health percentage (default: 30).",
    )
    parser.add_argument(
        "--key",
        default=DEFAULT_POTION_KEY,
        help="Game key that uses a potion (default: r).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show when a potion would be used without sending a keypress.",
    )
    args = parser.parse_args()
    if not 0 <= args.threshold <= 100:
        parser.error("--threshold must be between 0 and 100")
    if not args.key:
        parser.error("--key cannot be empty")
    return args


def _is_game_focused(process_id):
    if sys.platform != "win32":
        return False
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    if not hwnd:
        return False
    foreground_pid = wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(
        hwnd, ctypes.byref(foreground_pid)
    )
    return foreground_pid.value == process_id


def _focus_game_window(process_id):
    if sys.platform != "win32":
        return False

    user32 = ctypes.windll.user32
    found_window = [False]

    def enum_windows_callback(hwnd, _lparam):
        window_pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_pid))
        if window_pid.value == process_id and user32.IsWindowVisible(hwnd):
            found_window[0] = True
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            user32.SetForegroundWindow(hwnd)
            return False
        return True

    callback_type = ctypes.WINFUNCTYPE(
        ctypes.c_bool, wintypes.HWND, wintypes.LPARAM
    )
    callback = callback_type(enum_windows_callback)
    user32.EnumWindows(callback, 0)
    return found_window[0]


def _send_potion_key(process_id, key, dry_run):
    if dry_run:
        return True

    if not _is_game_focused(process_id):
        _focus_game_window(process_id)
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline and not _is_game_focused(process_id):
            time.sleep(0.025)

    if not _is_game_focused(process_id):
        print("[WARN] Game window is not focused; skipped the potion keypress.")
        return False

    pressed = False
    try:
        keyboard.press(key)
        pressed = True
        time.sleep(0.01)
        keyboard.release(key)
        pressed = False
        return True
    except Exception as exc:
        print(f"[ERROR] Could not send potion key: {exc}")
        return False
    finally:
        if pressed:
            try:
                keyboard.release(key)
            except Exception:
                pass


def _read_player_state(process, targets):
    max_health = struct.unpack(
        "<d", process.read_bytes(targets["max_health"], 8)
    )[0]
    current_health = struct.unpack(
        "<d", process.read_bytes(targets["health"], 8)
    )[0]
    current_potions = process.read_int(targets["current_potions"])
    max_potions = process.read_int(targets["max_potions"])

    if (
        not math.isfinite(max_health)
        or not math.isfinite(current_health)
        or max_health <= 0
        or max_health > MAX_VALID_VALUE
        or current_health < 0
        or current_health > MAX_VALID_VALUE
    ):
        raise UnrealReflectionError("Health values did not validate")
    if current_potions < 0 or current_potions > 10000:
        current_potions = -1
    if max_potions < 0 or max_potions > 10000:
        max_potions = -1
    return current_health, max_health, current_potions, max_potions


def _monitor_process(process, module_base, args):
    reader = UnrealReflectionReader(process, module_base)
    targets = None
    next_resolve_at = 0.0
    next_liveness_check_at = 0.0
    last_resolution_signature = None
    last_state = None
    last_warning_at = 0.0
    last_potion_attempt_at = 0.0

    print(
        f"[INFO] Monitoring {GAME_PROCESS_NAME}; threshold="
        f"{args.threshold:g}%; potion key={args.key!r}; "
        f"dry_run={args.dry_run}. Press Ctrl+C to stop."
    )

    while True:
        now = time.monotonic()
        if now >= next_liveness_check_at:
            # Detect process exit even while Unreal's world graph is unavailable.
            process.read_bytes(module_base, 1)
            next_liveness_check_at = now + 1.0

        if now >= next_resolve_at:
            try:
                targets = reader.resolve()
                next_resolve_at = now + RESOLVE_INTERVAL_SECONDS
                signature = (
                    targets["world"],
                    targets["controller"],
                    targets["pawn"],
                    targets["potion_manager"],
                )
                if signature != last_resolution_signature:
                    print(
                        "[OK] Resolved local player: "
                        f"{targets['pawn_class']} health + "
                        f"{targets['manager_class']} potion state."
                    )
                    last_resolution_signature = signature
            except Exception as exc:
                targets = None
                next_resolve_at = now + 0.5
                if now - last_warning_at >= 1.0:
                    print(f"[WARN] Waiting for the player graph: {exc}")
                    last_warning_at = now

        if targets is not None:
            try:
                current_health, max_health, potions, max_potions = (
                    _read_player_state(process, targets)
                )
                state = (
                    round(current_health, 1),
                    round(max_health, 1),
                    potions,
                    max_potions,
                )
                if state != last_state:
                    print(
                        f"[STATE] Health {current_health:.1f}/{max_health:.1f} | "
                        f"Potions {potions}/{max_potions}"
                    )
                    last_state = state

                threshold_value = max_health * args.threshold / 100.0
                now = time.monotonic()
                if (
                    potions > 0
                    and current_health < threshold_value
                    and now - last_potion_attempt_at >= POTION_COOLDOWN_SECONDS
                ):
                    if _send_potion_key(process.process_id, args.key, args.dry_run):
                        if args.dry_run:
                            print(
                                f"[DRY RUN] Would use potion at "
                                f"{current_health:.1f}/{max_health:.1f} health; "
                                f"{potions} available."
                            )
                        else:
                            print(
                                f"[ACTION] Potion key sent at "
                                f"{current_health:.1f}/{max_health:.1f} health; "
                                f"{potions} available."
                            )
                    last_potion_attempt_at = now
            except Exception as exc:
                targets = None
                next_resolve_at = 0.0
                if now - last_warning_at >= 1.0:
                    print(f"[WARN] Could not read player state; re-resolving: {exc}")
                    last_warning_at = now

        time.sleep(POLL_INTERVAL_SECONDS)


def main():
    args = parse_args()
    last_missing_message_at = 0.0

    while True:
        process = None
        try:
            process = pymem.Pymem(GAME_PROCESS_NAME)
            module = pymem.process.module_from_name(
                process.process_handle, GAME_PROCESS_NAME
            )
            if module is None:
                raise RuntimeError(f"Could not find module {GAME_PROCESS_NAME}")
            print(f"[OK] Attached to game PID {process.process_id}.")
            _monitor_process(process, module.lpBaseOfDll, args)
        except KeyboardInterrupt:
            print("\n[INFO] Standalone AutoPot stopped.")
            return
        except pymem.exception.ProcessNotFound:
            now = time.monotonic()
            if now - last_missing_message_at >= 5.0:
                print(f"[WAIT] Start {GAME_PROCESS_NAME} to attach.")
                last_missing_message_at = now
            time.sleep(1.0)
        except Exception as exc:
            now = time.monotonic()
            if now - last_missing_message_at >= 1.0:
                print(f"[ERROR] {exc}")
                last_missing_message_at = now
            time.sleep(1.0)
        finally:
            if process is not None:
                try:
                    process.close_process()
                except Exception:
                    pass


if __name__ == "__main__":
    main()
