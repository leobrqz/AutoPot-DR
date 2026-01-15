"""
Main application entry point.
Initializes overlay, process detection, and hotkey handling.
"""
import sys
import os
import threading
import time
import psutil
import ctypes
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QTimer, pyqtSignal, QObject
from PyQt5.QtGui import QIcon
import keyboard

from config import Config
from overlay import OverlayWindow
from memory_reader import MemoryReader

# Game process name
GAME_PROCESS_NAME = "ProjectAlpha-Win64-Shipping.exe"


class ProcessDetector(QObject):
    """Detects if game process is running and emits signals."""
    
    process_status_changed = pyqtSignal(bool, int)  # True if running, False if not, PID
    
    def __init__(self, process_name):
        """
        Initialize process detector.
        
        Args:
            process_name: Name of the process to detect
        """
        super().__init__()
        self.process_name = process_name
        self._running = False
        self._thread = None
        self._last_status = None
        self._last_pid = None
    
    def start(self):
        """Start process detection in background thread."""
        if self._running:
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._detection_loop, daemon=True)
        self._thread.start()
    
    def stop(self):
        """Stop process detection."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)
    
    def _detection_loop(self):
        """Main detection loop running in background thread."""
        while self._running:
            try:
                is_running, pid = self.check_process_running()
                
                # Only emit signal if status changed
                if is_running != self._last_status or (is_running and pid != self._last_pid):
                    self._last_status = is_running
                    self._last_pid = pid
                    self.process_status_changed.emit(is_running, pid)
                
                # Check every 0.5 seconds
                time.sleep(0.5)
            except Exception as e:
                print(f"Error in process detection: {e}")
                time.sleep(1.0)
    
    def check_process_running(self):
        """
        Check if game process is running.
        
        Returns:
            Tuple of (is_running: bool, pid: int)
        """
        try:
            for proc in psutil.process_iter(['name', 'pid']):
                if proc.info['name'] == self.process_name:
                    return (True, proc.info['pid'])
            return (False, 0)
        except Exception:
            return (False, 0)


class HotkeyManager:
    """Manages global hotkeys for the application."""
    
    def __init__(self, overlay, app, config):
        """
        Initialize hotkey manager.
        
        Args:
            overlay: OverlayWindow instance
            app: QApplication instance
            config: Config instance for hotkey settings
        """
        self.overlay = overlay
        self.app = app
        self.config = config
        self._registered = False
    
    def register_hotkeys(self):
        """Register all global hotkeys from config."""
        try:
            lock_key = self.config.get_hotkey_lock()
            toggle_key = self.config.get_hotkey_toggle()
            close_key = self.config.get_hotkey_close()
            
            keyboard.add_hotkey(lock_key, self._toggle_lock)
            keyboard.add_hotkey(toggle_key, self._toggle_enabled)
            keyboard.add_hotkey(close_key, self._close_app)
            
            self._registered = True
        except Exception as e:
            print(f"Error registering hotkeys: {e}")
    
    def get_hotkey_info(self):
        """Get formatted hotkey information for display."""
        lock_key = self.config.get_hotkey_lock().upper()
        toggle_key = self.config.get_hotkey_toggle().upper()
        close_key = self.config.get_hotkey_close().upper()
        
        return [
            f"  {lock_key} - Toggle overlay lock/unlock",
            f"  {toggle_key} - Toggle auto potion on/off",
            f"  {close_key} - Close application"
        ]
    
    def _toggle_lock(self):
        """Toggle overlay lock state."""
        self.overlay.toggle_locked()
        status = "locked" if self.overlay.is_locked() else "unlocked"
        print(f"Overlay {status}")
    
    def _toggle_enabled(self):
        """Toggle enabled/disabled state."""
        self.overlay.toggle_enabled()
        status = "enabled" if self.overlay.is_enabled() else "disabled"
        print(f"Auto potion {status}")
    
    def _close_app(self):
        """Close application."""
        print("Closing application...")
        self.app.quit()


def get_resource_path(relative_path):
    """
    Get absolute path to resource, works for dev and PyInstaller.
    
    Args:
        relative_path: Path relative to project root (e.g., "imgs/icon.ico")
    
    Returns:
        Absolute path to the resource
    """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except AttributeError:
        # Running in development mode
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    return os.path.join(base_path, relative_path)


def main():
    """Main application entry point."""
    # Set Windows AppUserModelID for proper taskbar icon (Windows only)
    # This is critical for Windows to show the correct icon in taskbar
    if sys.platform == 'win32':
        try:
            myappid = 'com.autopot.dr.1.0.0'
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except Exception:
            pass  # Fail silently if not on Windows or if it fails
    
    # Create QApplication
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    
    # Load configuration
    print("Loading configuration...")
    config = Config()
    
    # Create overlay window
    print("Creating overlay window...")
    overlay = OverlayWindow(config)
    overlay.setWindowTitle("AutoPot-DR")
    
    # Set application and window icon (works in .exe, may not work in dev mode)
    # For .exe: PyInstaller embeds icon via --icon flag, this sets it at runtime
    # For dev: Icon may not appear (that's okay per requirements)
    try:
        # Try to load icon from bundled resources (PyInstaller)
        icon_path = get_resource_path("imgs/icon.ico")
        if not os.path.exists(icon_path):
            icon_path = get_resource_path("imgs/icon.png")
        
        if os.path.exists(icon_path):
            icon = QIcon(icon_path)
            app.setWindowIcon(icon)
            overlay.setWindowIcon(icon)
    except Exception:
        # Icon loading failed (expected in dev mode, should work in .exe)
        pass
    
    overlay.show()
    
    # Print searching message
    print(f'Searching process "{GAME_PROCESS_NAME}"...')
    
    # Initialize process detector
    process_detector = ProcessDetector(GAME_PROCESS_NAME)
    
    # Initialize memory reader
    memory_reader = MemoryReader(config, GAME_PROCESS_NAME, potion_key="r")
    
    # Track if we've printed process found message
    process_found_printed = False
    
    # Connect process status to overlay and memory reader with PID handling
    def on_process_status_changed(running, pid):
        nonlocal process_found_printed
        overlay.set_process_running(running)
        memory_reader.set_process_running(running)
        
        # Print process found message once
        if running and not process_found_printed:
            print(f'Process found: "{GAME_PROCESS_NAME}" (PID: {pid})')
            print("Started memory_reader...")
            # Print hotkeys section after process found
            print("-----------")
            print("Hotkeys:")
            for line in hotkey_manager.get_hotkey_info():
                print(line)
            print("-----------")
            process_found_printed = True
    
    process_detector.process_status_changed.connect(on_process_status_changed)
    
    # Connect enabled state changes: when overlay enabled state changes, update memory reader
    # Wrap the overlay's set_enabled_state to also update memory reader
    original_set_enabled = overlay.set_enabled_state
    def set_enabled_wrapper(enabled):
        original_set_enabled(enabled)
        memory_reader.set_enabled(enabled)
    overlay.set_enabled_state = set_enabled_wrapper
    
    # Set initial enabled state for memory reader
    memory_reader.set_enabled(overlay.is_enabled())
    
    # Connect potion usage signal to overlay
    memory_reader.potion_used.connect(overlay.add_potion_log_entry)
    
    # Connect max health signal to overlay
    memory_reader.max_health_updated.connect(overlay.set_max_health)
    
    # Connect current health signal to overlay
    memory_reader.current_health_updated.connect(overlay.set_current_health)
    
    # Start process detection
    process_detector.start()
    
    # Register hotkeys
    hotkey_manager = HotkeyManager(overlay, app, config)
    hotkey_manager.register_hotkeys()
    
    # Start memory reader
    memory_reader.start()
    
    # Initial process check
    initial_status, initial_pid = process_detector.check_process_running()
    if initial_status:
        on_process_status_changed(initial_status, initial_pid)
    else:
        overlay.set_process_running(False)
        memory_reader.set_process_running(False)
    
    # Run application
    try:
        sys.exit(app.exec_())
    except KeyboardInterrupt:
        print("Application interrupted")
    finally:
        # Cleanup
        process_detector.stop()
        memory_reader.stop()
        print("Application closed")


if __name__ == "__main__":
    main()
