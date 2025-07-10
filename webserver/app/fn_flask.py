# A custom Flask wrapper to handle pagination globally

from flask import Flask, request
from flask_sqlalchemy.pagination import QueryPagination


class FNFlask(Flask):
    def make_response(self, rv):
        """
        Only handle the special case of QueryPagination where this has to be restructured
        into a json format.
        The other responses should already be of a valid format (list, json, text)
        """
        body, status_code = rv
        if isinstance(body, QueryPagination):
            page = int(request.values.get("page", '1'))
            per_page = int(request.values.get("per_page", '25'))
            jsonized = {"items": []}
            for obj in body.items:
                jsonized["items"].append(obj.sanitized_dict())
            jsonized["page"] = page
            jsonized["per_page"] = per_page
            jsonized["total"] = body.total
            jsonized["pages"] = body.pages
            return super().make_response((jsonized, status_code))
        return super().make_response(rv)
