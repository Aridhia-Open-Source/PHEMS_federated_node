# FN db connector

This image aims to act as a data fetcher for all supported db engines.

It's a simple python module where [classes.py](./classes.py) standardises the way of creating a connection string/object that is then used by [connector.py](./connector.py) to establishing a connection, and executing a query.

After that, the results will be put into a file defined by `INPUT_FILE` environment variable.

This file will be the passed to the task's pod.

__This will only be used when the task definition (or the `/tasks` request body) has `db_query` field, meaning the docker image requested by the user is not able to connect to a db.__
