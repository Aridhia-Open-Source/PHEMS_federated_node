import re

import sqlalchemy as sa
from sqlalchemy import and_, or_
from sqlalchemy.orm import relationship

from app.helpers.base_model import BaseModel, db
from app.models import Models
from app.models.extras.registry import Registry
from app.helpers.exceptions import ContainerRegistryException, InvalidRequest


class WhitelistedImage(db.Model, BaseModel):
    """
    Which images a project is permitted to run.
    """

    __tablename__ = 'whitelisted_images'

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    registry_id = sa.Column(sa.Integer, sa.ForeignKey('registries.id', ondelete='CASCADE'), nullable=True)
    project_id = sa.Column(
        sa.Integer, sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False
    )

    name = sa.Column(sa.String(256), nullable=False)
    tag = sa.Column(sa.String(256), nullable=True)
    sha = sa.Column(sa.String(256), nullable=True)

    registry = relationship("Registry")
    project = relationship("Project", back_populates="whitelisted_images")

    def __init__(
        self,
        name: str,
        registry: Registry,
        project_id: int,
        tag: str | None = None,
        sha: str | None = None
    ):
        self.name = name
        self.registry = registry
        self.project_id = project_id
        self.tag = tag
        self.sha = sha

    @classmethod
    def validate(cls, data:dict):
        data = super().validate(data)

        reg = Registry.query.filter(Registry.url==data["registry"]).one_or_none()
        if reg is None:
            raise ContainerRegistryException(f"Registry {data["registry"]} could not be found")
        data["registry"] = reg

        project = Models.Project.query.filter(
            Models.Project.id == data["project_id"]
        ).one_or_none()
        if project is None:
            raise InvalidRequest(f"Project {data["project_id"]} could not be found")

        img_with_tag = f"{data["name"]}:{data.get("tag")}"
        img_with_sha = f"{data["name"]}@{data.get("sha")}"

        cls.validate_image_format(img_with_tag, img_with_sha)
        return data

    @classmethod
    def validate_image_format(cls, img_with_tag, img_with_sha):
        tag_ok = re.match(r'^\w[\w\.\-/]+\w:[\w\.\-]+$', img_with_tag)
        sha_ok = re.match(r'^\w[\w\.\-/]+\w@(sha256:)?[a-fA-F0-9]{7,64}$', img_with_sha)
        if not (tag_ok or sha_ok):
            raise InvalidRequest(
                f"{img_with_tag} does not have a tag or is malformed. Please provide one in "
                "the format <registry>/<image>:<tag> or <registry>/<image>@sha256.."
            )

    @classmethod
    def validate_image_whitelisted(cls, docker_image: str, project_id: int) -> bool:
        """
        Validate that the image is whitelisted for this project, based on the following criteria:
        - Image-only: Neither tag nor SHA specified in DB (allows all versions).
        - Tag-only: Tag specified but no SHA in DB (allows matching tag).
        - SHA-restricted: SHA specified (and optionally tag) in DB (allows matching SHA/tag).
        
        If not immediately whitelisted, it resolves tags to SHAs remotely to check against
        SHA-restricted entries.
        """
        registry, name, tag, sha = Registry.extract_image_parts(docker_image)
        base = WhitelistedImage.query.filter_by(
            name=name, registry_id=registry.id, project_id=project_id
        )

        # Static whitelist checks (no registry call needed)
        checks = [and_(WhitelistedImage.tag == None, WhitelistedImage.sha == None)]
        if sha:
            checks.append(and_(
                WhitelistedImage.sha == sha,
                or_(WhitelistedImage.tag == None, WhitelistedImage.tag == tag)
            ))
        elif tag:
            checks.append(and_(WhitelistedImage.tag == tag, WhitelistedImage.sha == None))

        if base.filter(or_(*checks)).first():
            return True

        # Resolve tag to SHA if SHA-restricted entries exist for this image
        if tag and not sha and base.filter(WhitelistedImage.sha != None).first():
            remote_sha = registry.get_registry_class().get_tag_sha(name, tag)
            matches_sha = base.filter(
                WhitelistedImage.sha == remote_sha, or_(WhitelistedImage.tag == None, WhitelistedImage.tag == tag)
            ).first()
            if remote_sha and matches_sha:
                return True

        return False

    def full_image_name(self):
        if self.sha:
            return f"{self.registry.url}/{self.name}@{self.sha}"

        return f"{self.registry.url}/{self.name}:{self.tag}"
