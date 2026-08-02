# Model & API Changes: MVP Implementation

This document outlines the specific code changes needed to implement the MVP schema (Repository → Dataset + PullRequest status tracking).

---

## Models to Change

### 1. Repository (`webserver/app/models/repository.py`)

**Current issues:**
- Line 23: `default_dataset_id = Column(String(256), nullable=True)` — column name doesn't match usage
- Lines 87, 97, 103: code references `default_dataset_name` but column is `default_dataset_id`
- No actual FK to Dataset

**Changes needed:**

```python
# OLD:
default_dataset_id = Column(String(256), nullable=True)

# NEW:
dataset_id = Column(Integer, ForeignKey('datasets.id'), nullable=False)
dataset = relationship("Dataset", back_populates="repositories")
```

**Update __init__ signature:**
```python
def __init__(
    self,
    uri: str,
    watch_dir: str,
    dataset_id: int,  # NEW: required
    base_branch: str = 'main',
    initial_cursor: dt | None = None,
):
    self.uri = uri
    self.watch_dir = watch_dir
    self.dataset_id = dataset_id  # NEW
    self.base_branch = base_branch
    self.initial_cursor = initial_cursor
```

**Update sanitized_dict():**
```python
def sanitized_dict(self):
    return {
        'id': self.id,
        'uri': self.uri,
        'path': self.path,
        'watch_dir': self.watch_dir,
        'base_branch': self.base_branch,
        'dataset_id': self.dataset_id,  # CHANGED from default_dataset_name
        'pr_cursor': self.get_pull_request_cursor(),
        'pr_count': len(self.pull_requests)
    }
```

**Remove unused method reference:**
- Remove any reference to `default_dataset_name` property if it exists

---

### 2. Dataset (`webserver/app/models/dataset.py`)

**Current:**
- Line 42: `repository_id = Column(Integer, ForeignKey('repositories.id'), nullable=True)`
- Dataset has a backward relationship to Repository

**Change:**
- Keep `repository_id` FK (or remove if it's not used elsewhere)
- Add backward relationship:
  ```python
  repositories = relationship("Repository", back_populates="dataset")
  ```

**Note:** Need to check if `repository_id` on Dataset is actually used anywhere. If not, can remove it.

---

### 3. PullRequest (`webserver/app/models/pull_request.py`)

**Current issues:**
- Line 38-40: `dataset_id` is part of composite PK — need to remove

**Changes needed:**

```python
# OLD:
class PullRequest(db.Model, BaseModel):
    number = sa.Column(sa.Integer, nullable=False, primary_key=True)
    ...
    repository_id = sa.Column(..., primary_key=True)
    dataset_id = sa.Column(..., primary_key=True)  # REMOVE THIS

# NEW:
class PullRequest(db.Model, BaseModel):
    number = sa.Column(sa.Integer, nullable=False, primary_key=True)
    ...
    repository_id = sa.Column(..., primary_key=True)
    # dataset_id REMOVED from PK

    status = sa.Column(sa.String(32), nullable=False, default='UNKNOWN')  # Already exists
```

**Update __init__:**
```python
def __init__(
    self,
    repository_id: int,
    number: int,
    title: str,
    raised_by: str,
    merged_at: dt,
    merge_commit_sha: str,
    # dataset_id: int | None = None,  # REMOVE THIS PARAMETER
    status: str = PullRequestStatus.UNKNOWN.value,
    spec: dict | None = None,
):
    self.repository_id = repository_id
    self.number = number
    # self.dataset_id = dataset_id  # REMOVE THIS LINE
    self.title = title
    self.raised_by = raised_by
    self.merged_at = merged_at
    self.spec = spec or {}
    self.merge_commit_sha = merge_commit_sha
    self.status = status
```

---

## Migrations to Create

### Migration: `xxxx_fix_repository_dataset_relationship.py`

```python
def upgrade() -> None:
    # 1. Drop old columns from repositories table
    op.drop_column('repositories', 'default_dataset_id')
    op.drop_column('repositories', 'default_dataset_name')
    
    # 2. Add dataset_id FK to repositories
    op.add_column('repositories', 
        sa.Column('dataset_id', sa.Integer(), nullable=False)
    )
    op.create_foreign_key(
        'fk_repositories_dataset_id',
        'repositories', 'datasets',
        ['dataset_id'], ['id'],
        ondelete='RESTRICT'
    )

def downgrade() -> None:
    op.drop_constraint('fk_repositories_dataset_id', 'repositories', type_='foreignkey')
    op.drop_column('repositories', 'dataset_id')
    op.add_column('repositories',
        sa.Column('default_dataset_name', sa.String(length=256), nullable=True)
    )
```

### Migration: `xxxx_remove_dataset_id_from_pull_request_pk.py`

```python
def upgrade() -> None:
    # 1. Drop the old composite PK
    op.drop_constraint('pk_pull_requests', 'pull_requests', type_='primary')
    
    # 2. Drop dataset_id column and its FK
    op.drop_constraint('fk_pull_requests_dataset_id', 'pull_requests', type_='foreignkey')
    op.drop_column('pull_requests', 'dataset_id')
    
    # 3. Create new composite PK (repository_id, number only)
    op.create_primary_key('pk_pull_requests', 'pull_requests', ['repository_id', 'number'])
    
    # 4. Update index
    op.drop_index('ix_pull_requests_status', 'pull_requests')
    op.create_index('ix_pull_requests_status', 'pull_requests', ['repository_id', 'status'])

def downgrade() -> None:
    op.drop_index('ix_pull_requests_status', 'pull_requests')
    op.drop_constraint('pk_pull_requests', 'pull_requests', type_='primary')
    op.add_column('pull_requests',
        sa.Column('dataset_id', sa.Integer(), nullable=True)
    )
    op.create_foreign_key('fk_pull_requests_dataset_id', 'pull_requests', 'datasets', ['dataset_id'], ['id'], ondelete='CASCADE')
    op.create_primary_key('pk_pull_requests', 'pull_requests', ['repository_id', 'number', 'dataset_id'])
    op.create_index('ix_pull_requests_status', 'pull_requests', ['repository_id', 'dataset_id', 'status'])
```

---

## API Changes

### `webserver/app/repositories_api.py`

**POST /repositories (create):**
```python
@bp.route('/', methods=['POST'])
def post_repository():
    body = request.json or {}
    
    if not body.get('uri'):
        raise InvalidRequest("uri is required")
    if not body.get('dataset_id'):
        raise InvalidRequest("dataset_id is required")
    
    uri = body['uri'].lower().rstrip('/')
    if Repository.query.filter(Repository.uri == uri).one_or_none():
        raise InvalidRequest(f"Repository {uri} already exists")
    
    # Validate dataset exists
    dataset = Dataset.get_by_id(body['dataset_id'])
    
    repo = Repository(
        uri=uri,
        watch_dir=body.get('watch_dir', ''),
        dataset_id=body['dataset_id'],  # CHANGED
        base_branch=body.get('base_branch', 'main'),
        initial_cursor=body.get('initial_cursor'),
    )
    repo.add()
    return repo.sanitized_dict(), HTTPStatus.CREATED
```

**PATCH /repositories/<id> (update):**
```python
@bp.route('/<int:repo_id>', methods=['PATCH'])
def patch_repository(repo_id):
    repo = Repository.get_by_id(repo_id)
    body = request.json or {}
    
    if not body:
        raise InvalidRequest("No fields provided to update")
    
    if 'dataset_id' in body:
        dataset = Dataset.get_by_id(body['dataset_id'])
        repo.dataset_id = body['dataset_id']
    
    if 'base_branch' in body:
        if not body['base_branch']:
            raise InvalidRequest("base_branch cannot be empty")
        repo.base_branch = body['base_branch']
    
    if 'watch_dir' in body:
        if not body['watch_dir']:
            raise InvalidRequest("watch_dir cannot be empty")
        repo.watch_dir = body['watch_dir']
    
    # Remove default_dataset_name handling
    # if 'default_dataset_name' in body:
    #     repo.default_dataset_name = body['default_dataset_name']
    
    if 'initial_cursor' in body:
        repo.initial_cursor = body['initial_cursor']
    
    session.commit()
    return repo.sanitized_dict(), HTTPStatus.OK
```

**POST /repositories/<repo_id>/pull_requests/batch (create PRs):**
```python
@bp.route('/<int:repo_id>/pull_requests/batch', methods=['POST'])
def post_pull_requests_batch(repo_id):
    repository = Repository.get_by_id(repo_id)
    body = request.json or []
    
    if not isinstance(body, list):
        raise InvalidRequest("Body must be a list of pull requests")
    
    if len(body) > 100:
        raise InvalidRequest("Maximum 100 pull requests per batch")
    
    if not body:
        return [], HTTPStatus.CREATED
    
    created_prs = []
    for pr_data in body:
        try:
            required = ['number', 'title', 'raised_by', 'merged_at', 'merge_commit_sha', 'spec']
            missing = [f for f in required if f not in pr_data]
            if missing:
                raise InvalidRequest(f"Missing required fields in PR: {', '.join(missing)}")
            
            if 'status' in pr_data:
                if pr_data['status'] not in [s.value for s in PullRequestStatus]:
                    raise InvalidRequest(f"Invalid status: {pr_data['status']}")
            
            status = pr_data.get('status', PullRequestStatus.UNKNOWN.value)
            pr = PullRequest(
                repository_id=repo_id,
                number=pr_data['number'],
                title=pr_data['title'],
                raised_by=pr_data['raised_by'],
                merged_at=pr_data['merged_at'],
                merge_commit_sha=pr_data['merge_commit_sha'],
                spec=pr_data.get('spec', {}),
                # dataset_id=pr_data.get('dataset_id'),  # REMOVED
                status=status,
            )
            pr.add(commit=False)
            created_prs.append(pr)
        except Exception as e:
            session.rollback()
            raise InvalidRequest(f"Error creating PR #{pr_data.get('number', '?')}: {str(e)}")
    
    session.commit()
    return [_pr_to_dict(pr) for pr in created_prs], HTTPStatus.CREATED
```

---

## Summary of Changes

| Component | Change |
|-----------|--------|
| Repository.dataset_id | Add FK (required) |
| Repository.default_dataset_id/name | Remove both |
| PullRequest.dataset_id | Remove from composite PK |
| PullRequest.__init__ | Remove dataset_id parameter |
| API POST /repositories | Require dataset_id |
| API PATCH /repositories | Allow dataset_id update, remove default_dataset_name |
| API POST /pull_requests/batch | Remove dataset_id handling |
| Migrations | 2 new migrations |

---

## Testing Checklist

- [ ] Create repository with dataset_id → works
- [ ] GET /repositories returns sanitized_dict with dataset_id
- [ ] PATCH repository dataset_id → updates correctly
- [ ] Create PR without dataset_id → works
- [ ] GET pull_requests filters by repository_id + status
- [ ] Composite PK (repository_id, number) prevents duplicates
- [ ] Old default_dataset_name column doesn't exist
