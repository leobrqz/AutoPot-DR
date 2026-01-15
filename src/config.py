"""
Configuration management module.
Handles loading, creating, and saving configuration file.
"""
import os
import configparser
from pathlib import Path


class Config:
    """Manages application configuration from INI file."""
    
    CONFIG_FILE = "config_user.ini"
    
    # Default values
    DEFAULT_HEALTH_THRESHOLD = 30.0
    DEFAULT_MAX_HEALTH_BASE_OFFSET = "0x064D8FD0"
    DEFAULT_MAX_HEALTH_OFFSETS = "0x30,0x940,0x5D0,0x2F0,0x370"
    DEFAULT_CURRENT_HEALTH_BASE_OFFSET = "0x064D8FD0"
    DEFAULT_CURRENT_HEALTH_OFFSETS = "0x30,0x8C8,0xB0,0x2F0,0x368"
    DEFAULT_HOTKEY_LOCK = "home"
    DEFAULT_HOTKEY_TOGGLE = "insert"
    DEFAULT_HOTKEY_CLOSE = "end"
    DEFAULT_OVERLAY_POS_X = 200
    DEFAULT_OVERLAY_POS_Y = 880
    DEFAULT_OVERLAY_LOCKED = False
    
    def __init__(self):
        """Initialize config, create file if missing."""
        self.config = configparser.ConfigParser()
        self._ensure_config_file()
        self._load_config()
    
    def _ensure_config_file(self):
        """Create config file with defaults if it doesn't exist."""
        if not os.path.exists(self.CONFIG_FILE):
            self._create_default_config()
    
    def _create_default_config(self):
        """Create config file with default values."""
        self.config['GENERAL'] = {
            'health_threshold': str(self.DEFAULT_HEALTH_THRESHOLD)
        }
        self.config['OVERLAY'] = {
            'pos_x': str(self.DEFAULT_OVERLAY_POS_X),
            'pos_y': str(self.DEFAULT_OVERLAY_POS_Y),
            'locked': str(self.DEFAULT_OVERLAY_LOCKED)
        }
        self.config['KEYBINDS'] = {
            'hotkey_lock': self.DEFAULT_HOTKEY_LOCK,
            'hotkey_toggle': self.DEFAULT_HOTKEY_TOGGLE,
            'hotkey_close': self.DEFAULT_HOTKEY_CLOSE
        }
        self.config['POINTERCHAINS'] = {
            'max_health_base_offset': self.DEFAULT_MAX_HEALTH_BASE_OFFSET,
            'max_health_offsets': self.DEFAULT_MAX_HEALTH_OFFSETS,
            'current_health_base_offset': self.DEFAULT_CURRENT_HEALTH_BASE_OFFSET,
            'current_health_offsets': self.DEFAULT_CURRENT_HEALTH_OFFSETS
        }
        
        try:
            with open(self.CONFIG_FILE, 'w') as f:
                self.config.write(f)
        except Exception as e:
            print(f"Error creating config file: {e}")
    
    def _load_config(self):
        """Load configuration from file."""
        try:
            self.config.read(self.CONFIG_FILE)
        except Exception as e:
            print(f"Error loading config file: {e}, using defaults")
    
    def _save_config(self):
        """Save current configuration to file."""
        try:
            with open(self.CONFIG_FILE, 'w') as f:
                self.config.write(f)
        except Exception as e:
            print(f"Error saving config file: {e}")
    
    # Getter methods
    def get_health_threshold(self):
        """Get health threshold percentage."""
        try:
            return float(self.config.get('GENERAL', 'health_threshold', 
                                        fallback=self.DEFAULT_HEALTH_THRESHOLD))
        except (ValueError, configparser.NoOptionError):
            return self.DEFAULT_HEALTH_THRESHOLD
    
    def get_max_health_base_offset(self):
        """Get max health base offset (hex string)."""
        return self.config.get('POINTERCHAINS', 'max_health_base_offset',
                              fallback=self.DEFAULT_MAX_HEALTH_BASE_OFFSET)
    
    def get_max_health_offsets(self):
        """Get max health offsets as comma-separated hex string."""
        return self.config.get('POINTERCHAINS', 'max_health_offsets',
                              fallback=self.DEFAULT_MAX_HEALTH_OFFSETS)
    
    def get_current_health_base_offset(self):
        """Get current health base offset (hex string)."""
        return self.config.get('POINTERCHAINS', 'current_health_base_offset',
                              fallback=self.DEFAULT_CURRENT_HEALTH_BASE_OFFSET)
    
    def get_current_health_offsets(self):
        """Get current health offsets as comma-separated hex string."""
        return self.config.get('POINTERCHAINS', 'current_health_offsets',
                              fallback=self.DEFAULT_CURRENT_HEALTH_OFFSETS)
    
    def get_hotkey_lock(self):
        """Get hotkey for lock/unlock overlay."""
        return self.config.get('KEYBINDS', 'hotkey_lock',
                              fallback=self.DEFAULT_HOTKEY_LOCK)
    
    def get_hotkey_toggle(self):
        """Get hotkey for toggle enable/disable."""
        return self.config.get('KEYBINDS', 'hotkey_toggle',
                              fallback=self.DEFAULT_HOTKEY_TOGGLE)
    
    def get_hotkey_close(self):
        """Get hotkey for close application."""
        return self.config.get('KEYBINDS', 'hotkey_close',
                              fallback=self.DEFAULT_HOTKEY_CLOSE)
    
    def get_overlay_pos_x(self):
        """Get overlay X position."""
        try:
            return int(self.config.get('OVERLAY', 'pos_x',
                                      fallback=self.DEFAULT_OVERLAY_POS_X))
        except (ValueError, configparser.NoOptionError):
            return self.DEFAULT_OVERLAY_POS_X
    
    def get_overlay_pos_y(self):
        """Get overlay Y position."""
        try:
            return int(self.config.get('OVERLAY', 'pos_y',
                                      fallback=self.DEFAULT_OVERLAY_POS_Y))
        except (ValueError, configparser.NoOptionError):
            return self.DEFAULT_OVERLAY_POS_Y
    
    def get_overlay_locked(self):
        """Get overlay locked state."""
        try:
            value = self.config.get('OVERLAY', 'locked',
                                   fallback=str(self.DEFAULT_OVERLAY_LOCKED))
            return value.lower() in ('true', '1', 'yes')
        except (ValueError, configparser.NoOptionError):
            return self.DEFAULT_OVERLAY_LOCKED
    
    # Setter methods
    def set_overlay_pos(self, x, y):
        """Save overlay position to config."""
        if 'OVERLAY' not in self.config:
            self.config['OVERLAY'] = {}
        self.config['OVERLAY']['pos_x'] = str(x)
        self.config['OVERLAY']['pos_y'] = str(y)
        self._save_config()
    
    def set_overlay_locked(self, locked):
        """Save overlay locked state to config."""
        if 'OVERLAY' not in self.config:
            self.config['OVERLAY'] = {}
        self.config['OVERLAY']['locked'] = str(locked)
        self._save_config()
