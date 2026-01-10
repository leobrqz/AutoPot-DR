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


# Game process name
GAME_PROCESS_NAME = "ProjectAlpha-Win64-Shipping.exe"


class ProcessDetector(QObject):
    """Detects if game process is running and emits signals."""
    
    process_status_changed = pyqtSignal(bool)  # True if running, False if not
    
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
                is_running = self.check_process_running()
                
                # Only emit signal if status changed
                if is_running != self._last_status:
                    self._last_status = is_running
                    self.process_status_changed.emit(is_running)
                
                # Check every 0.5 seconds
                time.sleep(0.5)
            except Exception as e:
                print(f"Error in process detection: {e}")
                time.sleep(1.0)
    
    def check_process_running(self) -> bool:
        """Check if game process is running."""
        try:
            for proc in psutil.process_iter(['name']):
                if proc.info['name'] == self.process_name:
                    return True
            return False
        except Exception:
            return False


class HotkeyManager:
    """Manages global hotkeys for the application."""
    
    def __init__(self, overlay, app):
        """
        Initialize hotkey manager.
        
        Args:
            overlay: OverlayWindow instance
            app: QApplication instance
        """
        self.overlay = overlay
        self.app = app
        self._registered = False
    
    def register_hotkeys(self):
        """Register all global hotkeys."""
        try:
            # HOME: Toggle lock/unlock
            keyboard.add_hotkey('home', self._toggle_lock)
            
            # INSERT: Toggle enabled/disabled
            keyboard.add_hotkey('insert', self._toggle_enabled)
            
            # END: Close application
            keyboard.add_hotkey('end', self._close_app)
            
            self._registered = True
            print("Hotkeys registered: HOME (lock), INSERT (enable/disable), END (close)")
        except Exception as e:
            print(f"Error registering hotkeys: {e}")
    
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
    
    # Initialize process detector
    print("Starting process detection...")
    process_detector = ProcessDetector(GAME_PROCESS_NAME)
    
    # Connect process status to overlay
    process_detector.process_status_changed.connect(overlay.set_process_running)
    
    # Start process detection
    process_detector.start()
    
    # Register hotkeys
    print("Registering hotkeys...")
    hotkey_manager = HotkeyManager(overlay, app)
    hotkey_manager.register_hotkeys()
    
    # Initial process check
    initial_status = process_detector.check_process_running()
    overlay.set_process_running(initial_status)
    
    print("Application started. Overlay is visible.")
    print("Hotkeys:")
    print("  HOME - Toggle overlay lock/unlock")
    print("  INSERT - Toggle auto potion on/off")
    print("  END - Close application")
    
    # Run application
    try:
        sys.exit(app.exec_())
    except KeyboardInterrupt:
        print("Application interrupted")
    finally:
        # Cleanup
        process_detector.stop()
        print("Application closed")


if __name__ == "__main__":
    main()
