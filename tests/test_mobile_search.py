"""Tests for in-session mobile Bing search integration."""

import contextlib
import logging
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
import urllib.parse
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

import browser
import constants
import main
import mobile_search
import rewards_tasks
import run_lock
import run_record
from fakes import FakeDriver, FakeElement


class FakeCdpDriver:
	def __init__(self, browser_version="141.0.3537.57"):
		self.capabilities = {"browserVersion": browser_version}
		self.cdp_calls = []
		self.current_url = rewards_tasks.REWARDS_HOME_URL
		self.window_handles = ["main"]
		self.current_window_handle = "main"
		self.visited = []
		self.quit = mock.Mock()

	def execute_cdp_cmd(self, cmd, params):
		self.cdp_calls.append((cmd, params))
		return {}

	def get(self, url):
		self.visited.append(url)
		self.current_url = url


class MobileFlagTests(unittest.TestCase):
	def test_is_mobile_search_enabled_variants(self):
		with mock.patch.dict(os.environ, {}, clear=True):
			self.assertFalse(mobile_search.is_mobile_search_enabled())

		for val in ("false", "0", "no", ""):
			with mock.patch.dict(os.environ, {"ENABLE_MOBILE_SEARCH": val}, clear=True):
				self.assertFalse(mobile_search.is_mobile_search_enabled())

		for val in ("true", "TRUE", "1", "yes", " Yes "):
			with mock.patch.dict(os.environ, {"ENABLE_MOBILE_SEARCH": val}, clear=True):
				self.assertTrue(mobile_search.is_mobile_search_enabled())


class MobileEmulationTests(unittest.TestCase):
	def test_enable_and_disable_mobile_emulation_send_expected_cdp_commands(self):
		driver = FakeCdpDriver(browser_version="142.0.3595.53")

		ua = mobile_search.enable_mobile_emulation(driver)
		self.assertIn("EdgiOS/142.0.3595.53", ua)
		self.assertIn("iPhone; CPU iPhone OS 18_3 like Mac OS X", ua)

		cmds = [cmd for cmd, _ in driver.cdp_calls]
		self.assertIn("Network.disable", cmds)
		self.assertIn("Network.enable", cmds)
		self.assertLess(cmds.index("Network.disable"), cmds.index("Network.enable"))

		by_cmd = {cmd: params for cmd, params in driver.cdp_calls}
		self.assertEqual(by_cmd["Network.setExtraHTTPHeaders"], {"headers": {}})
		self.assertEqual(by_cmd["Network.setUserAgentOverride"]["platform"], "iPhone")
		self.assertTrue(by_cmd["Network.setUserAgentOverride"]["userAgentMetadata"]["mobile"])
		self.assertEqual(by_cmd["Network.setUserAgentOverride"]["userAgentMetadata"]["platform"], "iOS")
		self.assertEqual(by_cmd["Network.setUserAgentOverride"]["userAgentMetadata"]["platformVersion"], "18.3.0")
		self.assertEqual(by_cmd["Network.setUserAgentOverride"]["userAgent"], ua)
		self.assertTrue(by_cmd["Emulation.setUserAgentOverride"]["userAgentMetadata"]["mobile"])
		self.assertEqual(
			by_cmd["Emulation.setUserAgentOverride"]["userAgentMetadata"]["brands"][0],
			{"brand": "Microsoft Edge", "version": "142"},
		)
		self.assertEqual(by_cmd["Emulation.setDeviceMetricsOverride"]["width"], 375)
		self.assertEqual(by_cmd["Emulation.setDeviceMetricsOverride"]["height"], 812)
		self.assertEqual(by_cmd["Emulation.setDeviceMetricsOverride"]["deviceScaleFactor"], 3)
		self.assertTrue(by_cmd["Emulation.setDeviceMetricsOverride"]["mobile"])
		self.assertTrue(by_cmd["Emulation.setTouchEmulationEnabled"]["enabled"])

		driver.cdp_calls.clear()
		mobile_search.disable_mobile_emulation(driver)
		self.assertEqual(
			[cmd for cmd, _ in driver.cdp_calls],
			[
				"Emulation.clearDeviceMetricsOverride",
				"Emulation.setTouchEmulationEnabled",
				"Emulation.setUserAgentOverride",
				"Network.setUserAgentOverride",
				"Network.setExtraHTTPHeaders",
			],
		)
		disable_by_cmd = dict(driver.cdp_calls)
		self.assertEqual(disable_by_cmd["Emulation.setTouchEmulationEnabled"], {"enabled": False})
		self.assertEqual(disable_by_cmd["Emulation.setUserAgentOverride"], {"userAgent": ""})
		self.assertEqual(disable_by_cmd["Network.setUserAgentOverride"], {"userAgent": ""})
		self.assertEqual(disable_by_cmd["Network.setExtraHTTPHeaders"], {"headers": {}})

	def test_disable_mobile_emulation_is_best_effort_on_cdp_errors(self):
		driver = mock.Mock()
		driver.execute_cdp_cmd.side_effect = RuntimeError("target closed")

		mobile_search.disable_mobile_emulation(driver)
		self.assertEqual(driver.execute_cdp_cmd.call_count, 5)


class ParseMobilePointsTests(unittest.TestCase):
	def test_parses_live_earn_sidebar_mobile_bing_search_row(self):
		text = "\n".join([
			"Points breakdown",
			"Today's points",
			"135",
			"Today's activity",
			"Points",
			"Desktop Bing search",
			"90/90",
			"Mobile Bing search",
			"0/60",
			"Offers",
			"45",
		])
		self.assertEqual(mobile_search.parse_mobile_points_from_text(text), (0, 60))

	def test_parses_english_mobile_search_row(self):
		text = "\n".join([
			"Points breakdown",
			"Bing search",
			"60 / 60",
			"Mobile search",
			"18 / 60",
		])
		self.assertEqual(mobile_search.parse_mobile_points_from_text(text), (18, 60))

	def test_parses_vietnamese_mobile_search_row_with_thousands_separator(self):
		text = "\n".join([
			"Chi tiết điểm",
			"Tìm kiếm trên Bing",
			"60/60",
			"Tìm kiếm trên thiết bị di động",
			"1,020 / 1,500",
		])
		self.assertEqual(mobile_search.parse_mobile_points_from_text(text), (1020, 1500))

	def test_never_confuses_pc_search_row_with_mobile_search(self):
		text = "\n".join([
			"Points breakdown",
			"Desktop Bing search",
			"90/90",
			"Bing search",
			"60/60",
			"Offers",
			"20",
		])
		self.assertIsNone(mobile_search.parse_mobile_points_from_text(text))


class ReadMobilePointsTests(unittest.TestCase):
	def test_opens_earn_clicks_breakdown_and_reads_sidebar(self):
		breakdown_btn = FakeElement(text="Today's points\n135\nPoints breakdown")
		close_btn = FakeElement(text="", attributes={"aria-label": "Close"})
		sidebar = FakeElement(
			text="Points breakdown\nDesktop Bing search\n90/90\nMobile Bing search\n12/60",
			attributes={"id": "react-aria-9"},
			children={
				(By.TAG_NAME, "button"): [close_btn],
				(By.CSS_SELECTOR, "button[aria-label*='lose']"): [close_btn],
			},
		)

		class EarnDriver(FakeDriver):
			def __init__(self):
				super().__init__(children={
					(By.TAG_NAME, "button"): [breakdown_btn],
					(By.TAG_NAME, "body"): [FakeElement(text="Earn")],
				})
				self.visited = []
				self.clicked = []
				self.current_url = ""

			def get(self, url):
				self.visited.append(url)
				self.current_url = url

			def execute_script(self, script, *args):
				if args:
					self.clicked.append(args[0])
					if args[0] is breakdown_btn:
						self.children[(By.TAG_NAME, "section")] = [sidebar]

		driver = EarnDriver()
		with mock.patch.object(mobile_search.time, "sleep"):
			points = mobile_search.read_mobile_points(driver, timeout=2.0)

		self.assertEqual(points, (12, 60))
		self.assertEqual(driver.visited, ["https://rewards.bing.com/earn"])
		self.assertEqual(driver.clicked, [breakdown_btn, close_btn])


class PerformMobileSearchTests(unittest.TestCase):
	def setUp(self):
		self.stack = contextlib.ExitStack()
		self.addCleanup(self.stack.close)
		self.stack.enter_context(mock.patch.object(mobile_search.time, "sleep"))
		# Real seconds otherwise, and the failure paths wait them out in full.
		for name in ("SEARCH_BOX_TIMEOUT", "SUBMIT_TIMEOUT", "RESULTS_TIMEOUT"):
			self.stack.enter_context(mock.patch.object(mobile_search, name, 0.05))

	def test_navigates_to_bing_home_types_without_clicking_and_submits_on_enter(self):
		class SearchBox:
			def __init__(self, driver):
				self.driver = driver
				self.clicked = False
				self.cleared = False
				self.keys = []

			def is_displayed(self):
				return True

			def click(self):
				self.clicked = True

			def clear(self):
				self.cleared = True

			def send_keys(self, *vals):
				self.keys.extend(vals)
				if Keys.ENTER in vals:
					self.driver.current_url = "https://www.bing.com/search?q=coffee+beans"

		class SearchDriver:
			def __init__(self):
				self.current_url = "https://www.bing.com/search?q=previous"
				self.visited = []
				self.box = SearchBox(self)

			def get(self, url):
				self.visited.append(url)
				self.current_url = url

			def execute_script(self, script, *args):
				return "complete" if "readyState" in script else None

			def find_elements(self, by, selector):
				if (by, selector) == (By.ID, "sb_form_q"):
					return [self.box]
				return []

		driver = SearchDriver()
		ok = mobile_search.perform_mobile_search(driver, "coffee beans")

		self.assertTrue(ok)
		self.assertEqual(driver.visited, ["https://www.bing.com/"])
		self.assertFalse(driver.box.clicked)
		self.assertTrue(driver.box.cleared)
		self.assertEqual("".join(k for k in driver.box.keys if k != Keys.ENTER), "coffee beans")
		self.assertEqual(driver.box.keys[-1], Keys.ENTER)

	def _stuck_driver(self, *, renders=True, enter_works_after=None):
		test = self

		class Textarea:
			def __init__(self, driver):
				self.driver = driver
				self.typed = ""
				self.enters = 0

			def is_displayed(self):
				return True

			def clear(self):
				self.typed = ""

			def send_keys(self, *vals):
				for val in vals:
					if val == Keys.ENTER:
						self.enters += 1
						# Simulates mobile <textarea> swallowing Enter without submitting
						if enter_works_after is not None and self.enters > enter_works_after:
							self.driver.current_url = f"https://www.bing.com/search?q={urllib.parse.quote_plus(self.typed)}"
					else:
						self.typed += val

		class StuckDriver:
			def __init__(self):
				self.current_url = ""
				self.visited = []
				self.refreshed = 0
				self.box = Textarea(self)

			def get(self, url):
				self.visited.append(url)
				self.current_url = url

			def refresh(self):
				self.refreshed += 1

			def execute_script(self, script, *args):
				if "readyState" in script:
					return "complete" if renders else "loading"
				return None

			def find_elements(self, by, selector):
				if (by, selector) == (By.ID, "sb_form_q"):
					return [self.box]
				return []

		return StuckDriver()

	def test_swallowed_enter_is_pressed_again_instead_of_waiting_out(self):
		driver = self._stuck_driver(enter_works_after=1)
		with self.assertLogs(mobile_search.logger, level="WARNING") as logs:
			ok = mobile_search.perform_mobile_search(driver, "gold price")

		self.assertTrue(ok)
		self.assertEqual(driver.visited, ["https://www.bing.com/"])
		self.assertIn(
			"WARNING:mobile_search:Mobile search 'gold price' did not open the results page within 0.05s, submitting again",
			logs.output,
		)

	def test_falls_back_through_reload_and_home_to_direct_search_url(self):
		driver = self._stuck_driver()
		with self.assertLogs(mobile_search.logger, level="WARNING") as logs:
			ok = mobile_search.perform_mobile_search(driver, "gold price")

		self.assertTrue(ok)
		self.assertEqual(driver.refreshed, 1)
		self.assertEqual(
			driver.visited,
			["https://www.bing.com/", "https://www.bing.com/", "https://www.bing.com/search?q=gold%20price&form=QBLH"],
		)
		output = "\n".join(logs.output)
		self.assertIn("retry 1/3 via reload", output)
		self.assertIn("retry 3/3 via direct search URL", output)

	def test_search_whose_results_never_render_is_reported_as_skipped(self):
		driver = self._stuck_driver(renders=False, enter_works_after=0)
		with self.assertLogs(mobile_search.logger, level="WARNING") as logs:
			ok = mobile_search.perform_mobile_search(driver, "gold price")

		self.assertFalse(ok)
		self.assertIn(
			"WARNING:mobile_search:Mobile search 'gold price' skipped after 4 attempts (SearchNotConfirmed), continuing with the next one",
			logs.output,
		)


class RunMobileSearchesTests(unittest.TestCase):
	def setUp(self):
		old = logging.root.manager.disable
		logging.disable(logging.CRITICAL)
		self.addCleanup(logging.disable, old)

	def test_skips_searching_when_quota_already_complete(self):
		driver = FakeCdpDriver()
		with (
			mock.patch.object(mobile_search, "read_mobile_points", return_value=(60, 60)),
			mock.patch.object(mobile_search, "perform_mobile_search") as search_mock,
		):
			sent, earned, max_pts = mobile_search.run_mobile_searches(driver)

		self.assertEqual((sent, earned, max_pts), (0, 60, 60))
		search_mock.assert_not_called()
		cmds = [cmd for cmd, _ in driver.cdp_calls]
		self.assertIn("Emulation.setUserAgentOverride", cmds)
		self.assertIn("Emulation.clearDeviceMetricsOverride", cmds)

	def test_runs_multiple_rounds_with_ceiling_batches_until_full(self):
		driver = FakeCdpDriver()
		progress_updates = []
		queries_asked = []

		def fake_collect(count, exclude=None):
			queries_asked.append(count)
			return [f"query-{len(queries_asked)}-{i}" for i in range(count)]

		with (
			mock.patch.object(mobile_search, "read_mobile_points", side_effect=[(0, 10), (6, 10), (10, 10)]),
			mock.patch.object(mobile_search, "_collect_queries", side_effect=fake_collect),
			mock.patch.object(mobile_search, "perform_mobile_search", return_value=True) as search_mock,
			mock.patch.object(mobile_search.time, "sleep"),
		):
			sent, earned, max_pts = mobile_search.run_mobile_searches(
				driver, progress_cb=progress_updates.append
			)

		# (10 - 0 + 2) // 3 = 4, then (10 - 6 + 2) // 3 = 2
		self.assertEqual(queries_asked, [4, 2])
		self.assertEqual((sent, earned, max_pts), (6, 10, 10))
		self.assertEqual(search_mock.call_count, 6)
		self.assertEqual(progress_updates[0], "sent 1 mobile search")
		self.assertEqual(progress_updates[-1], "sent 6 mobile searches")

	def test_stops_early_when_round_produces_no_points(self):
		driver = FakeCdpDriver()
		with (
			mock.patch.object(mobile_search, "read_mobile_points", side_effect=[(3, 30), (3, 30)]),
			mock.patch.object(mobile_search, "_collect_queries", side_effect=lambda count, exclude=None: [f"q-{i}" for i in range(count)]),
			mock.patch.object(mobile_search, "perform_mobile_search", return_value=True) as search_mock,
			mock.patch.object(mobile_search.time, "sleep"),
		):
			sent, earned, max_pts = mobile_search.run_mobile_searches(driver, max_rounds=6)

		# (30 - 3 + 2) // 3 = 9 searches in round 1, then stops immediately
		self.assertEqual((sent, earned, max_pts), (9, 3, 30))
		self.assertEqual(search_mock.call_count, 9)

	def test_skipped_searches_are_not_counted_and_the_rest_still_run(self):
		driver = FakeCdpDriver()
		progress_updates = []
		# (30 - 0 + 2) // 3 = 10 searches, the 3rd and 7th cannot be confirmed.
		outcomes = iter([True, True, False, True, True, True, False, True, True, True, True, True])
		with (
			mock.patch.object(mobile_search, "read_mobile_points", side_effect=[(0, 30), (24, 30), (30, 30)]),
			mock.patch.object(mobile_search, "_collect_queries", side_effect=lambda count, exclude=None: [f"q-{i}" for i in range(count)]),
			mock.patch.object(mobile_search, "perform_mobile_search", side_effect=lambda d, q: next(outcomes)) as search_mock,
			mock.patch.object(mobile_search.time, "sleep"),
		):
			sent, earned, max_pts = mobile_search.run_mobile_searches(driver, progress_cb=progress_updates.append)

		# 8 confirmed in round 1, then (30 - 24 + 2) // 3 = 2 more.
		self.assertEqual(search_mock.call_count, 12)
		self.assertEqual((sent, earned, max_pts), (10, 30, 30))
		self.assertEqual(progress_updates[-1], "sent 10 mobile searches")

	def test_three_unconfirmed_searches_in_a_row_end_the_batch_early(self):
		driver = FakeCdpDriver()
		with (
			mock.patch.object(mobile_search, "read_mobile_points", side_effect=[(0, 30), (6, 30), (6, 30)]),
			mock.patch.object(mobile_search, "_collect_queries", side_effect=lambda count, exclude=None: [f"q-{i}" for i in range(count)]),
			mock.patch.object(mobile_search, "perform_mobile_search", side_effect=[True, True, False, False, False] + [False] * 20) as search_mock,
			mock.patch.object(mobile_search.time, "sleep"),
		):
			sent, earned, max_pts = mobile_search.run_mobile_searches(driver)

		# Round 1 stops after 5 of 10, round 2 skips 3 in a row and makes no points.
		self.assertEqual(search_mock.call_count, 8)
		self.assertEqual((sent, earned, max_pts), (2, 6, 30))

	def test_points_are_re_read_instead_of_ending_on_the_first_failed_read(self):
		driver = FakeCdpDriver()
		with (
			mock.patch.object(mobile_search, "read_mobile_points", side_effect=[(0, 6), None, None, (6, 6)]),
			mock.patch.object(mobile_search, "_collect_queries", side_effect=lambda count, exclude=None: [f"q-{i}" for i in range(count)]),
			mock.patch.object(mobile_search, "perform_mobile_search", return_value=True),
			mock.patch.object(mobile_search.time, "sleep"),
		):
			sent, earned, max_pts = mobile_search.run_mobile_searches(driver)

		self.assertEqual((sent, earned, max_pts), (2, 6, 6))

	def test_disables_mobile_emulation_even_when_search_raises(self):
		driver = FakeCdpDriver()
		with (
			mock.patch.object(mobile_search, "read_mobile_points", return_value=(0, 30)),
			mock.patch.object(mobile_search, "_collect_queries", return_value=["boom"]),
			mock.patch.object(mobile_search, "perform_mobile_search", side_effect=RuntimeError("browser died")),
			self.assertRaises(RuntimeError),
		):
			mobile_search.run_mobile_searches(driver)

		cmds = [cmd for cmd, _ in driver.cdp_calls]
		self.assertIn("Emulation.clearDeviceMetricsOverride", cmds)
		self.assertIn("Emulation.setTouchEmulationEnabled", cmds)


class MainSingleSessionMobileIntegrationTests(unittest.TestCase):
	def setUp(self):
		self.temp = tempfile.TemporaryDirectory()
		self.addCleanup(self.temp.cleanup)
		self.home = Path(self.temp.name)
		self.stack = contextlib.ExitStack()
		self.addCleanup(self.stack.close)
		self.env = self.stack.enter_context(
			mock.patch.dict(os.environ, {"USER_DATA_DIR": str(self.home / "profiles")}, clear=True)
		)
		self.stack.enter_context(mock.patch.object(constants, "RUNS_DIR", str(self.home / "runs")))
		self.stack.enter_context(mock.patch.object(main, "DOTENV_PATH", str(self.home / "missing.env")))
		self.stack.enter_context(mock.patch.object(browser, "headless_enabled", return_value=True))
		self.stack.enter_context(mock.patch.object(main.log_utils, "setup_logging", lambda: None))

		self.prep_desktop = self.stack.enter_context(
			mock.patch.object(main.desktop_utils, "prepare_desktop_before_launch", return_value=True)
		)
		self.switch_back = self.stack.enter_context(
			mock.patch.object(main.desktop_utils, "switch_back_after_launch")
		)
		self.cleanup_desktop = self.stack.enter_context(
			mock.patch.object(main.desktop_utils, "cleanup_virtual_desktop", return_value=True)
		)
		self.stack.enter_context(mock.patch.object(main.desktop_utils, "reset_virtual_desktop_state"))
		self.stack.enter_context(mock.patch.object(main.desktop_utils, "is_virtual_desktop_enabled", return_value=True))

		self.driver = FakeCdpDriver()
		self.start_driver = self.stack.enter_context(
			mock.patch.object(browser, "start_driver", return_value=self.driver)
		)

		task_class = rewards_tasks.RewardsTaskUtils

		def make_real_tasks(driver):
			tasks = task_class.__new__(task_class)
			tasks.driver = driver
			tasks.main_window = "main"
			tasks.progress = None
			tasks.tab_utils = types.SimpleNamespace(
				ensure_focus=lambda: None,
				close_all_other_tabs=lambda **kwargs: None,
			)
			for _, _, method in rewards_tasks.TASKS:
				setattr(tasks, method, mock.Mock())
			return tasks

		self.stack.enter_context(
			mock.patch.object(main.rewards_tasks, "RewardsTaskUtils", side_effect=make_real_tasks)
		)
		old = logging.root.manager.disable
		logging.disable(logging.CRITICAL)
		self.addCleanup(logging.disable, old)

	def _run_and_read_events(self, argv):
		def fake_mobile(driver, max_rounds=6, progress_cb=None):
			if progress_cb:
				progress_cb("sent 4 mobile searches")
			return 4, 12, 60

		with mock.patch.object(mobile_search, "run_mobile_searches", side_effect=fake_mobile) as mobile_runner:
			code = main.cli(argv)

		ids = run_record.list_run_ids(str(self.home / "runs"))
		self.assertEqual(len(ids), 1)
		events = run_record.read_events(str(self.home / "runs" / (ids[0] + ".jsonl")))
		return code, events, mobile_runner

	def test_cli_mobile_flag_runs_desktop_then_mobile_in_fresh_session_on_same_virtual_desktop(self):
		code, events, mobile_runner = self._run_and_read_events(["--unattended", "--mobile"])

		self.assertEqual(code, 0)
		mobile_runner.assert_called_once()
		# Desktop and Mobile each get a fresh Edge session, sharing one virtual desktop.
		self.assertEqual(self.start_driver.call_count, 2)
		self.assertEqual(self.prep_desktop.call_count, 2)
		self.assertEqual(self.switch_back.call_count, 2)
		self.assertEqual(self.driver.quit.call_count, 2)
		self.cleanup_desktop.assert_called_once()
		self.assertIsNone(run_lock.status())

		task_ends = [e for e in events if e["type"] == "task_end"]
		self.assertEqual([e["task"] for e in task_ends], [*rewards_tasks.TASK_IDS, "mobile_searches"])
		self.assertEqual(task_ends[-1]["outcome"], "ok")
		self.assertEqual(task_ends[-1]["progress"], "sent 4 mobile searches")
		self.assertEqual(events[-1]["result"], "ok")

	def test_enable_mobile_search_env_triggers_mobile_and_no_mobile_overrides_it(self):
		os.environ["ENABLE_MOBILE_SEARCH"] = "true"
		code, events, mobile_runner = self._run_and_read_events(["--unattended"])
		self.assertEqual(code, 0)
		mobile_runner.assert_called_once()
		self.assertIn("mobile_searches", [e["task"] for e in events if e["type"] == "task_end"])

		# Fresh runs directory for --no-mobile check
		for p in (self.home / "runs").glob("*.jsonl"):
			p.unlink()

		code2, events2, mobile_runner2 = self._run_and_read_events(["--unattended", "--no-mobile"])
		self.assertEqual(code2, 0)
		mobile_runner2.assert_not_called()
		self.assertNotIn("mobile_searches", [e["task"] for e in events2 if e["type"] == "task_end"])


if __name__ == "__main__":
	unittest.main()
