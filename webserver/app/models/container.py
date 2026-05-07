import re
from sqlalchemy import Column, Integer, String, ForeignKey, or_, and_
from sqlalchemy.orm import relationship
from app.helpers.base_model import BaseModel, db
from app.models.registry import Registry
from app.helpers.exceptions import ContainerRegistryException, InvalidRequest


class Container(db.Model, BaseModel):
    __tablename__ = 'containers'

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
        if not (re.match(r'^\w[\w\.\-/]+\w:[\w\.\-]+$', img_with_tag) or re.match(r'^\w[\w\.\-/]+\w@(sha256:)?[a-fA-F0-9]{7,64}$', img_with_sha)):
            raise InvalidRequest(
                f"{img_with_tag} does not have a tag or is malformed. Please provide one in the format <registry>/<image>:<tag> or <registry>/<image>@sha256.."
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
        base = Container.query.filter_by(name=name, registry_id=registry.id)

        # Static whitelist checks (no registry call needed)
        checks = [and_(Container.tag == None, Container.sha == None)]
        if sha:
            checks.append(and_(Container.sha == sha, or_(Container.tag == None, Container.tag == tag)))
        elif tag:
            checks.append(and_(Container.tag == tag, Container.sha == None))

        if base.filter(or_(*checks)).first():
            return True

        # Resolve tag to SHA if SHA-restricted entries exist for this image
        if tag and not sha and base.filter(Container.sha != None).first():
            remote_sha = registry.get_registry_class().get_tag_sha(name, tag)
            if remote_sha and base.filter(Container.sha == remote_sha, or_(Container.tag == None, Container.tag == tag)).first():
                return True

        return False

    def full_image_name(self):
        if self.sha:
            return f"{self.registry.url}/{self.name}@{self.sha}"

        return f"{self.registry.url}/{self.name}:{self.tag}"
