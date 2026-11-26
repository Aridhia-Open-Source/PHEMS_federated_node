// The standard access rules (ADR 0037). Nothing is allowed unless a permit matches; a forbid always wins.
// Every rule is named Model.Action.Context in its @id (* for every model); nexus-api logs the ids of the rules that
// decide each request, and roles.yaml names the ones a role holds.
// Grants arrive in context.grants as one expiry per relation (epoch seconds); context.now is the time.

// Grants. Every caller holds these; the grant on the record decides.

// manage allows everything, including changing the record's grants.
@id("*.all.owner")
permit (principal, action, resource)
when { context.grants has manage && context.grants.manage > context.now };

// write, execute and assign each allow their own action, until they expire.
@id("*.write.granted")
permit (principal, action in Action::"write", resource)
when { context.grants has write && context.grants.write > context.now };
@id("*.execute.granted")
permit (principal, action in Action::"execute", resource)
when { context.grants has execute && context.grants.execute > context.now };
@id("*.assign.granted")
permit (principal, action in Action::"assign", resource)
when { context.grants has assign && context.grants.assign > context.now };

// operate turns things on or off and backfills; write includes it.
@id("*.operate.granted")
permit (principal, action in Action::"operate", resource)
when {
  (context.grants has operate && context.grants.operate > context.now) ||
  (context.grants has write && context.grants.write > context.now)
};

// Any current grant lets you read the record.
@id("*.read.granted")
permit (principal, action in Action::"read", resource)
when {
  (context.grants has read && context.grants.read > context.now) ||
  (context.grants has write && context.grants.write > context.now) ||
  (context.grants has operate && context.grants.operate > context.now) ||
  (context.grants has execute && context.grants.execute > context.now) ||
  (context.grants has assign && context.grants.assign > context.now)
};

// Permissions held through roles.yaml.

// Admins and the operator may create global records.
@id("global.write.all")
permit (principal in Permission::"global.write.all", action == Action::"global.write", resource == Global::"0");

// Admins may read and assign any global record.
@id("global.read.all")
permit (principal in Permission::"global.read.all", action in Action::"read", resource in Global::"0");
@id("global.assign.all")
permit (principal in Permission::"global.assign.all", action in Action::"assign", resource in Global::"0");

// Dagster reads every record: it runs the pipelines for all of them.
@id("*.read.all")
permit (principal in Permission::"*.read.all", action in Action::"read", resource);

// SuperUser may do anything a forbid does not stop.
@id("*.all.superuser")
permit (principal in Permission::"*.all.superuser", action, resource);

// Refusals. A forbid always wins, SuperUser included.

// write and manage stay with admins (ADR 0037): a Users account or group granted them still cannot use them, so a
// manage holder cannot hand the record, or its grants, to a normal user. The one rule that names a role.
@id("*.write.users")
forbid (principal in Role::"Users", action in Action::"write", resource);
@id("*.manage.users")
forbid (principal in Role::"Users", action in Action::"manage", resource);

// Nobody runs tasks on a revoked dataset.
@id("dataset.execute.revoked")
forbid (principal, action == Action::"dataset.execute", resource is Dataset)
when { resource.revoked };
