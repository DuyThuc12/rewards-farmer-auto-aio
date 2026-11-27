"""Standalone Mobile Search runner for Microsoft Rewards (via run_mobile_search.bat).

Reuses the shared `src/mobile_search.py`, `src/browser.py`, and
`src/desktop_utils.py` modules so Virtual Desktop handling and mobile CDP
emulation stay consistent with `src/main.py --mobile`.
"""

import logging
import os
import sys

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

for candidate in (
	os.path.join(CURRENT_DIR, "src"),
	os.path.join(CURRENT_DIR, "rewards-farmer", "src"),
	os.path.join(CURRENT_DIR, "rewards-farmer-main", "src"),
):
	if os.path.isdir(candidate):
		if candidate not in sys.path:
			sys.path.insert(0, candidate)
		break

import dotenv

import accounts
import browser
import constants
import desktop_utils
import log_utils
import mobile_search

logger = logging.getLogger(__name__)


def main() -> int:
	if os.path.isfile(constants.DOTENV_PATH):
		dotenv.load_dotenv(constants.DOTENV_PATH)

	log_utils.setup_logging()
	desktop_utils.reset_virtual_desktop_state()

	if desktop_utils.is_virtual_desktop_enabled() and not desktop_utils.is_windows():
		logger.warning("USE_VIRTUAL_DESKTOP is enabled, but virtual desktops are only supported on Windows.")

	print("=" * 60)
	print("      MICROSOFT REWARDS - MOBILE SEARCH AUTOMATION")
	print("=" * 60)
	print()

	try:
		configured = accounts.configured()
	except ValueError as exc:
		logger.error("[FAIL] %s", exc)
		return 2

	started = 0
	try:
		for account in configured:
			if len(configured) > 1:
				logger.info("=== account: %s ===", account.name)

			driver = None
			try:
				if not desktop_utils.prepare_desktop_before_launch():
					continue
				driver = browser.start_driver(account)
			finally:
				desktop_utils.switch_back_after_launch()

			if driver is None:
				continue

			started += 1
			try:
				sent, earned, max_pts = mobile_search.run_mobile_searches(driver)
				print()
				print("=" * 60)
				if earned is not None and max_pts is not None:
					print(f"  RESULT ({account.name}): {earned}/{max_pts} Mobile Search points ({sent} searches)")
				else:
					print(f"  RESULT ({account.name}): completed {sent} Mobile Search queries")
				print("=" * 60)
			except KeyboardInterrupt:
				logger.info("Process stopped by user (Ctrl+C).")
				return 130
			except Exception as exc:
				logger.error(
					"[FAIL] %s: %s: %s",
					account.name,
					type(exc).__name__,
					log_utils.exception_summary(exc),
					exc_info=logger.isEnabledFor(logging.DEBUG),
				)
			finally:
				try:
					driver.quit()
				except Exception as exc:
					logger.warning(
						"%s: the driver did not shut down cleanly: %s",
						account.name,
						log_utils.exception_summary(exc),
					)
	finally:
		desktop_utils.cleanup_virtual_desktop()

	return 0 if started else 1


if __name__ == "__main__":
	sys.exit(main())
