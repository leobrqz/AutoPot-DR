"""
Memory reading and potion logic module.
Reads game memory and automatically uses potions when health falls below threshold.
"""
import time
import threading
import struct
import math
import sys
import ctypes
from ctypes import wintypes
from datetime import datetime
import pymem
import pymem.process
import keyboard
from PyQt5.QtCore import QObject, pyqtSignal
from unreal_reader import UnrealReflectionError, UnrealReflectionReader


# ============================================================================
# Windows API Functions for Window Focus
# ============================================================================

if sys.platform == 'win32':
    # Windows API constants
    SW_RESTORE = 9
    SW_SHOW = 5
    
    # Windows API functions
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    
    def get_foreground_window():
        """Get the handle of the foreground window."""
        return user32.GetForegroundWindow()
    
    def get_window_thread_process_id(hwnd):
        """Get the process ID of the window."""
        process_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        return process_id.value
    
    def is_process_window_focused(process_id):
        """Check if the given process window is focused."""
        try:
            hwnd = get_foreground_window()
            if hwnd:
                focused_pid = get_window_thread_process_id(hwnd)
                return focused_pid == process_id
        except Exception:
            pass
        return False
    
    def focus_process_window(process_id):
        """Try to focus the window of the given process."""
        try:
            # EnumWindows callback
            def enum_windows_callback(hwnd, lParam):
                if get_window_thread_process_id(hwnd) == process_id:
                    # Found the window, try to focus it
                    user32.ShowWindow(hwnd, SW_RESTORE)
                    user32.SetForegroundWindow(hwnd)
                    return False  # Stop enumeration
                return True  # Continue enumeration
            
            # Define callback type
            EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
            callback = EnumWindowsProc(enum_windows_callback)
            
            # Enumerate all windows
            user32.EnumWindows(callback, 0)
        except Exception:
            pass
else:
    # Non-Windows platforms (placeholder)
    def is_process_window_focused(process_id):
        return True
    
    def focus_process_window(process_id):
        pass

# ============================================================================
# Base Memory Reading Functions
# ============================================================================

def get_module_base_address(pm, process_name):
    """
    Get module base address for the process.
    
    Args:
        pm: Pymem instance
        process_name: Name of the process/module
    
    Returns:
        Module base address (int) or None on error
    """
    try:
        module = pymem.process.module_from_name(pm.process_handle, process_name)
        return module.lpBaseOfDll
    except Exception:
        return None




# ============================================================================
# Memory Reader Worker
# ============================================================================

class MemoryReader(QObject):
    """Reads game memory and triggers potion usage."""
    
    # Signal emitted when potion is used
    potion_used = pyqtSignal(float, float)  # health_amount, percentage
    # Signal emitted when max health is read
    max_health_updated = pyqtSignal(float)  # max_health value
    # Signal emitted when current health is read
    current_health_updated = pyqtSignal(float)  # current_health value
    # Signals emitted when the player's energy (the game's mana-like resource) is read
    max_energy_updated = pyqtSignal(float)  # max_energy value
    current_energy_updated = pyqtSignal(float)  # current_energy value
    # Signal emitted when process is successfully attached
    process_attached = pyqtSignal()
    # Signal emitted when process death is detected
    process_died = pyqtSignal()
    # Signal emitted when potion count is read (-1 for read failure)
    potion_count_updated = pyqtSignal(int)
    # Signal emitted when maximum potion capacity is read (-1 for read failure)
    max_potion_count_updated = pyqtSignal(int)
    
    def __init__(self, config, process_name, potion_key="r"):
        """
        Initialize memory reader.
        
        Args:
            config: Config instance for settings
            process_name: Name of the game process
            potion_key: Key to press for potion (default "r")
        """
        super().__init__()
        self.config = config
        self.process_name = process_name
        self.potion_key = potion_key
        self._running = False
        self._thread = None
        self._pm = None
        self._last_potion_time = 0.0
        self._potion_cooldown = 0.5  # 500ms cooldown between potion drinks
        self._enabled = True
        self._process_running = False
        self._module_base = None
        self._process_id = None
        self._unreal_reader = None
        self._unreal_targets = None
        self._next_unreal_resolution = 0.0
        self._last_unreal_resolution = None
        self._last_energy_debug_signature = None
        self._attachment_notified = False  # Track if we've notified about current attachment
        self._last_error_print_time = 0.0
        self._error_print_cooldown = 1.0  # 1 second cooldown for error prints
    
    # Constants
    MEMORY_READ_INTERVAL = 0.01  # 10ms interval for memory reading loop
    
    def set_enabled(self, enabled: bool):
        """Set enabled state (pauses memory reading when False)."""
        self._enabled = enabled
    
    def set_process_running(self, running: bool):
        """Set process running state."""
        self._process_running = running
        if not running:
            self._close_process()
            self._module_base = None
            self._process_id = None
            self._unreal_targets = None
            self._next_unreal_resolution = 0.0
            self._last_unreal_resolution = None
            self._attachment_notified = False  # Reset so we can notify again on next attachment
    
    def start(self):
        """Start memory reading in background thread."""
        if self._running:
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._reading_loop, daemon=True)
        self._thread.start()
    
    def stop(self):
        """Stop memory reading."""
        self._running = False
        self._close_process()
        if self._thread:
            self._thread.join(timeout=1.0)
    
    def _close_process(self):
        """Close pymem process handle."""
        if self._pm is not None:
            try:
                self._pm.close_process()
            except Exception:
                pass
            self._pm = None
        self._unreal_reader = None
        self._unreal_targets = None
        self._next_unreal_resolution = 0.0
        self._last_unreal_resolution = None
        self._last_energy_debug_signature = None
    
    def _handle_process_death(self):
        """Handle process death - cleanup state and emit signal."""
        self._close_process()
        self._module_base = None
        self._process_id = None
        self._last_unreal_resolution = None
        self._attachment_notified = False
        if self._process_running:
            self.process_died.emit()
            self._process_running = False
    
    def _attach_to_process(self) -> bool:
        """Attach to game process using pymem."""
        try:
            if self._pm is not None:
                # Already attached, verify process is still alive by checking process handle
                try:
                    # Try to read a small amount of memory to verify process is still alive
                    # This will raise ProcessNotFound if process died
                    _ = self._pm.read_bytes(self._module_base, 1)
                    # Process is still alive, just ensure process ID is cached
                    if self._process_id is None:
                        self._process_id = self._pm.process_id
                    return True
                except (pymem.exception.ProcessNotFound, pymem.exception.MemoryReadError):
                    # Process died - cleanup and signal
                    self._handle_process_death()
                    return False
            
            # Not attached yet, try to attach
            self._pm = pymem.Pymem(self.process_name)
            self._process_id = self._pm.process_id
            
            self._module_base = get_module_base_address(self._pm, self.process_name)
            if self._module_base is None:
                self._close_process()
                return False

            self._unreal_reader = UnrealReflectionReader(self._pm, self._module_base)
            
            # Successfully attached - emit signal only once per attachment session
            if not self._attachment_notified:
                self.process_attached.emit()
                self._attachment_notified = True
            return True
        except pymem.exception.ProcessNotFound:
            # Process not found by name - this is the only true "process death" indicator
            self._handle_process_death()
            return False
        except Exception as e:
            now = time.time()
            if now - self._last_error_print_time >= self._error_print_cooldown:
                print(f"Unable to initialize Unreal reflection reader: {e}")
                self._last_error_print_time = now
            self._close_process()
            return False
    
    def _resolve_unreal_targets(self):
        """Refresh object/property addresses from live Unreal reflection."""
        now = time.monotonic()
        if now < self._next_unreal_resolution:
            return self._unreal_targets
        self._next_unreal_resolution = now + 0.25

        if self._unreal_reader is None:
            self._unreal_targets = None
            return None

        try:
            targets = self._unreal_reader.resolve()
            self._unreal_targets = targets
            signature = (
                targets["world"],
                targets["controller"],
                targets["pawn"],
                targets["potion_manager"],
            )
            if signature != self._last_unreal_resolution:
                print(
                    "[OK] Unreal reflection resolved: "
                    f"{targets['pawn_class']} health + "
                    "energy + "
                    f"{targets['manager_class']} potion state"
                )
                self._last_unreal_resolution = signature
            return targets
        except Exception as exc:
            self._unreal_targets = None
            error_time = time.time()
            if error_time - self._last_error_print_time >= self._error_print_cooldown:
                print(f"[ERROR] Unreal reflection discovery failed: {exc}")
                self._last_error_print_time = error_time
            return None

    def _read_game_state(self):
        """Read health, energy, and potion values from reflected fields."""
        targets = self._resolve_unreal_targets()
        if targets is None or self._pm is None:
            return 0.0, -1.0, 0.0, -1.0, -1, -1

        try:
            max_health = struct.unpack(
                "<d", self._pm.read_bytes(targets["max_health"], 8)
            )[0]
            current_health = struct.unpack(
                "<d", self._pm.read_bytes(targets["health"], 8)
            )[0]
            energy_available = (
                targets.get("energy") is not None
                and targets.get("max_energy") is not None
            )
            if energy_available:
                try:
                    max_energy = struct.unpack(
                        "<d", self._pm.read_bytes(targets["max_energy"], 8)
                    )[0]
                    current_energy = struct.unpack(
                        "<d", self._pm.read_bytes(targets["energy"], 8)
                    )[0]
                    if (
                        not math.isfinite(max_energy)
                        or not math.isfinite(current_energy)
                        or max_energy <= 0
                        or max_energy > 100000000
                        or current_energy < 0
                        or current_energy > 100000000
                    ):
                        raise UnrealReflectionError("Energy values did not validate")
                except Exception as exc:
                    energy_available = False
                    error_time = time.time()
                    if error_time - self._last_error_print_time >= self._error_print_cooldown:
                        print(f"[WARN] Could not read optional Energy values: {exc}")
                        self._last_error_print_time = error_time
                    max_energy = 0.0
                    current_energy = -1.0
            else:
                max_energy = 0.0
                current_energy = -1.0
            current_potions = self._pm.read_int(targets["current_potions"])
            max_potions = self._pm.read_int(targets["max_potions"])

            if (
                not math.isfinite(max_health)
                or not math.isfinite(current_health)
                or max_health <= 0
                or max_health > 100000000
                or current_health < 0
                or current_health > 100000000
            ):
                raise UnrealReflectionError("Health values did not validate")
            if current_potions < 0 or current_potions > 10000:
                current_potions = -1
            if max_potions < 0 or max_potions > 10000:
                max_potions = -1

            energy_signature = (
                targets["pawn"], targets["energy"], targets["max_energy"]
            ) if energy_available else None
            if (
                energy_available
                and energy_signature != self._last_energy_debug_signature
            ):
                print(
                    "[RESULT] Player Energy/Mana: "
                    f"{current_energy:g} / {max_energy:g} "
                    "(reflected Energy / MaxEnergy)"
                )
                self._last_energy_debug_signature = energy_signature

            return (
                max_health,
                current_health,
                max_energy,
                current_energy,
                current_potions,
                max_potions,
            )
        except Exception as exc:
            # Force a fresh object walk on the next read after a map or pawn change.
            self._unreal_targets = None
            self._next_unreal_resolution = 0.0
            error_time = time.time()
            if error_time - self._last_error_print_time >= self._error_print_cooldown:
                print(f"[ERROR] Could not read reflected player state: {exc}")
                self._last_error_print_time = error_time
            return 0.0, -1.0, 0.0, -1.0, -1, -1

    def _use_potion(self):
        """Send potion keypress. Ensures game window is focused first."""
        try:
            # On Windows, ensure the game window is focused before sending key
            if sys.platform == 'win32' and self._process_id is not None:
                if not is_process_window_focused(self._process_id):
                    # Try to focus the game window
                    focus_process_window(self._process_id)
                    # Small delay to allow window to focus
                    time.sleep(0.02)
            
            # Send the key using press and release separately for better game compatibility
            # This mimics actual key press more accurately
            keyboard.press(self.potion_key)
            time.sleep(0.01)  # Small delay between press and release
            keyboard.release(self.potion_key)
        except Exception as e:
            print(f"Error sending potion keypress: {e}")
    
    def _reading_loop(self):
        """Main memory reading loop running in background thread."""
        while self._running:
            try:
                # Only read if process is running and enabled
                if not self._process_running or not self._enabled:
                    time.sleep(self.MEMORY_READ_INTERVAL)
                    continue
                
                # Attach to process if not already attached
                if not self._attach_to_process():
                    time.sleep(0.5)
                    continue
                
                # Resolve the object graph once, then read current values from
                # reflected health and potion properties.
                (
                    max_health,
                    current_health,
                    max_energy,
                    current_energy,
                    potion_count,
                    max_potions,
                ) = self._read_game_state()
                self.max_health_updated.emit(max_health)
                self.current_health_updated.emit(current_health)
                self.max_energy_updated.emit(max_energy)
                self.current_energy_updated.emit(current_energy)
                self.potion_count_updated.emit(potion_count)
                self.max_potion_count_updated.emit(max_potions)
                
                # Potion logic
                if max_health > 0 and current_health >= 0 and potion_count > 0:
                    threshold_percentage = self.config.get_health_threshold()
                    threshold_value = (max_health * threshold_percentage) / 100.0
                    current_time = time.time()
                    time_since_last_potion = current_time - self._last_potion_time
                    
                    # Check if health is below threshold and player has potions
                    if current_health < threshold_value:
                        # Potion logic: wait 500ms between potion drinks
                        if time_since_last_potion >= self._potion_cooldown:
                            self._use_potion()
                            self._last_potion_time = current_time
                            
                            # Calculate percentage for log
                            health_percentage = (current_health / max_health) * 100.0
                            self.potion_used.emit(current_health, health_percentage)
                            
                            # Print to console with same format as overlay
                            timestamp = datetime.now().strftime("%H:%M:%S")
                            health_amount = int(current_health)
                            remaining = potion_count - 1
                            print(f"[LOG] {timestamp} - {health_amount} - {health_percentage:.1f}% - {remaining} potions remaining")
                
                # Check every 10ms
                time.sleep(self.MEMORY_READ_INTERVAL)
                
            except (pymem.exception.ProcessNotFound, pymem.exception.MemoryReadError) as e:
                # Process-related errors - handled in _attach_to_process, just wait and retry
                time.sleep(0.5)
            except Exception as e:
                # Other unexpected errors - log but don't treat as process death
                current_time = time.time()
                if current_time - self._last_error_print_time >= self._error_print_cooldown:
                    print(f"Unexpected error in memory reading loop: {e}")
                    self._last_error_print_time = current_time
                time.sleep(0.5)
