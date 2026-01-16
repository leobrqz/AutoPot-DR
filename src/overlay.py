"""
PyQt5 overlay window module.
Creates a transparent, always-on-top overlay with status display and potion log.
"""
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt5.QtCore import Qt, pyqtSignal
from datetime import datetime
from typing import List, Dict


class OverlayWindow(QWidget):
    """Transparent overlay window for displaying status and potion log."""
    
    # Signals for thread-safe updates
    position_changed = pyqtSignal(int, int)  # x, y
    
    def __init__(self, config, parent=None):
        """
        Initialize overlay window.
        
        Args:
            config: Config instance for settings
            parent: Parent widget (None for top-level)
        """
        super().__init__(parent)
        print("Creating overlay window...")
        self.config = config
        self._enabled_state = True
        self._locked_state = config.get_overlay_locked()
        self._process_running = False
        self._potion_log: List[Dict] = []  # List of {timestamp, health_amount, percentage}
        self._current_health = 0.0
        self._max_health = 0.0
        
        self._init_ui()
        self._setup_window_properties()
        self._load_position()
    
    def _init_ui(self):
        """Initialize UI elements."""
        layout = QVBoxLayout()
        layout.setSpacing(5)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # Status label
        self.status_label = QLabel("WAITING")
        self.status_label.setStyleSheet("font-size: 14px; font-weight: bold; background-color: transparent;")
        self._update_status_display()
        layout.addWidget(self.status_label)
        
        # Combined health label
        self.health_label = QLabel("Health: -- | --")
        self.health_label.setStyleSheet("font-size: 12px; color: #CCCCCC; background-color: transparent;")
        layout.addWidget(self.health_label)
        
        # Threshold label
        self.threshold_label = QLabel("Threshold: -- | --%")
        self.threshold_label.setStyleSheet("font-size: 12px; color: #CCCCCC; background-color: transparent;")
        layout.addWidget(self.threshold_label)
        self._update_threshold_display()
        
        # Spacer
        spacer = QLabel("")
        spacer.setFixedHeight(5)
        spacer.setStyleSheet("background-color: transparent;")
        layout.addWidget(spacer)
        
        # Potion log label
        log_header = QLabel("Potion Log:")
        log_header.setStyleSheet("font-size: 11px; font-weight: bold; color: #CCCCCC; background-color: transparent;")
        layout.addWidget(log_header)
        
        # Potion log entries (3 labels)
        self.log_labels = []
        for i in range(3):
            log_label = QLabel("")
            log_label.setStyleSheet("font-size: 10px; color: #AAAAAA; background-color: transparent;")
            log_label.setFixedHeight(15)
            layout.addWidget(log_label)
            self.log_labels.append(log_label)
        
        self.setLayout(layout)
        
        # Set background color (semi-transparent dark)
        self.setStyleSheet("""
            QWidget {
                background-color: rgba(20, 20, 20, 200);
                border-radius: 5px;
            }
        """)
    
    def _setup_window_properties(self):
        """Configure window properties for overlay behavior."""
        # Set window flags for overlay
        # Note: We don't use WindowTransparentForInput because we need mouse events for dragging
        # Note: Removed Qt.Tool so window appears in taskbar
        self.setWindowFlags(
            Qt.WindowStaysOnTopHint |
            Qt.FramelessWindowHint
        )
        
        # Enable transparency
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        # Make window accept mouse events for dragging
        self.setMouseTracking(True)
        
        # Set minimum size
        self.setMinimumSize(200, 150)
        self.adjustSize()
    
    def _load_position(self):
        """Load overlay position from config."""
        x = self.config.get_overlay_pos_x()
        y = self.config.get_overlay_pos_y()
        self.move(x, y)
    
    def _update_status_display(self):
        """Update status label text and color based on current state."""
        if not self._process_running:
            text = "WAITING"
            color = "#FFD700"  # Yellow
        elif self._enabled_state:
            text = "ON"
            color = "#00FF00"  # Green
        else:
            text = "OFF"
            color = "#FF0000"  # Red
        
        self.status_label.setText(f"Status: {text}")
        self.status_label.setStyleSheet(
            f"font-size: 14px; font-weight: bold; color: {color}; background-color: transparent;"
        )
    
    def _update_potion_log_display(self):
        """Update potion log labels with current entries."""
        # Clear all labels first
        for label in self.log_labels:
            label.setText("")
        
        # Display entries (most recent first, max 3)
        for i, entry in enumerate(self._potion_log[:3]):
            timestamp = entry['timestamp'].strftime("%H:%M:%S")
            health_amount = entry['health_amount']
            percentage = entry['percentage']
            text = f"{timestamp} - {health_amount} - {percentage:.1f}%"
            self.log_labels[i].setText(text)
    
    # Public methods for state updates
    def set_enabled_state(self, enabled: bool):
        """Set enabled state (ON/OFF)."""
        self._enabled_state = enabled
        self._update_status_display()
    
    def set_process_running(self, running: bool):
        """Set process running state."""
        self._process_running = running
        self._update_status_display()
    
    def set_locked_state(self, locked: bool):
        """Set locked state (prevents moving)."""
        self._locked_state = locked
        self.config.set_overlay_locked(locked)
    
    def toggle_enabled(self):
        """Toggle enabled state."""
        self.set_enabled_state(not self._enabled_state)
    
    def toggle_locked(self):
        """Toggle locked state."""
        self.set_locked_state(not self._locked_state)
    
    def _update_health_display(self):
        """Update the combined health display."""
        if self._max_health > 0 and self._current_health >= 0:
            self.health_label.setText(f"Health: {self._current_health:.1f} | {self._max_health:.1f}")
        else:
            self.health_label.setText("Health: -- | --")
        self._update_threshold_display()
    
    def _update_threshold_display(self):
        """Update the threshold display with calculated value and percentage."""
        threshold_percentage = self.config.get_health_threshold()
        if self._max_health > 0:
            threshold_value = (self._max_health * threshold_percentage) / 100.0
            self.threshold_label.setText(f"Threshold: {threshold_value:.1f} | {threshold_percentage}%")
        else:
            self.threshold_label.setText(f"Threshold: -- | {threshold_percentage}%")
    
    def set_current_health(self, current_health: float):
        """
        Update current health display.
        
        Args:
            current_health: Current health value to display
        """
        self._current_health = current_health if current_health >= 0 else 0.0
        self._update_health_display()
    
    def set_max_health(self, max_health: float):
        """
        Update max health display.
        
        Args:
            max_health: Max health value to display
        """
        self._max_health = max_health if max_health > 0 else 0.0
        self._update_health_display()
    
    def add_potion_log_entry(self, health_amount: float, percentage: float):
        """
        Add entry to potion log.
        
        Args:
            health_amount: Health value when potion was used
            percentage: Health percentage when potion was used
        """
        entry = {
            'timestamp': datetime.now(),
            'health_amount': int(health_amount),
            'percentage': percentage
        }
        # Add to beginning (most recent first)
        self._potion_log.insert(0, entry)
        # Keep only last 3 entries
        if len(self._potion_log) > 3:
            self._potion_log = self._potion_log[:3]
        self._update_potion_log_display()
    
    # Mouse event handlers for dragging
    def mousePressEvent(self, event):
        """Handle mouse press for dragging."""
        if event.button() == Qt.LeftButton and not self._locked_state:
            self._drag_position = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()
    
    def mouseMoveEvent(self, event):
        """Handle mouse move for dragging."""
        if event.buttons() == Qt.LeftButton and not self._locked_state:
            if hasattr(self, '_drag_position'):
                new_pos = event.globalPos() - self._drag_position
                self.move(new_pos)
                # Save position to config
                self.config.set_overlay_pos(new_pos.x(), new_pos.y())
                event.accept()
    
    def mouseReleaseEvent(self, event):
        """Handle mouse release."""
        if hasattr(self, '_drag_position'):
            delattr(self, '_drag_position')
    
    def is_locked(self) -> bool:
        """Check if overlay is locked."""
        return self._locked_state
    
    def is_enabled(self) -> bool:
        """Check if overlay is enabled."""
        return self._enabled_state
