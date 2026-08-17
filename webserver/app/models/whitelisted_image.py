import re
from sqlalchemy import Column, Integer, String, ForeignKey, or_, and_
from sqlalchemy.orm import relationship
from app.helpers.base_model import BaseModel, db
from app.models.registry import Registry
from app.helpers.exceptions import ContainerRegistryException, InvalidRequest


class WhitelistedImage(db.Model, BaseModel):
    __tablename__ = 'whitelisted_images'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(256), nullable=False)
    tag = Column(String(256), nullable=True)
    sha = Column(String(256), nullable=True)

    registry_id = Column(Integer, ForeignKey(Registry.id, ondelete='CASCADE'))
    registry = relationship("Registry")

    def __init__(
            self,
            name:str,
            registry:Registry,
            tag:str=None,
            sha:str=None
        ):
        self.name = name
        self.registry = registry
        self.tag = tag
        self.sha = sha

    @classmethod
    def validate(cls, data:dict):
        data = super().validate(data)

        reg = Registry.query.filter(Registry.url==data["registry"]).one_or_none()
        if reg is None:
            raise ContainerRegistryException(f"Registry {data["registry"]} could not be found")
        data["registry"] = reg

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
    def validate_image_whitelisted(cls, docker_image: str) -> bool:
        """
        Validate that the image is whitelisted in the database based on the following criteria:
        - Image-only: Neither tag nor SHA specified in DB (allows all versions).
        - Tag-only: Tag specified but no SHA in DB (allows matching tag).
        - SHA-restricted: SHA specified (and optionally tag) in DB (allows matching SHA/tag).
        
        If not immediately whitelisted, it resolves tags to SHAs remotely to check against
        SHA-restricted entries.
        """
        registry, name, tag, sha = Registry.extract_image_parts(docker_image)
        base = WhitelistedImage.query.filter_by(name=name, registry_id=registry.id)

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
