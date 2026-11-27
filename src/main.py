from constants import DOTENV_PATH
import argparse
import dataclasses
from dataclasses import dataclass
import logging
import os
import sys
import time
import dotenv
import log_utils
import accounts
import browser
import desktop_utils
import mobile_search
import rewards_tasks
import rewards_state
import element_selectors
import run_record
import run_lock

logger = logging.getLogger(__name__)

DEFAULT_MIN_POINTS = 15
WHOLE_PAGE_CODES = ("signed_out", "terms_of_use", "page_blank")


@dataclass(frozen=True)
class RunPlan:
	read_state: bool = False
	only_if_open: bool = False
	check_only: bool = False
	min_points: int = DEFAULT_MIN_POINTS
	run_if_unreadable: bool = False
	mobile: bool = False


_plan = RunPlan()
_account_started = False
_account_ran = False


def decision_state(state: rewards_state.RewardsState) -> rewards_state.RewardsState:
	if state.unreadable is None or state.unreadable in WHOLE_PAGE_CODES:
		return state
	sections = [code for code in state.unreadable.split(",") if code != "balance"]
	return dataclasses.replace(state, unreadable=",".join(sections) or None)


def decide(state, plan) -> tuple[bool, str]:
	worth = rewards_state.worth_running(decision_state(state), plan.min_points)
	if worth is None:
		return (True, "unreadable_run_anyway") if plan.run_if_unreadable else (False, "unreadable")
	if worth:
		return True, ("enough_open" if state.open_points >= plan.min_points else "quest_unlocked")
	return False, ("below_threshold" if state.open_points > 0 else "nothing_open")


def _decision_log(account, state, reason):
	if reason == "quest_unlocked":
		logger.info("%s: a quest step is unlocked, running", account.name)
	elif reason in ("enough_open", "unreadable_run_anyway"):
		logger.info("%s: about %s points open, running", account.name, state.open_points)
	elif reason == "below_threshold":
		logger.info("%s: only %s points open, under the threshold of %s, not running", account.name, state.open_points, _plan.min_points)
	elif reason == "nothing_open":
		logger.info("%s: nothing open, not running", account.name)
	else:
		logger.info("%s: the Rewards page could not be read (%s), not running", account.name, state.unreadable)


def _quit_driver(driver, account_name: str) -> None:
	try:
		driver.quit()
	except Exception as exc:
		# quit() raises when the browser is already gone. Letting it out
		# here would replace whatever actually went wrong with the tidy-up's
		# own error, and the process it is meant to end is dead anyway.
		logger.warning(
			"%s: the driver did not shut down cleanly: %s",
			account_name,
			log_utils.exception_summary(exc),
		)


def _start_account_driver(account: accounts.Account):
	try:
		if not desktop_utils.prepare_desktop_before_launch():
			return None
		return browser.start_driver(account)
	finally:
		desktop_utils.switch_back_after_launch()


def _run_mobile_in_fresh_session(account: accounts.Account) -> None:
	"""Run mobile searches in a clean Edge session without Desktop CDP state.

	Reusing the Desktop driver carries over MSRewards/Desktop headers and
	pooled Bing connections, causing Bing to award 0 mobile points even when
	every mobile search succeeds. Launching a fresh Edge process on the same
	worker virtual desktop matches the standalone mobile runner.
	"""
	task_id, name, _ = rewards_tasks.MOBILE_TASK
	began = time.monotonic()
	run_record.emit("task_start", task=task_id, name=name)
	outcome, reason = "ok", None
	progress = "sent 0 mobile searches"

	logger.info("Starting a fresh Edge session for Mobile searches...")
	mobile_driver = _start_account_driver(account)
	if mobile_driver is None:
		reason = "could not start a fresh Edge session for mobile searches"
		outcome = "fail"
		rewards_tasks.logger.error("[FAIL] %s: %s", name, reason)
		run_record.emit("task_end", task=task_id, name=name, outcome=outcome, detail=reason,
			progress=progress, duration_ms=round((time.monotonic() - began) * 1000))
		return

	def set_progress(msg: str) -> None:
		nonlocal progress
		progress = msg

	try:
		try:
			mobile_search.run_mobile_searches(mobile_driver, progress_cb=set_progress)
			rewards_tasks.logger.info("[OK] %s", name)
		except Exception as exc:
			tag, reason = rewards_tasks.task_failure_report(exc, progress)
			outcome = "skip" if tag == "SKIP" else "fail"
			rewards_tasks.logger.log(
				logging.WARNING if tag == "SKIP" else logging.ERROR,
				"[%s] %s: %s", tag, name, reason,
				exc_info=rewards_tasks.logger.isEnabledFor(logging.DEBUG),
			)
		run_record.emit("task_end", task=task_id, name=name, outcome=outcome, detail=reason,
			progress=progress, duration_ms=round((time.monotonic() - began) * 1000))
		if _plan.read_state:
			state = rewards_state.read_state(mobile_driver, element_selectors.ElementSelectionUtils(mobile_driver))
			run_record.emit("state", phase="after", **dataclasses.asdict(state))
	finally:
		_quit_driver(mobile_driver, account.name)


def run_account(account: accounts.Account) -> bool:
	"""Work one account. Returns whether the browser started."""
	global _account_started, _account_ran
	began = time.monotonic()
	_account_started = _account_ran = False
	run_record.emit("account_start", account=account.name, profile=account.user_data_dir)
	def ended(error_code=None):
		if error_code == "browser_failed":
			run_record.emit("browser_failed", account=account.name)
		run_record.emit("account_end", account=account.name, started=_account_started, ran_tasks=_account_ran,
			error_code=error_code, duration_ms=round((time.monotonic() - began) * 1000))

	driver = _start_account_driver(account)
	if driver is None:
		ended("browser_failed")
		return False

	_account_started = True
	run_mobile = False
	try:
		only = None
		if _plan.read_state:
			driver.set_page_load_timeout(60)
			driver.set_script_timeout(30)
			elements = element_selectors.ElementSelectionUtils(driver)
			state = rewards_state.read_state(driver, elements)
			run_record.emit("state", phase="before", **dataclasses.asdict(state))
			if _plan.check_only:
				ended()
				return True
			if _plan.only_if_open:
				should_run, reason = decide(state, _plan)
				run_record.emit("decision", should_run=should_run, reason=reason, open_points=state.open_points, min_points=_plan.min_points)
				_decision_log(account, state, reason)
				if not should_run:
					ended()
					return True
				if reason == "quest_unlocked":
					only = {"quests"}
		rewards = rewards_tasks.RewardsTaskUtils(driver)
		_account_ran = True
		if only is None:
			rewards.complete_all_tasks()
			run_mobile = _plan.mobile
		else:
			rewards.complete_all_tasks(only=only)
		if _plan.read_state and not run_mobile:
			driver.execute_cdp_cmd("Network.setExtraHTTPHeaders", {"headers": {}})
			state = rewards_state.read_state(driver, rewards.elements)
			run_record.emit("state", phase="after", **dataclasses.asdict(state))
	except KeyboardInterrupt:
		ended()
		raise
	finally:
		_quit_driver(driver, account.name)

	if run_mobile:
		try:
			_run_mobile_in_fresh_session(account)
		except KeyboardInterrupt:
			ended()
			raise

	ended()
	return True


def main(unattended: bool = False, plan: RunPlan | None = None) -> int:
	global _plan, _account_started, _account_ran
	_plan = plan or RunPlan(mobile=mobile_search.is_mobile_search_enabled())
	_plan = dataclasses.replace(_plan, read_state=_plan.read_state or _plan.only_if_open or _plan.check_only)
	log_utils.setup_logging()
	desktop_utils.reset_virtual_desktop_state()

	if desktop_utils.is_virtual_desktop_enabled() and not desktop_utils.is_windows():
		logger.warning("USE_VIRTUAL_DESKTOP is enabled, but virtual desktops are only supported on Windows.")

	try:
		configured = accounts.configured()
	except ValueError as exc:
		logger.error("[FAIL] %s", exc)
		run_record.open_run("cli", [], dataclasses.asdict(_plan))
		run_record.close_run("config_error", 2, str(exc))

		return 2

	recorder = run_record.open_run("cli", [account.name for account in configured], dataclasses.asdict(_plan))
	try:
		lock = run_lock.acquire("farmer", recorder.run_id)
	except BaseException:
		run_record.close_run("failed", 1)
		raise
	if lock is None:
		info = run_lock.status()
		logger.error("[FAIL] another run is using the browser profiles (started %s by %s)", info.since if info else "unknown", info.owner if info else "unknown")
		run_record.close_run("busy", 3)
		return 3
	started = 0
	result, code = "failed", 1
	try:
		for account in configured:
			if len(configured) > 1:
				logger.info("=== account: %s ===", account.name)
			_account_started = _account_ran = False
			began = time.monotonic()
			# One account must not be able to end the batch. complete_all_tasks
			# already contains a task that fails, and run_account names the profile
			# that is already open, but everything else - a driver that will not
			# start for some other reason, the browser dying mid-run, a page that
			# never loads - reached here and took the remaining accounts with it.
			# KeyboardInterrupt is deliberately not caught: Ctrl-C means stop.
			with run_record.account_context(account.name):
				try:
					if run_account(account):
						started += 1
				except Exception as exc:
					logger.error(
						"[FAIL] %s: %s: %s",
						account.name,
						type(exc).__name__,
						log_utils.exception_summary(exc),
						exc_info=logger.isEnabledFor(logging.DEBUG),
					)
					run_record.emit("account_end", started=_account_started, ran_tasks=_account_ran, error_code="error",
						detail=f"{type(exc).__name__}: {log_utils.exception_summary(exc)}", duration_ms=round((time.monotonic() - began) * 1000))
		if len(configured) > 1:
			logger.info("%s/%s accounts ran", started, len(configured))
		# Nothing is watching a container, and stdin is not a terminal there.
		# --unattended skips the prompt for scheduled runs on the host too.
		if not browser.headless_enabled() and not unattended:
			input("Press Enter to exit...")
		code = 0 if started else 1
		stats = recorder.stats
		if not started:
			result = "failed"
		elif _plan.check_only:
			result = "checked"
		elif stats["accounts_decided_no"] and not stats["accounts_ran"] and not any(stats[key] for key in ("task_fail", "browser_failed", "account_error")):
			result = "skipped"
		elif any(stats[key] for key in ("task_fail", "browser_failed", "account_error")):
			result = "partial"
		else:
			result = "ok"
		return code
	except KeyboardInterrupt:
		result, code = "stopped", 130
		raise
	finally:
		try:
			desktop_utils.cleanup_virtual_desktop()
		finally:
			try:
				run_record.close_run(result, code)
			finally:
				lock.release()


def cli(argv: list[str] | None = None) -> int:
	parser = argparse.ArgumentParser(description="Work through the Rewards tasks for every configured account.")
	parser.add_argument("--unattended", action="store_true", help="exit without waiting for Enter, for scheduled runs")
	parser.add_argument("--read-state", action="store_true", help="record open work before and after the run")
	parser.add_argument("--only-if-open", action="store_true", help="run only for enough known points or an unlocked quest")
	parser.add_argument("--min-points", type=int, default=DEFAULT_MIN_POINTS, help="point threshold for --only-if-open (default: 15)")
	parser.add_argument("--run-if-unreadable", action="store_true", help="allow --only-if-open to run when the page cannot be read")
	parser.add_argument("--check-only", action="store_true", help="record open work without starting any tasks")
	parser.add_argument("--mobile", action="store_true", help="also run mobile searches in the same Edge session")
	parser.add_argument("--no-mobile", action="store_true", help="disable mobile searches even if ENABLE_MOBILE_SEARCH is set")
	arguments = parser.parse_args(argv)
	if os.path.isfile(DOTENV_PATH): dotenv.load_dotenv(DOTENV_PATH)
	minimum = arguments.min_points
	if minimum < 0:
		parser.error("--min-points must not be negative")
	mobile = arguments.mobile or (not arguments.no_mobile and mobile_search.is_mobile_search_enabled())
	return main(unattended=arguments.unattended, plan=RunPlan(arguments.read_state or arguments.only_if_open or arguments.check_only,
		arguments.only_if_open, arguments.check_only, minimum, arguments.run_if_unreadable, mobile))


if __name__ == "__main__":
	sys.exit(cli())
