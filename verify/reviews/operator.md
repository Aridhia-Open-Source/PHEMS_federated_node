# Operator stack review (Claude)

## #690 kopf operator core

- `nexus/operator/nexus_operator/sync.py:169` - Repository uri/type are editable but are the nexus-api key; an edit creates a new record and orphans the old one. Fix: CEL `self == oldSelf` on uri and type, or delete the record found from `old`. [comment](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/pull/690#discussion_r4674991260)
- `k8s/federated-node/templates/_helpers.tpl:302` - "never the release namespace" is not enforced; listing it in `operator.watchNamespaces` gives the operator `secrets: get` on kc-secrets, which a NodeSecret can copy into nexus-api. Fix: `fail` in the helper. [comment](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/pull/690#discussion_r4674991264)

## #697 operator on grants

- `nexus/operator/nexus_operator/sync.py:77` - status.access records every wanted entry, even a group grant that already existed (e.g. from an access request); dropping it from the spec then deletes a grant the operator never made. Fix: delete only grants whose `created_by` is the operator, or record only what it added. [comment](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/pull/697#discussion_r4674996091)

## #698 operator nexus secrets

- No findings.

## #696 shared nexus client

- `nexus/client/nexus_client/http.py:111` - the retry is now mounted by default and urllib3 honours Retry-After up to 6 h; a long 429 stalls a sensor tick or operator handler. Fix: `retry_after_max` of a few seconds. [comment](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/pull/696#discussion_r4675005221)

## #718 shared outbound client layer

- `nexus/api/app/clients/outbound.py:63` - Retry-After honoured up to 6 h (urllib3 default), outside the read timeout; a long 429 holds request threads, and `keycloak_is_up` holds the ttl_cache lock meanwhile so /health_check queues. Fix: `retry_after_max` of a few seconds. [comment](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/pull/718#discussion_r4675004957)
