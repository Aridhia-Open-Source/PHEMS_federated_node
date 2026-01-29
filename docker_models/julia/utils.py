import subprocess

from dagster_pipes import open_dagster_pipes, PipesContext


def dagster_pipes_logging_redirect():
    with open_dagster_pipes():
        ctx = PipesContext()

        ctx.log.info("RUNNING entrypoint.py")

        proc = subprocess.Popen(
            [
                "julia",
                "--project=/project",
                "/project/src/main.jl",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,          # line-buffered
        )

        # Stream stdout
        for line in proc.stdout:
            ctx.log.info(line.rstrip())

        # Stream stderr
        for line in proc.stderr:
            ctx.log.error(line.rstrip())

        returncode = proc.wait()
        if returncode != 0:
            raise RuntimeError(f"Julia exited with code {returncode}")

        ctx.log.info("Julia process completed successfully")
        return returncode
