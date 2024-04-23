from base64 import b64encode
import requests
import json
import os
import logging

logger = logging.getLogger('acr_handler')
logger.setLevel(logging.INFO)

# this might be in a config map, so we can handle this dynamically
URLS = {
    "hub.docker.com": {
        "login": {"url": "https://hub.docker.com/v2/users/login/", "auth_type": "json", "token_field": "token"},
        "tags": {"url": "https://hub.docker.com/v2/repositories/%(image)s/tags"}
    },
    "azurecr.io": {
        "login": {"url": "https://%(service)s/oauth2/token?service=%(service)s&scope=repository:%(repo)s:metadata_read", "auth_type": "basic", "token_field": "access_token"},
        "tags": {"url": "https://%(service)s/v2/%(image)s/tags/list"}
    },
    "ghcr.io": {
        "login": {},
        "tags": {"url": "https://api.github.com/orgs/%(organization)s/packages/container/%(image_no_org)s/versions"}
    }
}

class ACRClient:
    """
    Class to handle a set of ACR actions
    """
    def __init__(self) -> None:
        self.acrs = json.load(open(os.getenv('FLASK_APP') + '/acr/acrlist.json'))
        for acr in self.acrs.keys():
            self.acrs[acr]["login"] = self.needs_auth(acr)
            url_key = self.map_registry_to_url(acr)
            if URLS[url_key]["login"].get("auth_type") == "basic":
                self.acrs[acr]["auth"] = b64encode(f"{self.acrs[acr]['username']}:{self.acrs[acr]['password']}".encode()).decode()
            elif URLS[url_key]["login"].get("auth_type") == "json":
                self.acrs[acr]["auth"] = {"username": self.acrs[acr]['username'], "password": self.acrs[acr]['password']}
            else:
                self.acrs[acr]["auth"] = self.acrs[acr]["password"]

    def login(self, acr_url:str, acr_cred:str, image:str):
        """
        Get an access token from the ACR, works on Azure, should be double checked
        on other services
        """
        url_key = self.map_registry_to_url(acr_url)
        request_args = {
            "url": URLS[url_key]["login"]["url"] % {"service": acr_url, "repo": image}
        }
        if URLS[url_key]["login"]["auth_type"] == "basic":
            request_args["headers"] = {"Authorization": f"Basic {acr_cred}"}
        else:
            request_args["headers"] = {"Content-Type": "application/json"}
            request_args["json"] = acr_cred

        response_auth = requests.get(**request_args)

        if not response_auth.ok:
            return False

        return response_auth.json()[URLS[url_key]["login"]["token_field"]]

    def map_registry_to_url(self, acr):
        """
        """
        return list(filter(lambda x: x in acr, URLS.keys()))[0]

    def needs_auth(self, acr):
        """
        Some services do not need authentication in the form of Basic user:pass base64 token
        """
        url_key = self.map_registry_to_url(acr)
        return URLS[url_key]["login"] != {}

    def parse_image_and_tag(self, image:str):
        """
        Simple string parse, to split the image name from the tag
        if tag doesn't exist, return latest
        """
        if ":" in image:
            return image.split(":")
        return image, "latest"

    def get_url_string_params(self, acr:str, image_name:str):
        return {
            "service": acr,
            "image": image_name,
            "organization": image_name.split("/")[0] if "/" in image_name else image_name,
            "image_no_org": image_name.split("/")[1] if "/" in image_name else image_name
        }

    def find_image_repo(self, image:str) -> bool:
        """
        Works as an existence check. If the tag for the image
        has the requested tag in the list of available tags
        return True.
        This should work on any docker Registry v2 as it's a standard
        """
        image_name, tag = self.parse_image_and_tag(image)
        tags_list = []
        for acr in self.acrs.keys():
            if self.acrs[acr]["login"]:
                token = self.login(acr, self.acrs[acr]['auth'], image_name)
            else:
                token = self.acrs[acr]['auth']
            if not token:
                continue

            url_key = self.map_registry_to_url(acr)
            try:
                response_metadata = requests.get(
                    URLS[url_key]["tags"]["url"] % self.get_url_string_params(acr, image_name),
                    headers={"Authorization": f"Bearer {token}"}
                )
                if response_metadata.ok:
                    tags_list = response_metadata.json()
                    break
                else:
                    logger.info(response_metadata.text)
            except ConnectionError as ce:
                logger.info(ce.strerror)

        # Try for open repos?
        if not tags_list:
            return False

        full_image = f"{acr}/{image}"
        if "results" in tags_list:
            return full_image if tag in [t["name"] for t in tags_list["results"]] else False
        elif "tags" not in tags_list:
            return full_image if tag in [t for tags in tags_list for t in tags["metadata"]["container"]["tags"]] else False
        return full_image if tag in tags_list["tags"] else False
