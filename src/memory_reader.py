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
from datetime import datetime
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

def read_pointer_chain(pm, base_address, offsets, return_chain=False):
    """
    Resolves a multi-level pointer chain and returns the final address.
    
    Args:
        pm: Pymem instance
        base_address: Starting address (int)
        offsets: List of offsets (list of int)
        return_chain: If True, returns tuple (final_address, chain_addresses)
    
    Returns:
        Final address after following pointer chain, or tuple (final_address, chain_addresses) if return_chain=True
    """
    addr = base_address
    chain_addresses = [base_address]  # Start with base address
    
    for i, offset in enumerate(offsets):
        try:
            # Read pointer (8 bytes because it's a 64-bit process)
            addr = pm.read_ulonglong(addr)
            if addr == 0:
                raise RuntimeError(f"Read null pointer at level {i} (address: {hex(chain_addresses[-1])})")
            if addr < 4096 and i < len(offsets) - 1:
                raise RuntimeError(f"Address too low ({hex(addr)}) at level {i}")
        except pymem.exception.MemoryReadError as e:
            raise RuntimeError(f"Failed to read pointer at level {i} (address: {hex(chain_addresses[-1])}): {e}")
        
        addr += offset
        chain_addresses.append(addr)
    
    if return_chain:
        return addr, chain_addresses
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
    # Signal emitted when process is successfully attached
    process_attached = pyqtSignal()
    # Signal emitted when process death is detected
    process_died = pyqtSignal()
    # Signal emitted when potion count is read (-1 for read failure)
    potion_count_updated = pyqtSignal(int)
    
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
        self._last_max_health_chain = None
        self._last_current_health_chain = None
        self._potion_count_initialized = False
        self._last_potion_chain = None
        self._attachment_notified = False  # Track if we've notified about current attachment
        self._last_chain_resolution_attempt = 0.0
        self._chain_resolution_cooldown = 1.0  # 1 second cooldown for chain resolution
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
            self._max_health_initialized = False
            self._current_health_initialized = False
            self._potion_count_initialized = False
            self._process_id = None
            self._last_max_health_chain = None
            self._last_current_health_chain = None
            self._last_potion_chain = None
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
    
    def _handle_process_death(self):
        """Handle process death - cleanup state and emit signal."""
        self._close_process()
        self._module_base = None
        self._max_health_initialized = False
        self._current_health_initialized = False
        self._potion_count_initialized = False
        self._process_id = None
        self._last_max_health_chain = None
        self._last_current_health_chain = None
        self._last_potion_chain = None
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
                    _ = self._pm.read_bytes(self._pm.process_base, 1)
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
            self._close_process()
            return False
    
    def _initialize_max_health_pointer(self):
        """
        Initialize and print max health pointer debug information once.
        This method prints all debug info when first successfully reading max health.
        """
        if self._max_health_initialized:
            return
        
        # Throttle chain resolution attempts to once per second
        current_time = time.time()
        if current_time - self._last_chain_resolution_attempt < self._chain_resolution_cooldown:
            return  # Skip this attempt, wait for cooldown
        self._last_chain_resolution_attempt = current_time
        
        try:
            if self._pm is None or self._module_base is None:
                return
            
            print("Max_health pointer:")
            print(f"[OK] Module: {self.process_name} | Base address: {hex(self._module_base)}")
            
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
            
            # Follow pointer chain
            try:
                final_address, chain_addresses = read_pointer_chain(self._pm, base_address, offsets, return_chain=True)
                
                # Check if pointer chain path changed (excluding final address)
                current_pointer_path = tuple(chain_addresses[:-1])
                if self._last_max_health_chain != current_pointer_path:
                    print("[DEBUG] Max health pointer chain resolved:")
                    print(f"  Step 0: addr=0x{chain_addresses[0]:X}")
                    for i, (addr, offset) in enumerate(zip(chain_addresses[1:], offsets), 1):
                        print(f"  Step {i}: addr=0x{addr:X} offset=0x{offset:X}")
                    self._last_max_health_chain = current_pointer_path
                
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
        except RuntimeError:
            # Null pointer or invalid address - expected when pointer chain changes (e.g., moving areas)
            # Silently ignore and return 0.0 - don't treat as process death
            return 0.0
        except Exception as e:
            # Other errors - only print during initialization to avoid spam
            if not self._max_health_initialized:
                current_time = time.time()
                if current_time - self._last_error_print_time >= self._error_print_cooldown:
                    print(f"[ERROR] Error reading max health: {e}")
                    self._last_error_print_time = current_time
            return 0.0
    
    def _initialize_current_health_pointer(self):
        """
        Initialize and print current health pointer debug information once.
        This method prints all debug info when first successfully reading current health.
        """
        if self._current_health_initialized:
            return
        
        # Throttle chain resolution attempts to once per second
        current_time = time.time()
        if current_time - self._last_chain_resolution_attempt < self._chain_resolution_cooldown:
            return  # Skip this attempt, wait for cooldown
        self._last_chain_resolution_attempt = current_time
        
        try:
            if self._pm is None or self._module_base is None:
                return
            
            print("Current_health pointer:")
            print(f"[OK] Module: {self.process_name} | Base address: {hex(self._module_base)}")
            
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
            
            # Follow pointer chain
            try:
                final_address, chain_addresses = read_pointer_chain(self._pm, base_address, offsets, return_chain=True)
                
                # Check if pointer chain path changed (excluding final address)
                current_pointer_path = tuple(chain_addresses[:-1])
                if self._last_current_health_chain != current_pointer_path:
                    print("[DEBUG] Current health pointer chain resolved:")
                    print(f"  Step 0: addr=0x{chain_addresses[0]:X}")
                    for i, (addr, offset) in enumerate(zip(chain_addresses[1:], offsets), 1):
                        print(f"  Step {i}: addr=0x{addr:X} offset=0x{offset:X}")
                    self._last_current_health_chain = current_pointer_path
                
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
    
    def _initialize_potion_pointer(self):
        """
        Initialize and print potion pointer debug information once.
        Prints all debug info when first successfully reading potion count.
        """
        if self._potion_count_initialized:
            return
        
        current_time = time.time()
        if current_time - self._last_chain_resolution_attempt < self._chain_resolution_cooldown:
            return
        self._last_chain_resolution_attempt = current_time
        
        try:
            if self._pm is None or self._module_base is None:
                return
            
            print("Potion pointer:")
            print(f"[OK] Module: {self.process_name} | Base address: {hex(self._module_base)}")
            
            base_offset_str = self.config.get_potion_base_offset()
            offsets_str = self.config.get_potion_offsets()
            
            base_offset = parse_address(base_offset_str)
            if base_offset == 0:
                print("[ERROR] Invalid potion base offset")
                return
            
            offsets = parse_offsets(offsets_str)
            if not offsets:
                print("[ERROR] Invalid potion offsets")
                return
            
            base_address = self._module_base + base_offset
            
            try:
                final_address, chain_addresses = read_pointer_chain(self._pm, base_address, offsets, return_chain=True)
                
                current_pointer_path = tuple(chain_addresses[:-1])
                if self._last_potion_chain != current_pointer_path:
                    print("[DEBUG] Potion pointer chain resolved:")
                    print(f"  Step 0: addr=0x{chain_addresses[0]:X}")
                    for i, (addr, offset) in enumerate(zip(chain_addresses[1:], offsets), 1):
                        print(f"  Step {i}: addr=0x{addr:X} offset=0x{offset:X}")
                    self._last_potion_chain = current_pointer_path
                
                print(f"[OK] Final address: {hex(final_address)}")
            except RuntimeError as e:
                print(f"[ERROR] {e}")
                return
            
            try:
                potion_count = read_memory_int(self._pm, final_address)
                if potion_count >= 0:
                    print(f"[RESULT] Player Potion Count: {potion_count}")
                    self._potion_count_initialized = True
                    print("-------------")
            except Exception as e:
                print(f"[ERROR] Failed to read final int value: {e}")
                
        except Exception as e:
            print(f"[ERROR] Error initializing potion pointer: {e}")
    
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
        except RuntimeError:
            # Null pointer or invalid address - expected when pointer chain changes (e.g., moving areas)
            # Silently ignore and return 0.0 - don't treat as process death
            return 0.0
        except Exception as e:
            # Other errors - only print during initialization to avoid spam
            if not self._current_health_initialized:
                current_time = time.time()
                if current_time - self._last_error_print_time >= self._error_print_cooldown:
                    print(f"[ERROR] Error reading current health: {e}")
                    self._last_error_print_time = current_time
            return 0.0
    
    def _read_potion_count(self) -> int:
        """
        Read potion count using pointer chain.
        
        Returns:
            Potion count (int >= 0) on success, -1 on read failure
        """
        try:
            if self._pm is None or self._module_base is None:
                return -1
            
            if not self._potion_count_initialized:
                self._initialize_potion_pointer()
            
            base_offset_str = self.config.get_potion_base_offset()
            offsets_str = self.config.get_potion_offsets()
            
            base_offset = parse_address(base_offset_str)
            if base_offset == 0:
                return -1
            
            offsets = parse_offsets(offsets_str)
            if not offsets:
                return -1
            
            base_address = self._module_base + base_offset
            
            final_address = read_pointer_chain(self._pm, base_address, offsets)
            
            potion_count = read_memory_int(self._pm, final_address)
            if potion_count < 0:
                return -1
            return potion_count
        except RuntimeError:
            return -1
        except Exception as e:
            if not self._potion_count_initialized:
                current_time = time.time()
                if current_time - self._last_error_print_time >= self._error_print_cooldown:
                    print(f"[ERROR] Error reading potion count: {e}")
                    self._last_error_print_time = current_time
            return -1
    
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
                
                # Read potion count using pointer chain
                potion_count = self._read_potion_count()
                self.potion_count_updated.emit(potion_count)
                
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
