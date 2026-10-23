"""The payments dev script: the environment it reads and what it reports.

These cover the interface a person uses - `./dev_payments.sh --check` - so the
two rules that matter are tested rather than trusted: a variable already in the
environment wins over the file, and no key is ever echoed.
"""

import os
import re
import shutil
import socket
import subprocess
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
SCRIPT = BACKEND / "dev_payments.sh"
BASH = shutil.which("bash")

pytestmark = pytest.mark.skipif(
    BASH is None, reason="bash is needed to run the dev script"
)


def run_script(*args, env=None, cwd=BACKEND):
    """Run `--check` with a clean Stripe environment.

    The developer's own STRIPE_* variables (and this machine's PORT=0) would
    otherwise decide what the assertions see.
    """
    base = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("STRIPE_", "DEV_PAYMENTS_")) and key != "PORT"
    }
    base.update(env or {})
    return subprocess.run(
        [BASH, SCRIPT.as_posix(), *args],
        cwd=str(cwd),
        env=base,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_help_lists_the_switches_and_exits_zero():
    result = run_script("--help")

    assert result.returncode == 0
    assert "--api-only" in result.stdout
    assert "--check" in result.stdout
    assert "--env-file" in result.stdout


def test_check_reports_keys_without_echoing_them(tmp_path):
    env_file = tmp_path / "stripe.env"
    env_file.write_text(
        'export STRIPE_SECRET_KEY="sk_test_never_print_me"\n', encoding="utf-8"
    )

    result = run_script("--check", "--env-file", env_file.as_posix())

    assert result.returncode == 0
    assert "STRIPE_SECRET_KEY:  set (env file)" in result.stdout
    assert "http://127.0.0.1:8000/api/payments/webhook" in result.stdout
    assert "sk_test_never_print_me" not in result.stdout + result.stderr


def test_a_variable_in_the_environment_wins_over_the_file(tmp_path):
    env_file = tmp_path / "stripe.env"
    env_file.write_text("STRIPE_SECRET_KEY=sk_test_from_file\n", encoding="utf-8")

    result = run_script(
        "--check",
        "--env-file",
        env_file.as_posix(),
        env={"STRIPE_SECRET_KEY": "sk_test_from_environment"},
    )

    assert "STRIPE_SECRET_KEY:  set (environment)" in result.stdout


def test_a_relative_env_file_is_resolved_against_the_callers_directory(tmp_path):
    (tmp_path / "local.env").write_text("STRIPE_SECRET_KEY=sk_test_here\n", encoding="utf-8")

    result = run_script("--check", "--env-file", "local.env", cwd=tmp_path)

    assert result.returncode == 0
    assert "set (env file)" in result.stdout


def test_a_missing_key_is_reported_as_no_charges(tmp_path):
    env_file = tmp_path / "empty.env"
    env_file.write_text("# nothing configured yet\n", encoding="utf-8")

    result = run_script("--check", "--env-file", env_file.as_posix())

    assert result.returncode == 0
    assert "STRIPE_SECRET_KEY:  missing" in result.stdout
    assert "503" in result.stdout
    assert "API only (no STRIPE_SECRET_KEY)" in result.stdout


def test_a_taken_port_moves_to_the_next_free_one_and_moves_the_webhook_with_it():
    with socket.socket() as held:
        held.bind(("127.0.0.1", 0))
        held.listen(1)
        busy = held.getsockname()[1]

        result = run_script("--check", env={"PORT": str(busy)})

    assert result.returncode == 0
    assert f"Port {busy} is in use" in result.stdout
    chosen = re.search(r"using (\d+) instead", result.stdout)
    assert chosen, result.stdout
    port = chosen.group(1)
    assert port != str(busy)
    assert f"http://127.0.0.1:{port}" in result.stdout
    assert f"http://127.0.0.1:{port}/api/payments/webhook" in result.stdout


def test_a_live_key_is_refused_before_anything_starts():
    result = run_script("--api-only", env={"STRIPE_SECRET_KEY": "sk_live_not_a_test"})

    assert result.returncode == 2
    assert "live key" in result.stderr
    assert "--allow-live" in result.stderr
    assert "Starting IFTR API" not in result.stdout


def test_a_restricted_live_key_is_refused_too():
    result = run_script("--api-only", env={"STRIPE_SECRET_KEY": "rk_live_not_a_test"})

    assert result.returncode == 2
    assert "--allow-live" in result.stderr


def test_check_explains_the_live_key_refusal_without_starting():
    result = run_script("--check", env={"STRIPE_SECRET_KEY": "sk_live_not_a_test"})

    assert result.returncode == 0
    assert "live key:           yes - will refuse to start without --allow-live" in result.stdout


def test_allow_live_is_the_explicit_confirmation():
    result = run_script(
        "--check", "--allow-live", env={"STRIPE_SECRET_KEY": "sk_live_not_a_test"}
    )

    assert result.returncode == 0
    assert "allowed by --allow-live" in result.stdout


def test_a_test_key_is_not_flagged_as_live(tmp_path):
    env_file = tmp_path / "stripe.env"
    env_file.write_text("STRIPE_SECRET_KEY=sk_test_fine\n", encoding="utf-8")

    result = run_script("--check", "--env-file", env_file.as_posix())

    assert result.returncode == 0
    assert "live key:           no" in result.stdout


def test_an_unknown_option_is_refused_with_exit_two():
    result = run_script("--nonsense")

    assert result.returncode == 2
    assert "unknown option: --nonsense" in result.stderr


def test_a_named_env_file_that_does_not_exist_is_an_error():
    result = run_script("--check", "--env-file", "no-such-file.env")

    assert result.returncode == 1
    assert "no such env file" in result.stderr
