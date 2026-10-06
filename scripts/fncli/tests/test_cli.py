import click

from fncli.cli import cli
from fncli.cmds import common

EXPECTED_COMMANDS = {
    "hello-world",
    "setup-project", "open-pr", "teardown-project", "setup-backend", "teardown-backend",
    "setup-gitea", "teardown-gitea", "verify-project", "verify-repo",
    "init-backend-project", "delete-backend-project", "project-healthcheck",
    "init-gitea-repo", "delete-gitea-repo", "init-backend-trigger-repo",
    "init-backend-results-repo", "delete-backend-trigger-repo", "delete-backend-results-repo",
    "init-git-secret", "init-dataset-secret", "init-backend-secret", "verify-git-secret",
    "delete-secret", "delete-gitea-token",
    "init-backend-dataset", "delete-backend-dataset",
    "create-gitea-branch", "commit-gitea-file", "create-gitea-pr", "merge-gitea-pr",
}


def test_every_expected_command_is_registered():
    assert EXPECTED_COMMANDS <= set(cli.commands)


def test_there_are_34_commands():
    assert len(cli.commands) == 34


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
