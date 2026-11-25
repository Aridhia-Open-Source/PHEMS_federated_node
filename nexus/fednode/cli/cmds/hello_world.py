import click


@click.command("hello-world")
def hello_world_command():
    """Print a greeting, to check the fncli CLI is installed and running."""
    click.echo("Hello, world!")


COMMANDS = [hello_world_command]
