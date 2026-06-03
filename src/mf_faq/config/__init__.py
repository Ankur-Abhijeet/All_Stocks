"""mf_faq.config — Phase 0: Configuration loading & validation."""
from mf_faq.config.loader import AppConfig, ConfigurationError, load_config

__all__ = ["load_config", "AppConfig", "ConfigurationError"]
