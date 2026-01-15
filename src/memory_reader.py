"""
Memory reading and potion logic module.
Reads game memory and automatically uses potions when health falls below threshold.
"""
import time
import threading
import struct
import sys
import ctypes
from ctypes import wintypes
import pymem
import pymem.process
import keyboard
from PyQt5.QtCore import QObject, pyqtSignal


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

def read_pointer_chain(pm, base_address, offsets):
    """
    Resolves a multi-level pointer chain and returns the final address.
    
    Args:
        pm: Pymem instance
        base_address: Starting address (int)
        offsets: List of offsets (list of int)
    
    Returns:
        Final address after following pointer chain
    """
    addr = base_address
    
    for i, offset in enumerate(offsets):
        try:
            # Read pointer (8 bytes because it's a 64-bit process)
            addr = pm.read_ulonglong(addr)
        except pymem.exception.MemoryReadError:
            raise RuntimeError(f"Failed to read pointer at level {i} (address: {hex(addr)})")
        
        addr += offset
    
    return addr


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


def parse_address(address_str: str) -> int:
    """
    Parse address string to integer.
    
    Args:
        address_str: Address as string (e.g., "0x12345" or "0x00000")
    
    Returns:
        Integer address value
    """
    try:
        if address_str.startswith("0x") or address_str.startswith("0X"):
            return int(address_str, 16)
        return int(address_str)
    except (ValueError, AttributeError):
        return 0


def parse_offsets(offsets_str: str) -> list:
    """
    Parse comma-separated hex offsets string to list of integers.
    
    Args:
        offsets_str: Comma-separated hex offsets (e.g., "0x28,0x530,0x10")
    
    Returns:
        List of integer offsets
    """
    offsets = []
    try:
        for offset_str in offsets_str.split(','):
            offset_str = offset_str.strip()
            if offset_str.startswith("0x") or offset_str.startswith("0X"):
                offsets.append(int(offset_str, 16))
            else:
                offsets.append(int(offset_str))
    except (ValueError, AttributeError):
        pass
    return offsets


def read_memory_float(pm, address: int) -> float:
    """Read float value from memory address."""
    try:
        if address == 0:
            return 0.0
        return pm.read_float(address)
    except Exception:
        return 0.0


def read_memory_double(pm, address: int) -> float:
    """Read double value from memory address."""
    try:
        if address == 0:
            return 0.0
        raw = pm.read_bytes(address, 8)
        return struct.unpack("<d", raw)[0]
    except Exception:
        return 0.0


def read_memory_int(pm, address: int) -> int:
    """Read integer value from memory address."""
    try:
        if address == 0:
            return 0
        return pm.read_int(address)
    except Exception:
        return 0


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
        self._max_health_initialized = False
        self._current_health_initialized = False
        self._last_max_health = 0.0
        self._last_current_health = 0.0
        self._process_id = None
    
    def set_enabled(self, enabled: bool):
        """Set enabled state (pauses memory reading when False)."""
        self._enabled = enabled
    
    def set_process_running(self, running: bool):
        """Set process running state."""
        self._process_running = running
        if not running:
            self._close_process()
            self._module_base = None
            self._max_health_initialized = False
            self._current_health_initialized = False
            self._process_id = None
    
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
    
    def _attach_to_process(self) -> bool:
        """Attach to game process using pymem."""
        try:
            if self._pm is not None:
                # Get module base if not already cached
                if self._module_base is None:
                    self._module_base = get_module_base_address(self._pm, self.process_name)
                # Update process ID if not set
                if self._process_id is None:
                    self._process_id = self._pm.process_id
                return True
            
            self._pm = pymem.Pymem(self.process_name)
            self._process_id = self._pm.process_id
            
            self._module_base = get_module_base_address(self._pm, self.process_name)
            if self._module_base is None:
                return False
            
            return True
        except pymem.exception.ProcessNotFound:
            self._pm = None
            self._module_base = None
            self._process_id = None
            return False
        except Exception as e:
            self._pm = None
            self._module_base = None
            self._process_id = None
            return False
    
    def _initialize_max_health_pointer(self):
        """
        Initialize and print max health pointer debug information once.
        This method prints all debug info when first successfully reading max health.
        """
        if self._max_health_initialized:
            return
        
        try:
            if self._pm is None or self._module_base is None:
                return
            
            print("Max_health pointer:")
            print(f"[OK] Module base address: {hex(self._module_base)}")
            
            # Get base offset and offsets from config
            base_offset_str = self.config.get_max_health_base_offset()
            offsets_str = self.config.get_max_health_offsets()
            
            # Parse base offset
            base_offset = parse_address(base_offset_str)
            if base_offset == 0:
                print("[ERROR] Invalid max health base offset")
                return
            
            # Parse offsets list
            offsets = parse_offsets(offsets_str)
            if not offsets:
                print("[ERROR] Invalid max health offsets")
                return
            
            # Calculate base address (module_base + base_offset)
            base_address = self._module_base + base_offset
            print(f"[OK] Base pointer address: {hex(base_address)}")
            
            # Follow pointer chain
            try:
                final_address = read_pointer_chain(self._pm, base_address, offsets)
                print(f"[OK] Final address: {hex(final_address)}")
            except RuntimeError as e:
                print(f"[ERROR] {e}")
                return
            
            # Read double value (8 bytes)
            try:
                max_health = read_memory_double(self._pm, final_address)
                if max_health > 0:
                    print(f"[RESULT] Player Max Health: {max_health}")
                    self._max_health_initialized = True
                    print("-------------")
            except Exception as e:
                print(f"[ERROR] Failed to read final double value: {e}")
                
        except Exception as e:
            print(f"[ERROR] Error initializing max health pointer: {e}")
    
    def _read_max_health(self) -> float:
        """
        Read max health using pointer chain.
        
        Returns:
            Max health value (float) or 0.0 on error
        """
        try:
            if self._pm is None or self._module_base is None:
                return 0.0
            
            # Initialize debug output once
            if not self._max_health_initialized:
                self._initialize_max_health_pointer()
            
            # Get base offset and offsets from config
            base_offset_str = self.config.get_max_health_base_offset()
            offsets_str = self.config.get_max_health_offsets()
            
            # Parse base offset
            base_offset = parse_address(base_offset_str)
            if base_offset == 0:
                return 0.0
            
            # Parse offsets list
            offsets = parse_offsets(offsets_str)
            if not offsets:
                return 0.0
            
            # Calculate base address (module_base + base_offset)
            base_address = self._module_base + base_offset
            
            # Follow pointer chain
            final_address = read_pointer_chain(self._pm, base_address, offsets)
            
            # Read double value (8 bytes)
            max_health = read_memory_double(self._pm, final_address)
            
            return max_health
        except Exception as e:
            if not self._max_health_initialized:
                print(f"[ERROR] Error reading max health: {e}")
            return 0.0
    
    def _initialize_current_health_pointer(self):
        """
        Initialize and print current health pointer debug information once.
        This method prints all debug info when first successfully reading current health.
        """
        if self._current_health_initialized:
            return
        
        try:
            if self._pm is None or self._module_base is None:
                return
            
            print("Current_health pointer:")
            print(f"[OK] Module base address: {hex(self._module_base)}")
            
            # Get base offset and offsets from config
            base_offset_str = self.config.get_current_health_base_offset()
            offsets_str = self.config.get_current_health_offsets()
            
            # Parse base offset
            base_offset = parse_address(base_offset_str)
            if base_offset == 0:
                print("[ERROR] Invalid current health base offset")
                return
            
            # Parse offsets list
            offsets = parse_offsets(offsets_str)
            if not offsets:
                print("[ERROR] Invalid current health offsets")
                return
            
            # Calculate base address (module_base + base_offset)
            base_address = self._module_base + base_offset
            print(f"[OK] Base pointer address: {hex(base_address)}")
            
            # Follow pointer chain
            try:
                final_address = read_pointer_chain(self._pm, base_address, offsets)
                print(f"[OK] Final address: {hex(final_address)}")
            except RuntimeError as e:
                print(f"[ERROR] {e}")
                return
            
            # Read double value (8 bytes)
            try:
                current_health = read_memory_double(self._pm, final_address)
                if current_health >= 0:  # Allow 0.0 as valid value
                    print(f"[RESULT] Player Current Health: {current_health}")
                    self._current_health_initialized = True
                    print("--------------")
            except Exception as e:
                print(f"[ERROR] Failed to read final double value: {e}")
                
        except Exception as e:
            print(f"[ERROR] Error initializing current health pointer: {e}")
    
    def _read_current_health(self) -> float:
        """
        Read current health using pointer chain.
        
        Returns:
            Current health value (float) or 0.0 on error
        """
        try:
            if self._pm is None or self._module_base is None:
                return 0.0
            
            # Initialize debug output once
            if not self._current_health_initialized:
                self._initialize_current_health_pointer()
            
            # Get base offset and offsets from config
            base_offset_str = self.config.get_current_health_base_offset()
            offsets_str = self.config.get_current_health_offsets()
            
            # Parse base offset
            base_offset = parse_address(base_offset_str)
            if base_offset == 0:
                return 0.0
            
            # Parse offsets list
            offsets = parse_offsets(offsets_str)
            if not offsets:
                return 0.0
            
            # Calculate base address (module_base + base_offset)
            base_address = self._module_base + base_offset
            
            # Follow pointer chain
            final_address = read_pointer_chain(self._pm, base_address, offsets)
            
            # Read double value (8 bytes)
            current_health = read_memory_double(self._pm, final_address)
            
            return current_health
        except Exception as e:
            if not self._current_health_initialized:
                print(f"[ERROR] Error reading current health: {e}")
            return 0.0
    
    def _read_potion_count(self) -> int:
        """
        Placeholder for reading potion count.
        Currently returns 0 and does not affect the program.
        
        Returns:
            Potion count (int)
        """
        # Placeholder - not implemented yet
        return 0
    
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
                    time.sleep(0.01)
                    continue
                
                # Attach to process if not already attached
                if not self._attach_to_process():
                    time.sleep(0.5)
                    continue
                
                # Read max health using pointer chain
                max_health = self._read_max_health()
                if max_health > 0:
                    self._last_max_health = max_health
                    # Emit signal for overlay to update display
                    self.max_health_updated.emit(max_health)
                
                # Read current health using pointer chain
                current_health = self._read_current_health()
                if current_health >= 0:  # Allow 0.0 as valid value
                    self._last_current_health = current_health
                    # Emit signal for overlay to update display
                    self.current_health_updated.emit(current_health)
                
                # Potion logic
                if max_health > 0 and current_health >= 0:
                    threshold_percentage = self.config.get_health_threshold()
                    threshold_value = (max_health * threshold_percentage) / 100.0
                    current_time = time.time()
                    time_since_last_potion = current_time - self._last_potion_time
                    
                    # Check if health is below threshold
                    if current_health < threshold_value:
                        # Potion logic: wait 500ms between potion drinks
                        if time_since_last_potion >= self._potion_cooldown:
                            self._use_potion()
                            self._last_potion_time = current_time
                            
                            # Calculate percentage for log
                            health_percentage = (current_health / max_health) * 100.0
                            self.potion_used.emit(current_health, health_percentage)
                
                # Check every 10ms
                time.sleep(0.01)
                
            except Exception as e:
                print(f"Error in memory reading loop: {e}")
                self._close_process()
                self._module_base = None
                time.sleep(0.5)
