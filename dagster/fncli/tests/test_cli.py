import os

import click
from click.testing import CliRunner

from fncli.cli import cli
from fncli.cmds import common

EXPECTED_COMMANDS = {
    "hello-world", "demo", "experiment", "diff", "apply", "delete", "plan",
    "open-pr", "trigger", "verify-project", "verify-repo", "verify-git-secret", "delete-gitea-token", "project-healthcheck",
    "project-show", "project-set", "resource-set", "global-set", "secret-set",
    "simulate-setup", "simulate-run", "simulate-check", "simulate-teardown",
    "start-sensor", "stop-sensor", "sensor-status",
    "create-gitea-branch", "commit-gitea-file", "create-gitea-pr", "merge-gitea-pr", "merge-results-pr",
}


def test_every_expected_command_is_registered():
    assert EXPECTED_COMMANDS <= set(cli.commands)


def test_there_are_31_commands():
    assert len(cli.commands) == 31


def test_every_command_has_help_text():
    assert all(command.help for command in cli.commands.values())


def test_the_group_is_a_click_group():
    assert isinstance(cli, click.Group)


def test_entity_configs_name_the_two_gitea_repos():
    assert set(common.ENTITY_CONFIGS) == {"trigger", "results"}
    assert set(common.SECRET_CONFIGS) == {"trigger", "results", "dataset"}


def test_entity_option_offers_the_entity_configs_and_defaults_to_trigger():
    option = common.entity_option(click.command()(lambda entity: None)).params[0]

    assert list(option.type.choices) == list(common.ENTITY_CONFIGS)
    assert option.default == "trigger"


def test_each_entity_has_its_own_token_name_and_scope():
    trigger, results = common.TriggerRepoConfig, common.ResultsRepoConfig

    assert trigger.token_scope == "read:repository"
    assert results.token_scope == "write:repository"
    assert trigger.model_fields["token_name"].default != results.model_fields["token_name"].default


def test_env_file_option_wins_over_dev_env_and_the_shell(tmp_path, monkeypatch):
    (tmp_path / ".dev.env").write_text("FNCLI_TEST_VALUE=dev\n")
    (tmp_path / ".other.env").write_text("FNCLI_TEST_VALUE=other\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FNCLI_TEST_VALUE", "shell")

    result = CliRunner().invoke(cli, ["--env-file", ".other.env", "hello-world"])

    assert result.exit_code == 0, result.output
    assert os.environ["FNCLI_TEST_VALUE"] == "other"


def test_a_missing_env_file_is_a_clean_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(cli, ["--env-file", ".nope.env", "hello-world"])

    assert result.exit_code == 1
    assert ".nope.env not found" in result.output
