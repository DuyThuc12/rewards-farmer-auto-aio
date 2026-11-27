"""Mobile Bing search automation running inside the existing Edge session.

Uses Chrome DevTools Protocol (CDP) emulation to switch the active browser
session to a mobile Android/Pixel 7 profile without spawning a second Edge
process or touching Windows Virtual Desktops.
"""

import logging
import os
import random
import re
import time
from typing import Callable
import urllib.parse

from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

import element_selectors
import log_utils
import queries
import query_sources
import tab_utils

logger = logging.getLogger(__name__)

ENV_VAR = "ENABLE_MOBILE_SEARCH"
MOBILE_POINTS_URL = "https://rewards.bing.com/earn"
BING_URL = "https://www.bing.com/"
DEFAULT_FALLBACK_SEARCHES = 20

# Seconds. Module level so tests can shrink them.
SEARCH_BOX_TIMEOUT = 10
SUBMIT_TIMEOUT = 8
RESULTS_TIMEOUT = 15
# How a search that could not be confirmed is retried, in order, after the
# first try from bing.com. Same ladder as the desktop searches.
RECOVERY_STEPS = ("reload", "bing home", "direct search URL")
# One skipped search is fine, a row of them means Bing is not working.
MAX_CONSECUTIVE_SKIPPED = 3
# How often the points breakdown is tried before a round gives up on it.
POINTS_READ_ATTEMPTS = 3

SEARCH_BOX_SELECTORS = (
	(By.ID, "sb_form_q"),
	(By.NAME, "q"),
	(By.CSS_SELECTOR, "textarea[name='q']"),
	(By.CSS_SELECTOR, "input[type='search']"),
)


class SearchNotConfirmed(TimeoutException):
	"""A mobile search whose results page could not be confirmed."""

# Includes English and Vietnamese Microsoft Rewards UI labels for points parsing.
MOBILE_LABELS = (
	"mobile bing search",
	"mobile search",
	"di động",
	"di dong",
	"tìm kiếm trên thiết bị di động",
	"tim kiem tren thiet bi di dong",
)

SAMPLE_KEYWORDS = (
	"weather forecast today",
	"latest world news",
	"football match schedule",
	"gold price today",
	"latest ai technology",
	"popular movies in theaters",
	"top travel destinations",
	"how to cook beef pho",
	"everyday life hacks",
	"best budget student laptops",
	"long battery life smartphones 2026",
	"top pop music hits",
	"health and nutrition tips",
	"fat loss gym workout",
	"lunar calendar today",
	"stock market trends",
	"affordable electric cars",
	"currency exchange rates",
	"popular comic books",
	"trending mobile games 2026",
)


def is_mobile_search_enabled() -> bool:
	"""Return whether ENABLE_MOBILE_SEARCH is enabled in the environment."""
	return os.environ.get(ENV_VAR, "").strip().lower() in ("1", "true", "yes")


def _edge_version(driver) -> tuple[str, str]:
	"""Extract (major, full) version strings from driver capabilities."""
	caps = getattr(driver, "capabilities", None) or {}
	raw = str(caps.get("browserVersion") or "").strip()

	if re.fullmatch(r"\d+(?:\.\d+)*", raw):
		major = raw.split(".", 1)[0]
		parts = raw.split(".")
		while len(parts) < 4:
			parts.append("0")
		full = ".".join(parts[:4])
		return major, full

	return "131", "131.0.0.0"


def _mobile_user_agent(full_version: str) -> str:
	return (
		f"Mozilla/5.0 (iPhone; CPU iPhone OS 18_3 like Mac OS X) AppleWebKit/605.1.15 "
		f"(KHTML, like Gecko) Version/18.3 EdgiOS/{full_version} Mobile/15E148 Safari/605.1.15"
	)


def enable_mobile_emulation(driver) -> str:
	"""Switch the active Edge session to iPhone 11 Pro (iOS 18.3) mobile emulation via CDP."""
	major, full = _edge_version(driver)
	ua = _mobile_user_agent(full)
	ua_override = {
		"userAgent": ua,
		"platform": "iPhone",
		"userAgentMetadata": {
			"brands": [
				{"brand": "Microsoft Edge", "version": major},
				{"brand": "Chromium", "version": major},
			],
			"fullVersionList": [
				{"brand": "Microsoft Edge", "version": full},
				{"brand": "Chromium", "version": full},
			],
			"mobile": True,
			"platform": "iOS",
			"platformVersion": "18.3.0",
			"architecture": "",
			"bitness": "",
			"model": "iPhone",
			"wow64": False,
		},
	}

	# Reset the CDP Network agent so Desktop overrides (e.g. X-Rewards-Source
	# and desktop User-Agent extra headers) do not linger in Chromium's stack.
	try:
		driver.execute_cdp_cmd("Network.disable", {})
	except Exception as exc:
		logger.debug("Network.disable failed during mobile emulation setup: %s", log_utils.exception_summary(exc))

	try:
		driver.execute_cdp_cmd("Network.enable", {})
	except Exception as exc:
		logger.debug("Network.enable failed during mobile emulation setup: %s", log_utils.exception_summary(exc))

	driver.execute_cdp_cmd("Network.setExtraHTTPHeaders", {"headers": {}})
	driver.execute_cdp_cmd("Network.setUserAgentOverride", ua_override)
	driver.execute_cdp_cmd("Emulation.setUserAgentOverride", ua_override)
	driver.execute_cdp_cmd(
		"Emulation.setDeviceMetricsOverride",
		{
			"width": 375,
			"height": 812,
			"deviceScaleFactor": 3,
			"mobile": True,
			"screenWidth": 375,
			"screenHeight": 812,
		},
	)
	driver.execute_cdp_cmd(
		"Emulation.setTouchEmulationEnabled",
		{"enabled": True, "maxTouchPoints": 5},
	)
	logger.info("Mobile emulation enabled (iPhone 11 Pro, iOS 18.3): %s", ua)
	return ua


def disable_mobile_emulation(driver) -> None:
	"""Best-effort restore of desktop browser state after mobile searches."""
	for cmd, params in (
		("Emulation.clearDeviceMetricsOverride", {}),
		("Emulation.setTouchEmulationEnabled", {"enabled": False}),
		("Emulation.setUserAgentOverride", {"userAgent": ""}),
		("Network.setUserAgentOverride", {"userAgent": ""}),
		("Network.setExtraHTTPHeaders", {"headers": {}}),
	):
		try:
			driver.execute_cdp_cmd(cmd, params)
		except Exception as exc:
			logger.debug("CDP cleanup %s failed: %s", cmd, log_utils.exception_summary(exc))


def parse_mobile_points_from_text(text: str) -> tuple[int, int] | None:
	"""Parse (earned, max_pts) from mobile search row text, or None if absent.

	Strictly anchors on known mobile search labels so PC/Bing search rows are
	never mistaken for mobile quota.
	"""
	if not text:
		return None

	lines = [line.strip() for line in text.splitlines() if line.strip()]
	for i, line in enumerate(lines):
		line_lower = line.lower()
		if any(label in line_lower for label in MOBILE_LABELS):
			for candidate in lines[i:i + 4]:
				match = re.search(r"([\d,]+)\s*/\s*([\d,]+)", candidate)
				if match:
					earned = int(match.group(1).replace(",", ""))
					max_pts = int(match.group(2).replace(",", ""))
					return earned, max_pts

	return None


def _close_sidebar(driver, elements) -> None:
	"""Best-effort close of the Rewards points breakdown sidebar."""
	try:
		button = elements.get_generic_sidebar_close_button()
		if "lose" in (button.get_dom_attribute("aria-label") or "").lower():
			driver.execute_script("arguments[0].click();", button)
	except Exception:
		pass


def read_mobile_points(driver, timeout: float = 25.0) -> tuple[int, int] | None:
	"""Open `/earn` -> `Points breakdown` sidebar and read the mobile search quota."""
	try:
		driver.get(MOBILE_POINTS_URL)
	except TimeoutException:
		pass
	except Exception as exc:
		logger.warning("Could not open mobile points page: %s", log_utils.exception_summary(exc))
		return None

	elements = element_selectors.ElementSelectionUtils(driver)
	clicked_breakdown = False
	deadline = time.monotonic() + max(0.0, timeout)

	while True:
		if not clicked_breakdown:
			try:
				btn = elements.get_points_breakdown_button()
				driver.execute_script("arguments[0].click();", btn)
				clicked_breakdown = True
			except Exception:
				pass

		if clicked_breakdown:
			try:
				sidebar = elements.get_sidebar_section()
				parsed = parse_mobile_points_from_text(sidebar.text or "")
				if parsed is not None:
					_close_sidebar(driver, elements)
					return parsed
			except Exception:
				pass

		try:
			body = driver.find_element(By.TAG_NAME, "body")
			parsed = parse_mobile_points_from_text(body.text or "")
			if parsed is not None:
				if clicked_breakdown:
					_close_sidebar(driver, elements)
				return parsed
		except Exception:
			pass

		remaining = deadline - time.monotonic()
		if remaining <= 0:
			break
		time.sleep(min(1.0, remaining))

	if clicked_breakdown:
		_close_sidebar(driver, elements)
	return None


def _sanitize_query(raw: str) -> str:
	"""Return a clean single-line query string."""
	for line in (raw or "").splitlines():
		cleaned = " ".join(line.strip().strip(" \"'").split())
		if cleaned:
			return cleaned
	return ""


def _collect_queries(count: int, exclude: set[str] | None = None) -> list[str]:
	"""Collect up to `count` clean, unique queries using the configured source."""
	if count <= 0:
		return []

	collected: list[str] = []
	seen: set[str] = set(exclude or ())

	def add_candidates(candidates) -> None:
		for raw in candidates:
			cleaned = _sanitize_query(raw)
			if cleaned and cleaned.lower() not in seen:
				seen.add(cleaned.lower())
				collected.append(cleaned)
				if len(collected) >= count:
					return

	try:
		add_candidates(queries.related_queries(count))
	except Exception as exc:
		logger.warning("Primary query source failed for mobile search: %s", log_utils.exception_summary(exc))

	if len(collected) < count:
		try:
			add_candidates(query_sources.wordlist_queries(count - len(collected)))
		except Exception:
			pass

	if len(collected) < count:
		fallback = list(SAMPLE_KEYWORDS)
		random.shuffle(fallback)
		add_candidates(fallback)

	return collected[:count]


def _wait_until(timeout: float, condition: Callable[[], object], poll: float = 0.5):
	"""Poll condition until it returns something truthy, or None after timeout.

	Exceptions from condition count as "not yet", the page is mid-render.
	"""
	deadline = time.monotonic() + max(0.0, timeout)

	while True:
		try:
			result = condition()
		except Exception:
			result = None

		if result:
			return result

		remaining = deadline - time.monotonic()
		if remaining <= 0:
			return None
		time.sleep(min(poll, remaining))


def _find_search_box(driver):
	"""The visible, enabled Bing search box, or None."""
	for by, selector in SEARCH_BOX_SELECTORS:
		try:
			elems = driver.find_elements(by, selector)
		except Exception:
			continue
		for elem in elems:
			try:
				if not elem.is_displayed():
					continue
				is_enabled = getattr(elem, "is_enabled", None)
				if is_enabled is not None and not is_enabled():
					continue
				return elem
			except Exception:
				continue
	return None


def _box_value(box) -> str | None:
	get_attribute = getattr(box, "get_attribute", None)
	if get_attribute is None:
		return None
	try:
		return get_attribute("value")
	except Exception:
		return None


def _results_ready(driver) -> bool:
	"""Whether the results page rendered: any known container, or a finished load."""
	for selector in element_selectors.ElementSelectionUtils.BING_RESULTS_SELECTORS:
		try:
			if driver.find_elements(By.CSS_SELECTOR, selector):
				return True
		except Exception:
			continue

	try:
		state = driver.execute_script("return document.readyState")
	except Exception:
		state = None

	return state == "complete" and element_selectors.is_bing_results_url(getattr(driver, "current_url", ""))


def _navigated_to_results(driver, before_url: str, query: str) -> bool:
	url = getattr(driver, "current_url", "") or ""
	return element_selectors.is_bing_results_url(url) and (
		url != before_url or element_selectors.is_bing_results_url(url, query)
	)


def _accept_consent(driver) -> None:
	try:
		accept_btns = driver.find_elements(By.ID, "bnp_btn_accept")
		if accept_btns and accept_btns[0].is_displayed():
			accept_btns[0].click()
			time.sleep(0.5)
	except Exception:
		pass


def _focus(driver) -> None:
	try:
		tab_utils.TabUtils(driver).ensure_focus()
	except Exception:
		pass


def _type_query(box, query: str) -> None:
	box.clear()
	time.sleep(0.3)
	for char in query:
		box.send_keys(char)
		time.sleep(random.uniform(0.04, 0.12))
	time.sleep(0.5)


def _submit_and_confirm(driver, query: str) -> None:
	"""Type query into the open Bing page and return once its results rendered.

	Raises SearchNotConfirmed instead of returning quietly. The old flow
	looked for the box once after a fixed sleep, accepted any URL change as
	success and never checked that results rendered, so a lost search was
	still counted as sent.
	"""
	box = _wait_until(SEARCH_BOX_TIMEOUT, lambda: _find_search_box(driver))
	if box is None:
		raise SearchNotConfirmed(f"no usable search box on {getattr(driver, 'current_url', '')}")

	_type_query(box, query)
	before_url = getattr(driver, "current_url", "") or ""
	box.send_keys(Keys.ENTER)

	if not _wait_until(SUBMIT_TIMEOUT, lambda: _navigated_to_results(driver, before_url, query)):
		logger.warning(
			"Mobile search %r did not open the results page within %ss, submitting again",
			query, SUBMIT_TIMEOUT
		)
		_resubmit(driver, query)

		if not _wait_until(SUBMIT_TIMEOUT, lambda: _navigated_to_results(driver, before_url, query)):
			raise SearchNotConfirmed(f"Bing stayed on {getattr(driver, 'current_url', '')} after submitting twice")

	if not _wait_until(RESULTS_TIMEOUT, lambda: _results_ready(driver)):
		raise SearchNotConfirmed("the results page never rendered")


def _resubmit(driver, query: str) -> None:
	box = _find_search_box(driver)
	value = _box_value(box) if box is not None else None

	# The text never reached the box, Enter would submit nothing. Type again.
	if box is not None and value is not None and element_selectors._normalized(query) not in element_selectors._normalized(value):
		_type_query(box, query)
		box.send_keys(Keys.ENTER)
		return

	# The mobile <textarea> can swallow Enter, the form submit does not.
	try:
		forms = driver.find_elements(By.ID, "sb_form")
		if forms:
			driver.execute_script("arguments[0].submit();", forms[0])
			return
	except Exception:
		pass

	if box is not None:
		box.send_keys(Keys.ENTER)


def _direct_search_url(query: str) -> str:
	return f"https://www.bing.com/search?q={urllib.parse.quote(query)}&form=QBLH"


def perform_mobile_search(driver, query: str) -> bool:
	"""Send one Bing search and confirm it, retrying through RECOVERY_STEPS.

	Returns False when the search could not be confirmed at all, so the
	caller skips it instead of counting it as sent.
	"""
	error: BaseException | None = None
	total = len(RECOVERY_STEPS)

	for attempt, step in enumerate((None, *RECOVERY_STEPS)):
		try:
			if step is None:
				driver.get(BING_URL)
			else:
				logger.warning(
					"Mobile search %r could not be confirmed (%s), retry %s/%s via %s",
					query, type(error).__name__, attempt, total, step
				)
				if step == "reload":
					driver.refresh()
				elif step == "bing home":
					driver.get(BING_URL)
				else:
					driver.get(_direct_search_url(query))

			_focus(driver)
			time.sleep(random.uniform(1.5, 2.5))
			_accept_consent(driver)

			if step == "direct search URL":
				if not element_selectors.is_bing_results_url(getattr(driver, "current_url", ""), query):
					raise SearchNotConfirmed(f"direct search URL ended on {getattr(driver, 'current_url', '')}")
				if not _wait_until(RESULTS_TIMEOUT, lambda: _results_ready(driver)):
					raise SearchNotConfirmed("the results page never rendered")
			else:
				_submit_and_confirm(driver, query)

			return True
		except Exception as exc:
			# Exception rather than a bare except, so Ctrl+C still ends the run.
			error = exc

	logger.warning(
		"Mobile search %r skipped after %s attempts (%s), continuing with the next one",
		query, total + 1, type(error).__name__
	)
	return False


def _read_points_with_retry(driver, what: str) -> tuple[int, int] | None:
	"""read_mobile_points, tried up to POINTS_READ_ATTEMPTS times."""
	for attempt in range(1, POINTS_READ_ATTEMPTS + 1):
		points = read_mobile_points(driver)
		if points is not None:
			return points
		if attempt < POINTS_READ_ATTEMPTS:
			logger.warning(
				"Reload %s/%s could not read the mobile search points %s",
				attempt, POINTS_READ_ATTEMPTS, what
			)
	return None


def _run_batch(driver, batch_queries, used_queries: set[str], on_sent: Callable[[], None]) -> int:
	"""Search batch_queries, skipping searches that cannot be confirmed.

	Returns how many were confirmed. Stops early after
	MAX_CONSECUTIVE_SKIPPED searches in a row fail, so the points get read
	again instead of searching into a broken page.
	"""
	sent = 0
	skipped_in_a_row = 0

	for q in batch_queries:
		used_queries.add(q.lower())

		if not perform_mobile_search(driver, q):
			skipped_in_a_row += 1
			if skipped_in_a_row >= MAX_CONSECUTIVE_SKIPPED:
				logger.warning(
					"%s mobile searches in a row could not be confirmed, re-reading the points",
					skipped_in_a_row
				)
				break
			continue

		skipped_in_a_row = 0
		sent += 1
		on_sent()
		time.sleep(random.uniform(5.5, 7.5))

	return sent


def run_mobile_searches(
	driver,
	max_rounds: int = 6,
	progress_cb: Callable[[str], None] | None = None,
) -> tuple[int, int | None, int | None]:
	"""Run mobile Bing searches inside the existing Edge driver until quota is filled.

	Returns (searches_sent, final_earned, final_max).
	"""
	total_sent = 0
	used_queries: set[str] = set()

	def report_progress() -> None:
		if progress_cb is not None:
			noun = "search" if total_sent == 1 else "searches"
			progress_cb(f"sent {total_sent} mobile {noun}")

	def on_sent() -> None:
		nonlocal total_sent
		total_sent += 1
		report_progress()

	try:
		enable_mobile_emulation(driver)
		points = _read_points_with_retry(driver, "before searching")

		if points is not None:
			earned, max_pts = points
			logger.info("Mobile search points before: %s/%s", earned, max_pts)

			if max_pts > 0 and earned >= max_pts:
				logger.info("Mobile search quota already complete: %s/%s", earned, max_pts)
				return 0, earned, max_pts

			if max_pts == 0:
				logger.info("Mobile search quota is 0 for this account")
				return 0, earned, max_pts

			for round_number in range(1, max_rounds + 1):
				if earned >= max_pts:
					break

				searches = max(1, (max_pts - earned + 2) // 3)
				batch_queries = _collect_queries(searches, exclude=used_queries)
				if not batch_queries:
					logger.warning("No queries available for mobile search round %s.", round_number)
					break

				sent_in_round = _run_batch(driver, batch_queries, used_queries, on_sent)

				updated = _read_points_with_retry(driver, f"after round {round_number}")
				if updated is None:
					logger.warning("Could not re-read mobile search points after round %s.", round_number)
					break

				previous = earned
				earned, max_pts = updated
				logger.info("Mobile round %s: %s searches -> %s/%s", round_number, sent_in_round, earned, max_pts)

				if earned <= previous:
					logger.warning("Mobile round produced no points, stopping instead of searching pointlessly.")
					break

			if earned < max_pts:
				logger.warning("Mobile search quota not filled: %s/%s", earned, max_pts)
			else:
				logger.info("Mobile search quota complete: %s/%s", earned, max_pts)

			return total_sent, earned, max_pts

		logger.warning("Could not read mobile points breakdown; running %s fallback searches.", DEFAULT_FALLBACK_SEARCHES)
		_run_batch(driver, _collect_queries(DEFAULT_FALLBACK_SEARCHES, exclude=used_queries), used_queries, on_sent)

		final_points = _read_points_with_retry(driver, "after the fallback searches")
		if final_points is not None:
			final_earned, final_max = final_points
			logger.info("Mobile search points after fallback: %s/%s", final_earned, final_max)
			return total_sent, final_earned, final_max

		return total_sent, None, None
	finally:
		disable_mobile_emulation(driver)
