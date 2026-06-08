# FN db connector

This image aims to act as a data fetcher for all supported db engines.

It's a simple python module where [classes.py](./classes.py) standardises the way of creating a connection string/object that is then used by [connector.py](./connector.py) to establishing a connection, and executing a query.

After that, the results will be put into a file defined by `INPUT_FILE` environment variable.

This file will be the passed to the task's pod.

__This will only be used when the task definition (or the `/tasks` request body) has `db_query` field, meaning the docker image requested by the user is not able to connect to a db.__

## Development

### Locking dependencies

Several packages in this project (`mariadb`, `mysqlclient`, `psycopg2`, `pyodbc`) are C extensions that
require native system libraries to compile. These libraries must be installed before running `pip-compile`.

On Debian/Ubuntu:

```bash
sudo apt-get install -y \
    libmariadb-dev \
    libpq-dev \
    unixodbc-dev \
    pkg-config \
    build-essential
```
