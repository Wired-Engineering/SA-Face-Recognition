"""Configuration manager for the Face Recognition System"""
import yaml
import os
from typing import Any, Dict, Optional
from pathlib import Path

class ConfigManager:
    """Manages application configuration using YAML file"""

    def __init__(self, config_path: str = "system/config.yaml"):
        self.config_path = Path(config_path)
        self.config: Dict[str, Any] = {}
        self.load_config()

    def load_config(self) -> None:
        """Load configuration from YAML file"""
        if not self.config_path.exists():
            print(f"⚠️ Config file not found at {self.config_path}, creating default config")
            self.create_default_config()

        try:
            with open(self.config_path, 'r') as f:
                self.config = yaml.safe_load(f) or {}
                print(f"✅ Configuration loaded from {self.config_path}")
        except Exception as e:
            print(f"❌ Error loading config: {e}")
            self.config = self.get_default_config()

    def save_config(self) -> bool:
        """Save configuration to YAML file"""
        try:
            with open(self.config_path, 'w') as f:
                yaml.dump(self.config, f, default_flow_style=False, sort_keys=False)
                print(f"💾 Configuration saved to {self.config_path}")
            return True
        except Exception as e:
            print(f"❌ Error saving config: {e}")
            return False

    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value by dot notation key (e.g., 'camera.source')"""
        keys = key.split('.')
        value = self.config

        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
                if value is None:
                    return default
            else:
                return default

        return value

    def set(self, key: str, value: Any) -> bool:
        """Set configuration value by dot notation key"""
        keys = key.split('.')
        config_ref = self.config

        # Navigate to the parent dictionary
        for k in keys[:-1]:
            if k not in config_ref:
                config_ref[k] = {}
            config_ref = config_ref[k]

        # Set the value
        config_ref[keys[-1]] = value

        # Save to file
        return self.save_config()

    def update_section(self, section: str, values: Dict[str, Any]) -> bool:
        """Update an entire configuration section"""
        if section not in self.config:
            self.config[section] = {}

        self.config[section].update(values)
        return self.save_config()

    def get_camera_config(self) -> Dict[str, Any]:
        """Get camera configuration"""
        return self.config.get('camera', {})

    def set_camera_config(self, source: str, device_id: Optional[str] = None,
                         rtsp_url: Optional[str] = None) -> bool:
        """Set camera configuration"""
        camera_config = {
            'source': source,
            'device_id': device_id,
            'rtsp_url': rtsp_url
        }
        return self.update_section('camera', camera_config)

    def get_display_config(self) -> Dict[str, Any]:
        """Get display configuration"""
        return self.config.get('display', {})

    def set_display_config(self, timer: int = None, background_color: str = None, font_color: str = None,
                          use_background_image: bool = None, background_image: str = None,
                          font_family: str = None, font_size: str = None) -> bool:
        """Set display configuration"""
        display_config = self.get_display_config()
        if timer is not None:
            display_config['timer'] = timer
        if background_color is not None:
            display_config['background_color'] = background_color
        if font_color is not None:
            display_config['font_color'] = font_color
        if use_background_image is not None:
            display_config['use_background_image'] = use_background_image
        if background_image is not None:
            display_config['background_image'] = background_image
        if font_family is not None:
            display_config['font_family'] = font_family
        if font_size is not None:
            display_config['font_size'] = font_size
        return self.update_section('display', display_config)

    def get_recognition_config(self) -> Dict[str, Any]:
        """Get face recognition configuration"""
        return self.config.get('recognition', {})

    def get_default_config(self) -> Dict[str, Any]:
        """Get default configuration"""
        return {
            'camera': {
                'source': 'default',
                'device_id': None,
                'rtsp_url': None,
                'legacy_url': None
            },
            'display': {
                'timer': 5,
                'background_color': '#FFE8D4',
                'font_color': '#032F5C',
                'use_background_image': False,
                'background_image': None,
                'font_family': 'Inter',
                'font_size': 'medium'
            },
            'recognition': {
                'threshold': 0.5,
                'draw_boxes': True
            },
            'system': {
                'database_path': 'system/Attendance.db',
                'encodings_path': 'images/',
                'rtsp_pickle': 'system/rtspin.pkl'
            }
        }

    def create_default_config(self) -> None:
        """Create default configuration file"""
        self.config = self.get_default_config()
        self.save_config()

    def reload(self) -> None:
        """Reload configuration from file"""
        self.load_config()

# Global config instance
config_manager = ConfigManager()