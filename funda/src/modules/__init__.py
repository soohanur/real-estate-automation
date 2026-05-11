"""Modules package for Funda automation."""
from .browser_automation import BrowserAutomation
from .property_collector import PropertyCollector
from .property_scraper import PropertyScraper
from .agency_scraper import AgencyScraper
from .excel_writer import ExcelWriter
from .kvk_storage import KvkStorage, get_kvk_storage
from .sheets_writer import SheetsWriter
from .scraper_controller import (
    FundaController,
    ScraperStatus,
    ScraperStats,
    start_scraper,
    stop_scraper,
    pause_scraper,
    resume_scraper,
    get_scraper_stats,
    get_controller,
    maybe_resume_run,
)


def create_browser(
    profile_path=None,
    headless=False,
    profile_name='Default',
    implicit_wait=10,
):
    """Factory function to create and start a browser instance."""
    browser = BrowserAutomation(
        profile_path=str(profile_path) if profile_path else None,
        profile_name=profile_name,
        headless=headless,
        implicit_wait=implicit_wait,
    )
    browser.start_browser()
    return browser


__all__ = [
    'BrowserAutomation',
    'PropertyCollector',
    'PropertyScraper',
    'AgencyScraper',
    'ExcelWriter',
    'create_browser',
    'KvkStorage',
    'get_kvk_storage',
    'SheetsWriter',
    'FundaController',
    'ScraperStatus',
    'ScraperStats',
    'start_scraper',
    'stop_scraper',
    'pause_scraper',
    'resume_scraper',
    'get_scraper_stats',
    'get_controller',
    'maybe_resume_run',
]
