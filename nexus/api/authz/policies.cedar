// The standard access rules (ADR 0037). Nothing is allowed unless a permit matches; a forbid always wins.
// Grants arrive in context.grants as one expiry per relation (epoch seconds); context.now is the time.

// manage allows everything, including changing the record's grants.
permit (principal, action, resource)
when { context.grants has manage && context.grants.manage > context.now };

// write, execute and assign each allow their own action, until they expire.
permit (principal, action == Action::"write", resource)
when { context.grants has write && context.grants.write > context.now };
permit (principal, action == Action::"execute", resource)
when { context.grants has execute && context.grants.execute > context.now };
permit (principal, action == Action::"assign", resource)
when { context.grants has assign && context.grants.assign > context.now };

// operate turns things on or off and backfills; write includes it.
permit (principal, action == Action::"operate", resource)
when {
  (context.grants has operate && context.grants.operate > context.now) ||
  (context.grants has write && context.grants.write > context.now)
};

// Any current grant lets you read the record.
permit (principal, action == Action::"read", resource)
when {
  (context.grants has read && context.grants.read > context.now) ||
  (context.grants has write && context.grants.write > context.now) ||
  (context.grants has operate && context.grants.operate > context.now) ||
  (context.grants has execute && context.grants.execute > context.now) ||
  (context.grants has assign && context.grants.assign > context.now)
};

// Admins and the operator may create global records.
permit (principal in Group::"/roles/admins", action == Action::"write", resource == Global::"0");
permit (principal in Group::"/roles/service", action == Action::"write", resource == Global::"0");

// Admins may read and assign any global record.
permit (principal in Group::"/roles/admins", action in [Action::"read", Action::"assign"], resource in Global::"0");

// Dagster reads every record: it runs the pipelines for all of them.
permit (principal in Role::"Dagster", action == Action::"read", resource);

// SuperUser may do anything.
permit (principal in Role::"SuperUser", action, resource);

// write and manage stay with admins (ADR 0037): a Users account or group granted them still cannot use them, so a
// manage holder cannot hand the record, or its grants, to a normal user.
forbid (principal in Role::"Users", action in [Action::"write", Action::"manage"], resource);

// Nobody runs tasks on a revoked dataset.
forbid (principal, action == Action::"execute", resource is Dataset)
when { resource.revoked };
