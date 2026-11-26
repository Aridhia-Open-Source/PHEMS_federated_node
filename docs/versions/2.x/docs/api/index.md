# API reference

The Federated Node REST API, rendered from the `openapi.json` committed with this version of the node.

## Postman

A Postman collection of the same routes, with sign-in done for you, and an empty environment:

- [fn.postman_collection.json](fn.postman_collection.json)
- [fn.postman_environment.json](fn.postman_environment.json)

In Postman, use Import > Link with each file's address (right-click, copy link). Select the environment **Federated Node** and fill in `baseUrl` (nexus-api's URL), `username` and `password`. Each request signs in through `POST /login` when it has no token or the token is about to expire.

<swagger-ui src="openapi.json"/>
